"""Prepare a fixed 20+80 paper reading corpus from A and cached external sources."""

import argparse
import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from scripts.knowledge_builder.experiment_sources import ROOT, git_pool, write
from src.knowledge_builder.enrichment_sources import SourceClient, SourceUnavailable
from src.knowledge_builder.extraction import fingerprint, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.source_corpus import FORMAT, load_corpus
from src.knowledge_builder.source_enrichment import analyze_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-limit", type=int, default=80)
    parser.add_argument("--pool-ref", default="origin/data-pipeline")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge_builder/source_corpus/corpus.json")
    args = parser.parse_args()
    if not 0 <= args.pool_limit <= 200:
        parser.error("pool-limit must be between 0 and 200")
    load_dotenv(ROOT / ".env", override=False)
    baseline = load_openalex_sample(ROOT / "examples/week1_baseline.json")
    pool, provenance = git_pool(args.pool_ref, "examples/cvpr_2024_full/cvpr_2024.jsonl",
                                {p.openalex_id for p in baseline}, args.pool_limit)
    vocabulary = load_vocabulary()
    client = SourceClient(ROOT / "data/knowledge_builder/source_cache", offline=args.offline)
    entries, summaries = [], []
    for index, paper in enumerate(baseline + pool, 1):
        records, errors = [], []
        for source, fetch in (("openalex", client.openalex), ("paperswithcode", client.papers_with_code)):
            try:
                records.append(fetch(paper))
            except SourceUnavailable as exc:
                errors.append(dict(source=source, error=str(exc)))
        analysis = analyze_sources(paper, vocabulary, records, fallback=True)
        entries.append(dict(paper=asdict(paper), records=records, source_errors=errors))
        summaries.append(dict(paper_id=paper.openalex_id, title=paper.title,
            source_errors=errors, sources=[r["source"] for r in records],
            classifications=len(analysis["source_classifications"]),
            before_entities=len(analysis["baseline"]["entities"]),
            after_entities=len(analysis["enriched"]["entities"]),
            after_relations=len(analysis["enriched"]["relations"]),
            added_entities=analysis["added_entities"]))
        print(f"{index}/{len(baseline + pool)} {paper.openalex_id.rsplit('/', 1)[-1]} "
              f"sources={len(records)} added={len(analysis['added_entities'])} errors={len(errors)}", flush=True)
    payload = dict(format_version=FORMAT, provenance=provenance, papers=entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(dict(payload=payload, sha256=fingerprint(payload)), file, ensure_ascii=False)
        load_corpus(temporary, baseline, vocabulary)
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    summary = dict(papers=len(entries), source_coverage=dict(Counter(r["source"] for e in entries for r in e["records"])),
        added_by_kind=dict(Counter(c["kind"] for s in summaries for c in s["added_entities"])),
        before_entities=sum(s["before_entities"] for s in summaries),
        after_entities=sum(s["after_entities"] for s in summaries),
        after_relations=sum(s["after_relations"] for s in summaries),
        classifications=sum(s["classifications"] for s in summaries),
        network_requests=client.requests, cache_hits=client.cache_hits, details=summaries)
    write(args.output.with_name("summary.json"), summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "details"}), flush=True)


if __name__ == "__main__":
    main()
