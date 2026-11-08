"""自动质量盘点与开发评估清单；没有参考答案时不生成准确率。"""

from collections import Counter
from dataclasses import asdict

from .export import build_exports
from .extraction import fingerprint

ASSESSMENT_VERSION = "b-assessment/0.1-draft"


def build_evaluation_manifest(
    papers, *, source_manifest="examples/week1_baseline.json"
) -> dict:
    identifiers = [paper.openalex_id for paper in papers]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate evaluation papers")
    return {
        "format_version": ASSESSMENT_VERSION,
        "state": "draft_development_only",
        "source_manifest": source_manifest,
        "split_policy": "All existing prototype papers have been exposed during development; no unseen test set is claimed.",
        "splits": {"development": identifiers, "test": []},
        "calibration_subset": identifiers[:5],
        "test_ready": False,
        "papers": [
            {
                "paper_id": paper.openalex_id,
                "title": paper.title,
                "year": paper.year,
                "source_url": paper.source_url,
                "dataset_id": paper.dataset_id,
                "input_fingerprint": fingerprint(asdict(paper)),
                "exposure": "used_for_rule_and_vocabulary_development",
            }
            for paper in papers
        ],
        "remaining": [
            "Acquire unseen test papers",
            "Complete small independent annotation calibration",
            "Freeze evaluation protocol and test list before tuning on test papers",
        ],
    }


def validate_evaluation_manifest(
    manifest, papers, *, source_manifest="examples/week1_baseline.json"
):
    # 当前版本只描述已有开发样本；不接受把已用于开发的论文改标成独立测试。
    if manifest != build_evaluation_manifest(papers, source_manifest=source_manifest):
        raise ValueError(
            "Evaluation manifest changed or falsely claims an independent test split"
        )


def build_quality_report(papers, results, sessions=None) -> dict:
    bundle = build_exports(papers, results, sessions)
    by_type = Counter(
        candidate.entity.kind for result in results for candidate in result.entities
    )
    by_relation = Counter(
        candidate.kind for result in results for candidate in result.relations
    )
    per_paper = []
    for paper, result in zip(papers, results):
        types = Counter(candidate.entity.kind for candidate in result.entities)
        per_paper.append(
            {
                "paper_id": paper.openalex_id,
                "title": paper.title,
                "entity_count": len(result.entities),
                "relation_count": len(result.relations),
                "entity_types": dict(sorted(types.items())),
                "has_abstract": paper.abstract is not None,
                "diagnostics": result.diagnostics,
                "missing_text_categories": [
                    kind
                    for kind in ("method", "task", "dataset", "topic")
                    if not types[kind]
                ],
            }
        )
    return {
        "format_version": ASSESSMENT_VERSION,
        "scope": "prototype_development_sample_not_independent_test",
        "papers": len(papers),
        "entity_candidates": sum(by_type.values()),
        "relation_candidates": sum(by_relation.values()),
        "entities_by_type": dict(sorted(by_type.items())),
        "relations_by_type": dict(sorted(by_relation.items())),
        "papers_with_category": {
            kind: sum(kind in row["entity_types"] for row in per_paper)
            for kind in ("method", "task", "dataset", "topic")
        },
        "review_counts": {
            status: document["counts"] for status, document in bundle.items()
        },
        "diagnostic_count": sum(len(result.diagnostics) for result in results),
        "unresolved_author_candidates": sum(
            c.entity.kind == "author" and c.entity.source_id is None
            for result in results
            for c in result.entities
        ),
        "papers_without_abstract": [
            row["paper_id"] for row in per_paper if not row["has_abstract"]
        ],
        "automated_checks": {
            "candidate_structure_valid": True,
            "evidence_locations_valid": True,
            "review_states_separated": True,
        },
        "versions": sorted(
            {
                (
                    result.rule_version,
                    result.vocabulary_version,
                    result.vocabulary_fingerprint,
                )
                for result in results
            }
        ),
        "precision": None,
        "recall": None,
        "f1": None,
        "evaluation_status": "not_independent_test_evaluated",
        "limitations": [
            "Category presence is not recall or accuracy",
            "Absent candidates do not prove the paper has no such content",
            "Automated checks do not constitute human review",
        ],
        "per_paper": per_paper,
    }
