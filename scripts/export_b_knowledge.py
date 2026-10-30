"""一次导出真实样本及可用审核决定；不创建任何人工确认。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.knowledge_builder.export import build_exports
from src.knowledge_builder.export_io import write_exports
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.review_storage import load_review


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Export versioned B knowledge and candidates"
    )
    parser.add_argument(
        "--manifest", type=Path, default=root / "examples" / "week1_baseline.json"
    )
    parser.add_argument("--reviews-dir", type=Path, default=root / "data" / "b_reviews")
    parser.add_argument(
        "--vocabulary",
        type=Path,
        help="Optional vocabulary JSON, including an older version",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="New output directory; existing directories are not overwritten",
    )
    args = parser.parse_args()
    try:
        papers = load_openalex_sample(args.manifest)
        vocabulary = load_vocabulary(args.vocabulary)
        results = [extract_candidates(paper, vocabulary) for paper in papers]
        inputs = {
            paper.openalex_id: (paper, result) for paper, result in zip(papers, results)
        }
        sessions = {}
        if args.reviews_dir.exists() and not args.reviews_dir.is_dir():
            raise ValueError("Reviews path must be a directory")
        for path in sorted(args.reviews_dir.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or not isinstance(
                document.get("payload"), dict
            ):
                raise ValueError(f"Invalid review archive: {path}")
            paper_id = document["payload"].get("paper_id")
            if not isinstance(paper_id, str) or paper_id not in inputs:
                raise ValueError(
                    f"Archive refers to a paper outside this sample: {path}"
                )
            if paper_id in sessions:
                raise ValueError(f"Multiple review archives for one paper: {path}")
            paper, result = inputs[paper_id]
            sessions[paper_id] = load_review(path, paper, result).session
        bundle = build_exports(papers, results, sessions)
        output = args.output or root / "data" / "b_exports" / datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S%fZ")
        destination = write_exports(output, bundle, papers)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Export failed: {exc}\n")
    print("Output:", destination)
    print("Processed papers:", len(papers))
    print("Loaded review archives:", len(sessions))
    for status, document in bundle.items():
        print(status + ":", document["counts"])
    print("Contract: draft. Counts are not accuracy measurements.")


if __name__ == "__main__":
    main()
