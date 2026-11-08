from __future__ import annotations

import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, JobEvent, Paper, PaperBatch, PaperSource, Source, now
from .paths import configured_path
from scripts.fetch_openalex_batch import SOURCES as OPENALEX_SOURCES

VENUES = {"CVPR": "cvpr", "ICCV": "iccv", "ECCV": "eccv"}
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", value)).strip().rstrip(".")


def normalize_title(value: str) -> str:
    return re.sub(r"[^\w]+", " ", clean_title(value).casefold()).strip()


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I).lower()
    return value or None


def decode_abstract(index: dict | None) -> str | None:
    if index is None or index == {}:
        return None
    if not isinstance(index, dict):
        raise ValueError('Abstract inverted index must be an object')
    positions = {}
    for word, offsets in index.items():
        if not isinstance(word, str) or not isinstance(offsets, list):
            raise ValueError('Invalid abstract word or position list')
        for position in offsets:
            if type(position) is not int or position < 0 or position in positions:
                raise ValueError('Abstract positions must be unique nonnegative integers')
            positions[position] = word
    if not positions:
        return None
    if max(positions) != len(positions)-1:
        raise ValueError('Abstract positions are not contiguous')
    return ' '.join(positions[i] for i in range(len(positions))).strip() or None


def openalex_work_row(work: dict, venue: str, year: int) -> dict:
    title = clean_title(work.get("display_name") or "")
    if not title or work.get("publication_year") != year:
        raise ValueError("Missing title or wrong publication year")
    identifier = work['id']
    if not isinstance(identifier, str) or not re.fullmatch(r'https://openalex.org/W[0-9]+', identifier):
        raise ValueError('Invalid OpenAlex work identifier')
    return {
        "source_id": identifier,
        "source_url": identifier,
        "title": title,
        "year": year,
        "venue": venue,
        "doi": normalize_doi(work.get("doi")),
        "authors": [a["author"]["display_name"] for a in work.get("authorships", [])
                    if a.get("author", {}).get("display_name")],
        "abstract": decode_abstract(work.get("abstract_inverted_index")),
        "cited_by_count": work.get("cited_by_count"),
        "raw": work,
    }


def parse_dblp_xml(body: bytes, venue: str, year: int) -> list[dict]:
    if not body.lstrip().startswith(b"<?xml") and not body.lstrip().startswith(b"<dblp"):
        raise ValueError("DBLP did not return XML; check upstream access or venue/year")
    root = ET.fromstring(body)
    if root.tag != "dblp":
        raise ValueError("Unexpected DBLP XML root")
    papers = []
    for item in root:
        if item.tag != "inproceedings":
            continue
        key = item.get("key", "")
        if not key.startswith(f"conf/{VENUES[venue]}/"):
            continue
        item_year = item.findtext("year")
        if item_year != str(year):
            continue
        title_node = item.find("title")
        title = clean_title("".join(title_node.itertext())) if title_node is not None else ""
        if not title:
            continue
        ee = item.findtext("ee")
        doi = normalize_doi(item.findtext("ee") if ee and "doi.org/" in ee else None)
        record = {
            "source_id": key,
            "title": title,
            "year": year,
            "venue": venue,
            "dblp_key": key,
            "doi": doi,
            "authors": ["".join(a.itertext()).strip() for a in item.findall("author")],
            "source_url": f"https://dblp.org/rec/{key}",
            "ee": ee,
        }
        record["raw"] = {"dblp_xml": ET.tostring(item, encoding="unicode"), "parsed": record.copy()}
        papers.append(record)
    return papers


def fetch_dblp(venue: str, year: int, session: requests.Session, retries: int = 3) -> list[dict]:
    from .dblp import DblpAccessError, check_access, fetch_search
    slug = VENUES[venue]
    url = f"https://dblp.org/db/conf/{slug}/{slug}{year}.xml"
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "tupu-research-ingest/0.4 (metadata only)"})
            check_access(response)
            return parse_dblp_xml(response.content, venue, year)
        except DblpAccessError:
            # A verification page is not a transient XML parse failure.
            raise
        except (requests.RequestException, ValueError, ET.ParseError):
            if attempt + 1 == retries:
                return fetch_search(venue, year, session, retries=retries)
            time.sleep(min(2 ** attempt, 8))
    raise ValueError("DBLP retries must be positive")


def fetch_openalex(doi: str, session: requests.Session, retries: int = 3) -> dict | None:
    url = "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe="/")
    params = {}
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=TIMEOUT)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return {
                "source_id": data["id"],
                "source_url": data["id"],
                "doi": normalize_doi(data.get("doi")),
                "abstract": decode_abstract(data.get("abstract_inverted_index")),
                "cited_by_count": data.get("cited_by_count"),
                "authors": [a.get("author", {}).get("display_name") for a in data.get("authorships", [])],
                "raw": data,
            }
        except (requests.RequestException, ValueError, KeyError):
            if attempt + 1 == retries:
                raise
            time.sleep(min(2 ** attempt, 8))
    return None


def upsert_paper(db: Session, row: dict, source: str = "dblp", paper: Paper | None = None, job: Job | None = None) -> Paper:
    from .paper_quality import is_front_matter
    if is_front_matter(row):
        raise ValueError("Non-paper proceedings material excluded")
    if 'authors' in row and (not isinstance(row['authors'], list) or any(not isinstance(author, str) for author in row['authors'])):
        raise ValueError('Authors must be a list of names')
    doi = normalize_doi(row.get('doi'))
    source_id = row['source_id']
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError('Missing source identifier')
    existing_source = db.scalar(select(PaperSource).where(PaperSource.source == source, PaperSource.source_id == source_id))
    if existing_source:
        if paper is not None and paper.id != existing_source.paper_id:
            raise ValueError('Source identity conflicts with the supplied paper')
        paper = db.get(Paper, existing_source.paper_id)
        if row.get('_cached'):
            if job is not None and db.get(PaperBatch, (job.id, paper.id)) is None:
                db.add(PaperBatch(job_id=job.id, paper_id=paper.id, is_new=False))
            return paper
    if paper is None and doi:
        paper = db.scalar(select(Paper).where(Paper.doi == doi))
    if paper is None and row.get("dblp_key"):
        paper = db.scalar(select(Paper).where(Paper.dblp_key == row["dblp_key"]))
    if paper is None and row.get("title"):
        query = select(Paper).where(Paper.title_normalized == normalize_title(row['title']), Paper.year == row['year'], Paper.venue == row['venue'])
        if doi:
            query = query.where(Paper.doi.is_(None))
        if source == 'openalex':
            query = query.where((Paper.openalex_id.is_(None)) | (Paper.openalex_id == source_id))
        candidates = db.scalars(query.limit(2)).all()
        if len(candidates) == 1:
            candidate = candidates[0]
            incoming_names = {normalize_title(name) for name in row.get('authors', [])}
            known_names = {normalize_title(name) for name in json.loads(candidate.authors_json) if isinstance(name, str)}
            if not incoming_names or not known_names or incoming_names.intersection(known_names):
                paper = candidate
        elif len(candidates) > 1:
            raise ValueError('Ambiguous paper title; source identity requires manual review')
    if paper is not None:
        if doi and paper.doi and doi != paper.doi:
            raise ValueError('Conflicting DOI for an existing source record')
        if source == 'openalex' and paper.openalex_id and paper.openalex_id != source_id:
            raise ValueError('Conflicting OpenAlex identifiers; refusing to merge distinct works')
        if row.get('venue') and (paper.venue, paper.year) != (row['venue'], row['year']):
            raise ValueError('Existing source record has a different conference/year')
    is_new = paper is None
    if paper is None:
        key = "doi:" + doi if doi else f"{source}:" + source_id
        paper = Paper(canonical_key=key, title=row["title"], title_normalized=normalize_title(row["title"]), year=row["year"], venue=row["venue"])
        db.add(paper)
        db.flush()
    if source == "dblp":
        paper.title = row["title"]
        paper.title_normalized = normalize_title(row["title"])
        paper.year = row["year"]
        paper.venue = row["venue"]
        paper.dblp_key = row["dblp_key"]
        paper.authors_json = json.dumps(row.get('authors') or json.loads(paper.authors_json or '[]'), ensure_ascii=False)
        paper.source_url = row.get("source_url")
    elif source == "openalex":
        paper.openalex_id = source_id
        if not paper.dblp_key:
            paper.title = row.get("title") or paper.title
            paper.title_normalized = normalize_title(paper.title)
            paper.authors_json = json.dumps(row.get('authors') or json.loads(paper.authors_json or '[]'), ensure_ascii=False)
            paper.source_url = row.get("source_url")
        paper.abstract = row.get("abstract") or paper.abstract
        paper.cited_by_count = row.get("cited_by_count")
    else:
        paper.title = row["title"]
        paper.title_normalized = normalize_title(row["title"])
        paper.year = row["year"]
        paper.venue = row["venue"]
        paper.authors_json = json.dumps(row.get('authors') or json.loads(paper.authors_json or '[]'), ensure_ascii=False)
        paper.source_url = row.get("source_url")
    if source == "cvf":
        paper.abstract = row.get("abstract") or paper.abstract
    paper.doi = doi or paper.doi
    if existing_source is None or json.loads(existing_source.raw_json) != row.get('raw', row):
        paper.updated_at = now()
    if existing_source is None:
        existing_source = PaperSource(paper_id=paper.id, source=source, source_id=source_id, raw_json="{}")
        db.add(existing_source)
    from .models import SourceRevision
    db.flush()
    if existing_source.raw_json and existing_source.raw_json != "{}":
        old_hash = hashlib.sha256(existing_source.raw_json.encode()).hexdigest()
        if db.scalar(select(SourceRevision.id).where(SourceRevision.source_record_id == existing_source.id, SourceRevision.fingerprint == old_hash)) is None:
            db.add(SourceRevision(source_record_id=existing_source.id, fingerprint=old_hash, raw_json=existing_source.raw_json, recorded_at=existing_source.retrieved_at))
    new_json = json.dumps(row.get('raw', row), ensure_ascii=False)
    fingerprint = hashlib.sha256(new_json.encode()).hexdigest()
    if db.scalar(select(SourceRevision.id).where(SourceRevision.source_record_id == existing_source.id, SourceRevision.fingerprint == fingerprint)) is None:
        db.add(SourceRevision(source_record_id=existing_source.id, fingerprint=fingerprint, raw_json=new_json))
    existing_source.source_url = row.get("source_url")
    existing_source.retrieved_at = now()
    existing_source.raw_json = json.dumps(row.get("raw", row), ensure_ascii=False)
    if job is not None:
        if db.get(PaperBatch, (job.id, paper.id)) is None:
            db.add(PaperBatch(job_id=job.id, paper_id=paper.id, is_new=is_new))
    return paper


def log(db: Session, job: Job, stage: str, level: str, message: str) -> None:
    job.stage = stage
    job.updated_at = now()
    db.add(JobEvent(job_id=job.id, stage=stage, level=level, message=message[:2000]))
    db.commit()


def run_openalex_job(db: Session, job: Job) -> None:
    from scripts.fetch_openalex_batch import fetch_batch

    source = db.scalar(select(Source).where(Source.name == "openalex"))
    if not source or not source.enabled or job.venue not in OPENALEX_SOURCES:
        job.status = "failed"
        job.active_key = None
        job.error = f"OpenAlex is unavailable for {job.venue}"
        job.finished_at = now()
        log(db, job, "failed", "error", job.error)
        return
    from .pipeline import has_snapshot, process_snapshot, safe_error, save_snapshot
    if has_snapshot(db, job):
        cached = db.scalar(select(JobEvent.id).where(JobEvent.job_id == job.id,
                            JobEvent.message.like("OpenAlex unavailable%"))) is not None
        warning = "Saved batch came from cache; create a new refresh to fetch current upstream data." if cached else None
        process_snapshot(db, job, warning=warning)
        return
    job.status = "running"
    job.started_at = job.started_at or now()
    path = configured_path("BATCH_DIR", "data/raw") / f"{job.venue.lower()}_{job.year}.jsonl"
    cache_used = False
    log(db, job, "fetch", "info", f"Fetching {job.venue} {job.year} from OpenAlex")
    try:
        try:
            manifest = fetch_batch(job.venue, job.year, path, retries=source.max_retries, page_size=min(source.page_size, 100))
            log(db, job, "fetch", "info", f"Downloaded {manifest['count']} OpenAlex records")
        except Exception as exc:
            manifest_path = path.with_suffix(".manifest.json")
            if not path.exists() or not manifest_path.exists():
                raise
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            cache_used = True
            log(db, job, "fetch", "warning", f"OpenAlex unavailable ({type(exc).__name__}); using cached batch")
        if (manifest.get("venue"), manifest.get("year"), manifest.get("source"), manifest.get("source_id")) != (
            job.venue, job.year, "openalex", OPENALEX_SOURCES[job.venue]
        ):
            raise ValueError("OpenAlex batch does not match the requested venue/year")
        body = path.read_bytes()
        if not manifest.get("sha256") or hashlib.sha256(body).hexdigest() != manifest["sha256"]:
            raise ValueError("OpenAlex batch checksum mismatch; download a fresh batch")
        if not isinstance(manifest.get("count"), int) or manifest["count"] <= 0:
            raise ValueError("OpenAlex batch has no valid record count")
        rows = []
        for line in body.decode("utf-8").splitlines():
            work = json.loads(line)
            actual_source = ((work.get("primary_location") or {}).get("source") or {}).get("id")
            if work.get("publication_year") != job.year or actual_source != "https://openalex.org/" + OPENALEX_SOURCES[job.venue]:
                raise ValueError("Work venue/year does not match batch")
            # Preserve malformed payloads in the snapshot so they can be diagnosed.
            rows.append({"source_id": work["id"], "raw": work, "openalex_work": True, "_cached": cache_used})
        if len(rows) != manifest["count"]:
            raise ValueError("Batch length differs from manifest count")
        save_snapshot(db, job, rows, "openalex")
        warning = "Upstream unavailable; saved cached records were imported. Create a new refresh to fetch current data." if cache_used else None
        process_snapshot(db, job, warning=warning)
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.active_key = None
        job.error = safe_error(exc)
        job.finished_at = now()
        log(db, job, "failed", "error", job.error)


def run_job(db: Session, job: Job, http: requests.Session | None = None) -> None:
    if job.kind == "sample":
        from .datasets import import_sample
        from .additional_samples import DATASETS, import_additional
        try:
            if job.dataset_id in DATASETS:
                import_additional(db, job.dataset_id, job=job)
            else:
                import_sample(db, job.dataset_id, job=job)
        except Exception as exc:
            job.status = "failed"
            job.active_key = None
            job.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            job.finished_at = now()
            log(db, job, "failed", "error", job.error)
        return
    from .pipeline import has_snapshot, process_snapshot, safe_error, save_snapshot
    http = http or requests.Session()
    try:
        if has_snapshot(db, job):
            from .models import JobRecord
            actual = db.scalar(select(JobRecord.source).where(JobRecord.job_id == job.id).limit(1))
            if actual == 'openalex':
                run_openalex_job(db, job)
            else:
                process_snapshot(db, job, http)
            return
        if job.kind == 'file' and (job.dataset_id or '').startswith('upload:'):
            from .batch_import import process_upload
            process_upload(db, job)
            return
        if job.source == 'cvf':
            from .cvf_job import run_cvf_job
            run_cvf_job(db, job, http)
            return
        if job.source == 'auto' and job.venue in ('CVPR', 'ICCV'):
            configured = db.scalar(select(Source).where(Source.name == 'cvf', Source.enabled.is_(True)))
            if configured:
                from .cvf_job import run_cvf_job
                job.source = 'cvf'
                db.commit()
                run_cvf_job(db, job, http)
                from .models import CvfRecord
                if job.status == 'failed' and not db.scalar(select(CvfRecord.id).where(CvfRecord.job_id == job.id).limit(1)):
                    oa = db.scalar(select(Source).where(Source.name == 'openalex', Source.enabled.is_(True)))
                    if oa:
                        job.source = 'openalex'
                        job.active_key = f'{job.venue}:{job.year}'
                        db.commit()
                        run_openalex_job(db, job)
                return
        if job.source == 'ecva' or (job.source == 'auto' and job.venue == 'ECCV'):
            from .ecva import run_ecva_job
            run_ecva_job(db, job, http)
            return
        if job.source == 'openalex':
            run_openalex_job(db, job)
            return
        source = db.scalar(select(Source).where(Source.name == 'dblp'))
        if not source or not source.enabled:
            if job.source == 'auto' and job.venue in OPENALEX_SOURCES:
                run_openalex_job(db, job)
                return
            raise ValueError('DBLP source is disabled')
        job.status = 'running'
        job.started_at = job.started_at or now()
        log(db, job, 'fetch', 'info', f'Fetching {job.venue} {job.year} from DBLP')
        try:
            rows = fetch_dblp(job.venue, job.year, http, source.max_retries)
            if not rows:
                raise ValueError('DBLP returned no conference papers')
        except Exception as exc:
            oa = db.scalar(select(Source).where(Source.name == 'openalex', Source.enabled.is_(True)))
            if job.source == 'auto' and oa and job.venue in OPENALEX_SOURCES:
                log(db, job, 'fetch', 'warning', 'DBLP unavailable; trying OpenAlex')
                run_openalex_job(db, job)
                return
            raise
        save_snapshot(db, job, rows, 'dblp')
        process_snapshot(db, job, http)
    except Exception as exc:
        db.rollback()
        job.status = 'failed'
        job.active_key = None
        job.error = safe_error(exc)
        job.finished_at = now()
        log(db, job, 'failed', 'error', job.error)
