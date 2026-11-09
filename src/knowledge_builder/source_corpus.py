"""Validated, opt-in corpus for public knowledge reading; no network on requests."""

import json
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from .extraction import extract_candidates, fingerprint
from .models import PaperInput
from .source_enrichment import analyze_sources

FORMAT = "knowledge-source-corpus/1"


def load_corpus(path, baseline, vocabulary):
    papers, records, _ = load_reading_corpus(path, baseline, vocabulary)
    return papers, records


def load_reading_corpus(path, baseline, vocabulary):
    path = Path(path).resolve()
    stat = path.stat()
    return deepcopy(_load_corpus(str(path), stat.st_mtime_ns, stat.st_size,
        json.dumps([asdict(p) for p in baseline], sort_keys=True), json.dumps(vocabulary, sort_keys=True)))


@lru_cache(maxsize=2)
def _load_corpus(path, modified, size, baseline_json, vocabulary_json):
    baseline = [PaperInput(**p) for p in json.loads(baseline_json)]
    vocabulary = json.loads(vocabulary_json)
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = document["payload"]
    if document["sha256"] != fingerprint(payload) or payload["format_version"] != FORMAT:
        raise ValueError("Source corpus checksum or version mismatch")
    papers, records, entries = [], {}, payload["papers"]
    for entry in entries:
        paper = PaperInput(**entry["paper"])
        if paper.openalex_id in records:
            raise ValueError("Duplicate source corpus paper")
        # Validate both extraction evidence and source-to-paper identity.
        analyze_sources(paper, vocabulary, entry["records"])
        papers.append(paper)
        records[paper.openalex_id] = entry["records"]
    indexed = {p.openalex_id: asdict(p) for p in papers}
    if not papers or any(indexed.get(p.openalex_id) != asdict(p) for p in baseline):
        raise ValueError("Source corpus must preserve the complete original input")
    results = {p.openalex_id: extract_candidates(p, vocabulary) for p in papers}
    return papers, records, results
