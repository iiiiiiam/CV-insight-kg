"""Import the shared supplemental samples with their original provenance."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from examples.additional_papers_60.load_for_b import load_papers
from .datasets import ImportConflict, sample_directory
from .ingest import log, openalex_work_row, upsert_paper
from .models import Job, PaperSource, Source, now

DATASETS = {
    'additional-cvpr2024-detection-20-v1': ('CVPR', 2024),
    'additional-iccv2023-detection-20-v1': ('ICCV', 2023),
    'additional-eccv2024-detection-20-v1': ('ECCV', 2024),
}


def sample_dir() -> Path:
    return sample_directory() / 'additional_papers_60'


def list_additional_datasets() -> list[dict]:
    # Validate all files before offering a dataset for import.
    papers = load_papers(sample_dir())
    output = []
    for dataset_id, (venue, year) in DATASETS.items():
        count = sum(p.dataset_id == dataset_id and p.venue == venue and p.year == year for p in papers)
        if count != 20:
            raise ValueError('Additional sample group does not contain exactly 20 papers')
        output.append({'dataset_id': dataset_id, 'name': f'{venue} {year} 新增论文样本',
                       'venue': venue, 'year': year, 'source': 'ecva+openalex' if venue == 'ECCV' else 'openalex',
                       'expected_count': count})
    return output


def import_additional(db: Session, dataset_id: str, job: Job | None = None) -> Job:
    if dataset_id not in DATASETS:
        raise ValueError('Unknown sample dataset')
    venue, year = DATASETS[dataset_id]
    # The loader checks every file's checksum, original sample exclusion, IDs and scope.
    list_additional_datasets()
    papers = [p for p in load_papers(sample_dir()) if p.dataset_id == dataset_id]
    raw_path = sample_dir() / 'raw' / f'{venue.lower()}_{year}.openalex.jsonl'
    raw = {w['id']: w for w in (json.loads(line) for line in raw_path.read_text(encoding='utf-8').splitlines() if line)}
    evidence = {}
    if venue == 'ECCV':
        evidence = {r['openalex_id']: r for r in (json.loads(line) for line in
                    (sample_dir() / 'raw/eccv_2024.ecva.jsonl').read_text(encoding='utf-8').splitlines() if line)}
    if set(raw) != {p.openalex_id for p in papers} or (venue == 'ECCV' and set(evidence) != set(raw)):
        raise ValueError('Supplemental inputs and source records differ')
    for source_name in ('openalex', 'ecva') if venue == 'ECCV' else ('openalex',):
        source = db.scalar(select(Source).where(Source.name == source_name))
        if not source or not source.enabled:
            raise ImportConflict(f'{source_name} source is disabled')
    active = select(Job).where(Job.venue == venue, Job.year == year, Job.status.in_(['queued', 'running']))
    if job is not None:
        active = active.where(Job.id != job.id)
    if db.scalar(active):
        raise ImportConflict('Another import or refresh is active for this venue/year')
    if job is None:
        job = Job(venue=venue, year=year, source='ecva' if venue == 'ECCV' else 'openalex',
                  kind='sample', dataset_id=dataset_id)
        db.add(job)
    elif (job.dataset_id, job.venue, job.year) != (dataset_id, venue, year):
        raise ValueError('Existing job does not match the dataset')
    job.status='running'; job.stage='import'; job.active_key=f'{venue}:{year}'
    job.attempted=job.succeeded=job.failed=0; job.error=None; job.started_at=now(); job.finished_at=None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ImportConflict('Another import or refresh is active for this venue/year') from exc
    log(db, job, 'import', 'info', f'Importing checked sample {dataset_id}; {len(papers)} papers')
    for original in papers:
        job.attempted += 1
        try:
            with db.begin_nested():
                work = raw[original.openalex_id]
                row = openalex_work_row(work, venue, year)
                paper = upsert_paper(db, row, 'openalex', job=job)
                if venue == 'ECCV':
                    # OpenAlex supplies the identity; ECVA supplies this abstract and names.
                    item = evidence[original.openalex_id]
                    official = item['official_record']
                    previous = db.scalar(select(PaperSource).where(
                        PaperSource.source == 'ecva', PaperSource.source_id == official['source_id']))
                    if previous is not None and previous.paper_id != paper.id:
                        raise ValueError('OpenAlex and ECVA records point to different papers; review the source mapping')
                    row = {'source_id': official['source_id'], 'title': original.title,
                           'year': year, 'venue': venue, 'doi': official.get('doi'),
                           'authors': [a['author']['display_name'] for a in original.authorships],
                           'source_url': original.source_url,
                           'raw': {'paper_input': asdict(original), 'official_evidence': item}}
                    upsert_paper(db, row, 'ecva', paper=paper, job=job)
                    paper.abstract = original.abstract
                db.flush()
            job.succeeded += 1
            db.commit()
        except Exception as exc:
            job.failed += 1
            log(db, job, 'import', 'error', f'{original.openalex_id}: {type(exc).__name__}: {str(exc)[:200]}')
    job.status = 'partial' if job.failed else 'succeeded'
    job.active_key=None; job.finished_at=now()
    log(db, job, 'done', 'info', f'Completed: {job.succeeded} succeeded, {job.failed} failed')
    return job
