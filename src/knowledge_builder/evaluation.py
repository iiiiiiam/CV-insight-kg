"""小样本文本提及标注与精确匹配评分；未标注不当作全错或全对。"""

from dataclasses import asdict
from datetime import datetime

from .extraction import fingerprint, validate_evidence, validate_result
from .models import Evidence
from .serialization import nonempty_text, require_fields

ANNOTATION_VERSION = "b-mention-annotation/0.1-draft"
TEXT_KINDS = {"topic", "method", "task", "dataset"}


def build_annotation_template(papers, *, limit=5) -> dict:
    if type(limit) is not int or limit < 0:
        raise ValueError("Invalid annotation limit")
    return {
        "format_version": ANNOTATION_VERSION,
        "scope": "development_calibration_text_mentions_only",
        "matching": "paper_id+kind+canonical_name_casefold+field+start+end",
        "cases": [
            {
                "paper_id": paper.openalex_id,
                "input_fingerprint": fingerprint(asdict(paper)),
                "source_url": paper.source_url,
                "title": paper.title,
                "abstract": paper.abstract,
                "annotation_status": "unannotated",
                "annotator": None,
                "completed_at": None,
                "gold_entities": None,
            }
            for paper in papers[:limit]
        ],
    }


def _mention_key(paper_id, kind, name, field, start, end):
    return (paper_id, kind, name.casefold(), field, start, end)


def score_annotations(annotations: dict, papers, results) -> dict:
    require_fields(annotations, ("format_version", "scope", "matching", "cases"))
    expected = build_annotation_template([])
    if any(
        annotations[key] != expected[key]
        for key in ("format_version", "scope", "matching")
    ):
        raise ValueError("Unsupported annotation version or scope")
    if len(papers) != len(results) or not isinstance(annotations["cases"], list):
        raise ValueError("Invalid annotation inputs")
    inputs = {
        paper.openalex_id: (paper, result) for paper, result in zip(papers, results)
    }
    if len(inputs) != len(papers):
        raise ValueError("Duplicate source papers")
    for paper, result in inputs.values():
        validate_result(paper, result)
    seen, gold, predicted = set(), set(), set()
    incomplete = []
    for case in annotations["cases"]:
        require_fields(
            case,
            (
                "paper_id",
                "input_fingerprint",
                "source_url",
                "title",
                "abstract",
                "annotation_status",
                "annotator",
                "completed_at",
                "gold_entities",
            ),
        )
        identifier = case["paper_id"]
        if (
            not isinstance(identifier, str)
            or identifier not in inputs
            or identifier in seen
        ):
            raise ValueError("Unknown or duplicate annotation paper")
        seen.add(identifier)
        paper, result = inputs[identifier]
        for key, value in (
            ("input_fingerprint", fingerprint(asdict(paper))),
            ("source_url", paper.source_url),
            ("title", paper.title),
            ("abstract", paper.abstract),
        ):
            if case[key] != value:
                raise ValueError("Annotation source input changed")
        if case["annotation_status"] == "unannotated":
            if any(
                case[key] is not None
                for key in ("annotator", "completed_at", "gold_entities")
            ):
                raise ValueError(
                    "Unannotated cases must not pretend to contain completed answers"
                )
            incomplete.append(identifier)
            continue
        if case["annotation_status"] != "completed":
            raise ValueError("Unknown annotation status")
        nonempty_text(case["annotator"])
        nonempty_text(case["completed_at"])
        if datetime.fromisoformat(case["completed_at"]).utcoffset() is None:
            raise ValueError("Annotation time must include a timezone")
        if not isinstance(case["gold_entities"], list):
            raise ValueError("Completed annotations require an explicit gold list")
        for item in case["gold_entities"]:
            require_fields(
                item, ("kind", "canonical_name", "field", "start", "end", "quote")
            )
            if (
                not isinstance(item["kind"], str)
                or item["kind"] not in TEXT_KINDS
                or item["field"] not in ("title", "abstract")
            ):
                raise ValueError(
                    "Annotation supports four text mention categories only"
                )
            nonempty_text(item["canonical_name"])
            proof = Evidence(
                identifier,
                paper.dataset_id,
                paper.source_url,
                case["input_fingerprint"],
                item["field"],
                item["quote"],
                item["start"],
                item["end"],
            )
            validate_evidence(paper, proof)
            key = _mention_key(
                identifier,
                item["kind"],
                item["canonical_name"],
                item["field"],
                item["start"],
                item["end"],
            )
            if key in gold:
                raise ValueError("Duplicate gold mention")
            gold.add(key)
        for candidate in result.entities:
            if candidate.entity.kind in TEXT_KINDS:
                for proof in candidate.evidence:
                    if proof.field in ("title", "abstract"):
                        predicted.add(
                            _mention_key(
                                identifier,
                                candidate.entity.kind,
                                candidate.entity.name,
                                proof.field,
                                proof.start,
                                proof.end,
                            )
                        )
    outcome = {
        "scope": expected["scope"],
        "annotation_fingerprint": fingerprint(annotations),
        "cases": len(seen),
        "completed_cases": len(seen) - len(incomplete),
        "incomplete_papers": incomplete,
        "precision": None,
        "recall": None,
        "f1": None,
        "true_positive": None,
        "false_positive": None,
        "false_negative": None,
        "status": "awaiting_annotations",
        "limitations": "Development-only exact text mention matching; not all eight entity types, relationships, disambiguation or an unseen test score.",
    }
    if incomplete or not seen:
        return outcome
    tp, fp, fn = len(gold & predicted), len(predicted - gold), len(gold - predicted)
    outcome.update(
        {
            "status": "development_scored",
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        }
    )
    return outcome
