"""一次导出真实样本及可用审核决定；不创建任何人工确认。"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.knowledge_builder.export import build_exports
from src.knowledge_builder.export_io import write_exports
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.paths import default_review_directory, workspace_data
from src.knowledge_builder.review_storage import load_review_sessions


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Export versioned knowledge and candidates"
    )
    parser.add_argument(
        "--manifest", type=Path, default=root / "examples" / "week1_baseline.json"
    )
    parser.add_argument("--reviews-dir", type=Path)
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
        review_directory = (
            args.reviews_dir
            if args.reviews_dir is not None
            else default_review_directory(root)
        )
        sessions = load_review_sessions(review_directory, papers, results)
        bundle = build_exports(papers, results, sessions)
        output = args.output or workspace_data(root) / "exports" / datetime.now(
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
