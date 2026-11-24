"""生成自动质量报告、开发评估清单、空白答案模板和五篇验证材料。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.knowledge_builder.assessment import (
    build_evaluation_manifest,
    build_quality_report,
)
from src.knowledge_builder.assessment_io import (
    demo_markdown,
    quality_markdown,
    write_assessment,
)
from src.knowledge_builder.evaluation import (
    build_annotation_template,
    score_annotations,
)
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.paths import default_review_directory, workspace_data
from src.knowledge_builder.review_storage import load_review_sessions


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Prepare validation materials without inventing human answers"
    )
    parser.add_argument(
        "--manifest", type=Path, default=root / "examples/week1_baseline.json"
    )
    parser.add_argument("--vocabulary", type=Path)
    parser.add_argument("--reviews-dir", type=Path)
    parser.add_argument(
        "--annotations",
        type=Path,
        help="Optional independently completed annotation JSON",
    )
    parser.add_argument("--output", type=Path, help="New output directory")
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
        quality = build_quality_report(papers, results, sessions)
        annotations = (
            json.loads(args.annotations.read_text(encoding="utf-8"))
            if args.annotations is not None
            else build_annotation_template(papers)
        )
        scoring = score_annotations(annotations, papers, results)
        source_path = str(args.manifest.resolve())
        if args.manifest.resolve().is_relative_to(root):
            source_path = args.manifest.resolve().relative_to(root).as_posix()
        manifest = build_evaluation_manifest(papers, source_manifest=source_path)
        documents = {
            "quality.json": quality,
            "quality.md": quality_markdown(quality),
            "evaluation_manifest.json": manifest,
            "annotations.json": annotations,
            "evaluation.json": scoring,
            "demo_packet.md": demo_markdown(
                papers, results, vocabulary_path=args.vocabulary
            ),
        }
        output = args.output or workspace_data(root) / "validation" / datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S%fZ")
        destination = write_assessment(output, documents)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Preparation failed: {exc}\n")
    print("Output:", destination)
    print("Vocabulary:", vocabulary["version"])
    print(
        "Papers:",
        quality["papers"],
        "Entity candidates:",
        quality["entity_candidates"],
        "Relation candidates:",
        quality["relation_candidates"],
    )
    print("Papers with text categories:", quality["papers_with_category"])
    print("Diagnostics:", quality["diagnostic_count"])
    print(
        "Annotation status:",
        scoring["status"],
        f"({scoring['completed_cases']}/{scoring['cases']})",
    )
    print(
        "Development papers:",
        len(manifest["splits"]["development"]),
        "Unseen test papers:",
        len(manifest["splits"]["test"]),
    )
    print(
        "No human confirmation, gold answer or independent-test accuracy was created."
    )


if __name__ == "__main__":
    main()
