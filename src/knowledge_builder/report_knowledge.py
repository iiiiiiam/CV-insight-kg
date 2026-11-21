"""A frozen B knowledge attachment for A's reports; no jobs or graph publication."""

import json
import os
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .author_tags import build_author_tags
from .effective_export import REVIEW_STATES, validate_effective_export
from .extraction import fingerprint
from .feedback import FeedbackConflict

FORMAT = "knowledge-report/1"
QUALITY_VERSION = "effective-facts/1"
ENTITY_KINDS = ("paper", "author", "institution", "venue", "topic", "method", "task", "dataset")
RELATION_KINDS = ("has_author", "affiliated_with", "published_in", "mentions_topic",
                  "mentions_method", "mentions_task", "mentions_dataset")


def _coverage(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator,
                ratio=numerator / denominator if denominator else None)


def build_knowledge_quality(document):
    """Count effective item occurrences, not raw candidates, accuracy or global people."""
    validate_effective_export(document)
    entities, relations, fields, states = Counter(), Counter(), Counter(), Counter()
    rows = []
    evidence_items = rule_adjusted = 0
    for part in document["papers"]:
        types = Counter(item["content"]["kind"] for item in part["entities"])
        entities.update(types)
        relations.update(item["content"]["kind"] for item in part["relations"])
        unresolved = sum(item["content"]["kind"] == "author" and not item["content"].get("source_id")
                         for item in part["entities"])
        for item in part["entities"] + part["relations"]:
            evidence_items += bool(item["evidence"])
            fields.update(proof["field"] for proof in item["evidence"])
            states[item["provenance"]["review_state"]] += 1
            rule_adjusted += item["provenance"]["rule_adjusted"]
        rows.append(dict(
            paper_id=part["input"]["openalex_id"],
            input_fingerprint=part["origin"]["input_fingerprint"],
            entity_count=len(part["entities"]), relation_count=len(part["relations"]),
            entities_by_kind={kind: types[kind] for kind in ENTITY_KINDS},
            unresolved_author_occurrences=unresolved,
            has_abstract=bool((part["input"]["abstract"] or "").strip()),
            has_source_url=bool(part["input"]["source_url"]),
            source_classification_count=len(part["source_classifications"]),
            missing_text_categories=[kind for kind in ("topic", "method", "task", "dataset") if not types[kind]],
        ))
    items = sum(entities.values()) + sum(relations.values())
    unresolved = sum(row["unresolved_author_occurrences"] for row in rows)
    return dict(
        rule_version=QUALITY_VERSION, knowledge_revision=document["revision"],
        counting_unit="effective_item_occurrences_per_paper",
        counts=dict(papers=len(rows), entities=sum(entities.values()), relations=sum(relations.values())),
        entities_by_kind={kind: entities[kind] for kind in ENTITY_KINDS},
        relations_by_kind={kind: relations[kind] for kind in RELATION_KINDS},
        review_states={state: states[state] for state in sorted(REVIEW_STATES)},
        rule_adjusted_items=rule_adjusted,
        evidence_coverage=_coverage(evidence_items, items),
        evidence_occurrences_by_field={field: fields[field] for field in ("title", "abstract", "metadata")},
        identified_author_coverage=_coverage(entities["author"] - unresolved, entities["author"]),
        papers_with_abstract=_coverage(sum(row["has_abstract"] for row in rows), len(rows)),
        papers_with_source_classifications=_coverage(sum(row["source_classification_count"] > 0 for row in rows), len(rows)),
        accuracy=dict(precision=None, recall=None, f1=None, status="no_independent_annotations"),
        external_source_availability=dict(status="not_recorded_in_effective_contract",
                                          pending=None, failed=None, with_sources=None),
        limitations=[
            "Evidence coverage and category presence are not accuracy or recall.",
            "Missing categories do not prove the paper has no such content.",
            "Source classifications do not measure external-source availability; see the live batch status separately.",
            "Snapshot records do not include rejected batches, source-fetch errors or personal browser edits.",
            "Author source IDs are supplied by input metadata, not independently verified natural-person identities.",
        ],
        per_paper=sorted(rows, key=lambda row: row["paper_id"]),
    )


def build_report_knowledge(document, *, expected_revision=None):
    """Derive everything from one immutable effective document; leave C's format intact."""
    document = deepcopy(document)
    validate_effective_export(document)
    if expected_revision is not None and expected_revision != document["revision"]:
        raise FeedbackConflict("当前有效知识版本已变化，请刷新后重新获取报告知识")
    tags = build_author_tags(document)
    # Export time is not content. Repeated downloads of the same snapshot have
    # the same report revision, while the original timestamp remains available.
    content = dict(
        format_version=FORMAT,
        scope=dict(mode="full_effective_snapshot", knowledge_revision=document["revision"],
                   paper_ids=tags["paper_ids"], paper_count=len(document["papers"])),
        knowledge={key: value for key, value in document.items() if key != "generated_at"},
        author_tags=tags, quality=build_knowledge_quality(document),
    )
    return {**content, "knowledge": document, "revision": fingerprint(content),
            "generated_at": document["generated_at"]}


def validate_report_knowledge(document):
    rebuilt = build_report_knowledge(document["knowledge"])
    if document != rebuilt:
        raise ValueError("Report knowledge contents or checksum differ from the effective snapshot")
    return document


def write_report_knowledge(document, path):
    """Atomic JSON output; an invalid report or failed replace preserves the old file."""
    validate_report_knowledge(document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(document, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
