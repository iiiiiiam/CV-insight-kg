"""Validate frozen evidence and summarize changes on existing/unseen papers."""

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.knowledge_builder.experiment_sources import write
from src.knowledge_builder.extraction import fingerprint, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.source_enrichment import analyze_sources

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/knowledge_builder/source_corpus/corpus.json")
    parser.add_argument("--before", type=Path, default=ROOT / "data/knowledge_builder/source_corpus/before_text_rules.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge_builder/source_corpus/text_rule_check.json")
    args = parser.parse_args()
    document = json.loads(args.corpus.read_text(encoding="utf-8"))
    payload = document["payload"]
    if document["sha256"] != fingerprint(payload):
        raise ValueError("Corpus checksum mismatch")
    before = {r["paper_id"]: r["result"] for r in json.loads(args.before.read_text(encoding="utf-8"))["papers"]}
    vocabulary = load_vocabulary()
    baseline = {p.openalex_id: p for p in load_openalex_sample(ROOT / "examples/week1_baseline.json")}
    seen, groups, details = set(), {}, []
    for entry in payload["papers"]:
        paper = PaperInput(**entry["paper"])
        if paper.openalex_id in seen:
            raise ValueError("Duplicate corpus ID")
        seen.add(paper.openalex_id)
        if paper.openalex_id in baseline and paper != baseline[paper.openalex_id]:
            raise ValueError("Original paper changed")
        analysis = analyze_sources(paper, vocabulary, entry["records"], fallback=True)
        old, new = analysis["baseline"], analysis["enriched"]
        for kind in ("entities", "relations"):
            assert {i["candidate_id"] for i in old[kind]} <= {i["candidate_id"] for i in new[kind]}
        group = "existing" if paper.openalex_id in before else "new"
        counts = groups.setdefault(group, Counter())
        counts.update(papers=1, entities=len(new["entities"]), relations=len(new["relations"]),
                      original_entities=len(old["entities"]), original_relations=len(old["relations"]),
                      papers_with_text_signals=bool(analysis["text_signals"]))
        counts.update({"kind_" + kind: count for kind, count in Counter(c["entity"]["kind"] for c in new["entities"]).items()})
        previous = before.get(paper.openalex_id, old)
        previous_ids = {i["candidate_id"] for i in previous["entities"]}
        current_ids = {i["candidate_id"] for i in new["entities"]}
        additions = [i["entity"] for i in new["entities"] if i["candidate_id"] not in previous_ids]
        removals = [i["entity"] for i in previous["entities"] if i["candidate_id"] not in current_ids]
        counts.update(added=len(additions), removed=len(removals))
        details.append(dict(paper_id=paper.openalex_id, title=paper.title, group=group,
            text_signals=analysis["text_signals"], added=additions, removed=removals,
            source_errors=entry["source_errors"], ignored_reasons=dict(Counter(s["reason"] for s in analysis["ignored_signals"]))))
    if not set(baseline) <= seen or not set(before) <= seen:
        raise ValueError("Expected original/existing papers are missing")
    paths = ("source_enrichment.py", "text_signals.py", "curated_vocabulary.py", "vocabulary_cv.json", "extraction.py")
    rules = {name: fingerprint((ROOT / "src/knowledge_builder" / name).read_text(encoding="utf-8")) for name in paths}
    report = dict(groups={k: dict(v) for k, v in groups.items()}, rule_fingerprints=rules, details=details)
    write(args.output, report)
    print(json.dumps(dict(groups=report["groups"], output=str(args.output))), flush=True)


if __name__ == "__main__":
    main()
