"""离线演示 B 候选抽取：从仓库根目录 python -m scripts.demo_b_candidates。"""

import argparse
from collections import Counter
from pathlib import Path

from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Show B extraction candidates")
    parser.add_argument("--vocabulary", type=Path, help="Optional vocabulary JSON")
    args = parser.parse_args()
    vocabulary = load_vocabulary(args.vocabulary)
    papers = load_openalex_sample(root / "examples" / "week1_baseline.json")
    results = [extract_candidates(paper, vocabulary) for paper in papers]
    print("Vocabulary:", vocabulary["version"])
    print(f"Papers: {len(results)}")
    print(
        "Entity candidates (summed per paper):", sum(len(r.entities) for r in results)
    )
    print(
        "Relation candidates (summed per paper):",
        sum(len(r.relations) for r in results),
    )
    print(
        "Entity types:",
        dict(
            sorted(Counter(c.entity.kind for r in results for c in r.entities).items())
        ),
    )
    print(
        "Relation types:",
        dict(sorted(Counter(c.kind for r in results for c in r.relations).items())),
    )
    print("Diagnostics:", sum(len(r.diagnostics) for r in results))
    print("All candidates are pending; counts are not accuracy measurements.")
    print("\nFirst paper:", papers[0].title)
    for candidate in results[0].entities:
        if candidate.entity.kind in {"topic", "method", "task", "dataset"}:
            print(
                f"  {candidate.entity.kind}: {candidate.entity.name} [{candidate.status}]"
            )
            for proof in candidate.evidence[:2]:
                print(f"    {proof.field}[{proof.start}:{proof.end}] = {proof.quote!r}")
    if results[0].diagnostics:
        print("First-paper diagnostics:", results[0].diagnostics)


if __name__ == "__main__":
    main()
