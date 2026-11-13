"""Frozen per-input source supplements shared by batch reading and export.

HTTP is confined to prepare(); records() never performs network requests.
Dataset labels are excluded from the cache key, actual paper changes are not.
"""
import json
import os
import tempfile
import threading
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .enrichment_sources import SourceClient, SourceUnavailable
from .extraction import fingerprint, load_vocabulary
from .source_corpus import load_reading_corpus
from .source_enrichment import analyze_sources

FORMAT = "knowledge-batch-sources/1"
_prepare_lock = threading.Lock()  # The gateway runs one worker; writes also use os.replace.


class BatchSourcesInvalid(ValueError):
    pass


def input_key(paper):
    value = asdict(paper)
    value.pop("dataset_id")
    return fingerprint(value)


class BatchSources:
    def __init__(self, registry_path, *, corpus_path=None, cache_path=None, offline=False):
        self.directory = Path(registry_path).parent / "sources"
        self.corpus_path = Path(corpus_path) if corpus_path else None
        self.cache_path = Path(cache_path) if cache_path else Path(__file__).resolve().parents[2] / "data/knowledge_builder/source_cache"
        self.offline = offline

    def _seeds(self, vocabulary):
        if not self.corpus_path:
            return {}
        try:
            papers, records, _ = load_reading_corpus(self.corpus_path, [], vocabulary)
            return {input_key(p): records[p.openalex_id] for p in papers}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise BatchSourcesInvalid("原有来源语料无法校验，未使用无效缓存") from exc

    def _read(self, paper, vocabulary):
        path = self.directory / (input_key(paper) + ".json")
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            value = wrapper["payload"]
            if (wrapper["sha256"] != fingerprint(value) or value["format_version"] != FORMAT
                    or value["input_key"] != input_key(paper) or value["paper_id"] != paper.openalex_id
                    or not isinstance(value["errors"], list)):
                raise ValueError("Source snapshot identity/checksum mismatch")
            analyze_sources(paper, vocabulary, value["records"], fallback=True)
            return value
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BatchSourcesInvalid("批次来源快照无法校验，原文件保留") from exc

    def records(self, papers, vocabulary=None):
        vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
        seeds = self._seeds(vocabulary)
        result = {}
        for paper in papers:
            stored = self._read(paper, vocabulary)
            records = stored["records"] if stored else seeds.get(input_key(paper), [])
            analyze_sources(paper, vocabulary, records, fallback=True)
            result[paper.openalex_id] = deepcopy(records)
        return result

    def summary(self, papers, vocabulary=None):
        vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
        seeds = self._seeds(vocabulary)
        counts = dict(total=len(papers), completed=0, pending=0, with_sources=0, partial=0)
        for paper in papers:
            stored = self._read(paper, vocabulary)
            records = stored["records"] if stored else seeds.get(input_key(paper), [])
            sources = {r["source"] for r in records}
            if stored is not None or sources == {"openalex", "paperswithcode"}:
                counts["completed"] += 1
                if len(sources) < 2:
                    counts["partial"] += 1
            else:
                counts["pending"] += 1
            if records:
                counts["with_sources"] += 1
        return counts

    def _write(self, paper, records, errors):
        value = dict(format_version=FORMAT, input_key=input_key(paper), paper_id=paper.openalex_id,
                     records=records, errors=errors)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as file:
                temporary = Path(file.name)
                json.dump(dict(payload=value, sha256=fingerprint(value)), file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.directory / (input_key(paper) + ".json"))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def prepare(self, papers, vocabulary=None, *, client=None):
        """Fetch missing sources once per job. Retry never discards valid sources."""
        if client is None:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
        client = client or SourceClient(self.cache_path, offline=self.offline)
        with _prepare_lock:
            seeds = self._seeds(vocabulary)
            for paper in papers:
                stored = self._read(paper, vocabulary)
                previous = stored["records"] if stored else seeds.get(input_key(paper), [])
                records = {r["source"]: deepcopy(r) for r in previous}
                errors = []
                for source, fetch in (("openalex", client.openalex), ("paperswithcode", client.papers_with_code)):
                    if source in records:
                        continue
                    try:
                        record = fetch(paper)
                        if record["source"] != source:
                            raise ValueError("Unexpected source identity")
                        analyze_sources(paper, vocabulary, [record], fallback=True)
                        records[source] = record
                    except (SourceUnavailable, ValueError, KeyError, TypeError, OSError) as exc:
                        # Do not expose request exception URLs or API credentials.
                        errors.append(dict(source=source, reason="来源暂不可用或未通过匹配校验",
                                           error_type=type(exc).__name__))
                self._write(paper, list(records.values()), errors)
        return self.summary(papers, vocabulary)
