"""Compare frozen B rules with source-backed overlays; never writes live knowledge.

Run from the repository root with the existing insight-prototype environment.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

from src.knowledge_builder.enrichment_sources import SourceClient, SourceUnavailable
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.input_adapter import adapt_openalex_work, load_openalex_sample
from src.knowledge_builder.source_enrichment import analyze_sources

ROOT = Path(__file__).resolve().parents[2]


def git_pool(ref, path, exclude, limit):
    """Read A's immutable Git objects without switching or copying its whole branch."""
    relative = PurePosixPath(path)
    if (not re.fullmatch(r"[\w/.-]+", ref) or relative.is_absolute() or ".." in relative.parts
        or not path.startswith("examples/") or not path.endswith(".jsonl")):
        raise ValueError("Expected a Git ref and an examples/*.jsonl path")

    def read(name):
        return subprocess.run(["git", "show", f"{ref}:{name}"], cwd=ROOT,
                              check=True, capture_output=True).stdout

    body = read(path)
    manifest = json.loads(read(str(relative.with_suffix(".manifest.json"))))
    if (manifest.get("source") != "openalex" or manifest.get("filename") != relative.name
        or hashlib.sha256(body).hexdigest() != manifest.get("sha256")):
        raise ValueError("A pool metadata or checksum mismatch")
    rows = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != manifest.get("count"):
        raise ValueError("A pool count differs from manifest")
    papers, skipped = [], Counter()
    seen = set()
    for work in rows:
        identifier = work.get("id")
        if not isinstance(identifier, str) or identifier in seen:
            raise ValueError("Missing or duplicate A pool ID")
        seen.add(identifier)
        if identifier in exclude:
            skipped["already_in_baseline"] += 1
            continue
        if work.get("type") not in ("conference-paper", "article", "proceedings-article", "preprint"):
            skipped["non_research_record_type"] += 1
            continue
        source = ((work.get("primary_location") or {}).get("source") or {}).get("id")
        if source != "https://openalex.org/" + manifest["source_id"]:
            raise ValueError("A pool source differs from manifest")
        paper = adapt_openalex_work(work, venue=manifest["venue"], dataset_id="source-probe-" + manifest["sha256"][:12])
        if paper.year != manifest["year"]:
            raise ValueError("A pool year differs from manifest")
        papers.append(paper)
    papers.sort(key=lambda p: fingerprint(p.openalex_id))
    commit = subprocess.run(["git", "rev-parse", ref], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    return papers[:limit], dict(ref=ref, commit=commit, path=path, sha256=manifest["sha256"],
                               source_records=len(rows), eligible_records=len(papers), skipped=dict(skipped),
                               sample_policy="first N sorted by SHA256 of canonical paper ID")


def summarize(results):
    return dict(papers=len(results), entities=dict(Counter(c.entity.kind for r in results for c in r.entities)),
                relations=sum(len(r.relations) for r in results),
                missing_abstract=sum("Missing abstract" in r.diagnostics for r in results))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-ref", default="origin/data-pipeline")
    parser.add_argument("--pool-path", default="examples/cvpr_2024_full/cvpr_2024.jsonl")
    parser.add_argument("--pool-limit", type=int, default=100)
    parser.add_argument("--sources-per-group", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge_builder/source_experiment/latest")
    parser.add_argument("--cache", type=Path, default=ROOT / "data/knowledge_builder/source_cache")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--skip-pwc", action="store_true")
    args = parser.parse_args()
    if args.pool_limit < 0 or not 0 <= args.sources_per_group <= 50:
        parser.error("pool-limit must be nonnegative; sources-per-group must be between 0 and 50")
    if args.offline and args.refresh:
        parser.error("--offline and --refresh cannot be combined")
    # Optional API key is consumed only for requests and never stored in cache.
    load_dotenv(ROOT / ".env", override=False)
    baseline = load_openalex_sample(ROOT / "examples/week1_baseline.json")
    pool, provenance = git_pool(args.pool_ref, args.pool_path, {p.openalex_id for p in baseline}, args.pool_limit)
    vocabulary = load_vocabulary()
    client = SourceClient(args.cache, refresh=args.refresh, offline=args.offline)
    report = dict(format_version="source-experiment-summary/1", vocabulary_version=vocabulary["version"],
                  vocabulary_fingerprint=fingerprint(vocabulary), pool=provenance, groups={}, experiments=[],
                  notice="Experimental reports only. No UI, review store, canonical vocabulary or C writes.")
    started = time.monotonic()
    for group, papers in (("baseline", baseline), ("a_new_sample", pool)):
        originals = []
        for index, paper in enumerate(papers, 1):
            originals.append(extract_candidates(paper, vocabulary))
            if index % 100 == 0:
                print(f"{group}: baseline extraction {index}/{len(papers)}", flush=True)
        report["groups"][group] = summarize(originals)
        print(f"{group}: local baseline complete ({len(papers)} records)", flush=True)
        for paper in papers[:args.sources_per_group]:
            records, errors = [], []
            for source, fetch in (("openalex", client.openalex), ("paperswithcode", client.papers_with_code)):
                if source == "paperswithcode" and args.skip_pwc:
                    continue
                try:
                    records.append(fetch(paper))
                except SourceUnavailable as exc:
                    errors.append(dict(source=source, error=str(exc)))
            analysis = analyze_sources(paper, vocabulary, records)
            identifier = fingerprint(paper.openalex_id)
            write(args.output / "papers" / (identifier + ".json"), analysis)
            before, after = analysis["baseline"], analysis["enriched"]
            report["experiments"].append(dict(group=group, paper_id=paper.openalex_id, title=paper.title,
                sources=[r["source"] for r in records], source_errors=errors,
                source_classifications=len(analysis["source_classifications"]),
                baseline_entities=len(before["entities"]), enriched_entities=len(after["entities"]),
                added_entities=analysis["added_entities"],
                baseline_relations=len(before["relations"]), enriched_relations=len(after["relations"]),
                ignored_reasons=dict(Counter(s["reason"] for s in analysis["ignored_signals"])),
                artifact="papers/" + identifier + ".json"))
            print(f"{group}: source probe {len(report['experiments'])} {paper.openalex_id.rsplit('/', 1)[-1]} "
                  f"sources={len(records)} added={len(analysis['added_entities'])} errors={len(errors)}", flush=True)
            write(args.output / "summary.json", report)
    report.update(elapsed_seconds=round(time.monotonic() - started, 2),
                  network_requests=client.requests, cache_hits=client.cache_hits)
    write(args.output / "summary.json", report)
    print(json.dumps({"summary":str(args.output / "summary.json"), "groups":report["groups"],
                      "probed":len(report["experiments"]), "network_requests":client.requests,
                      "cache_hits":client.cache_hits}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
