"""带来源与证据的业务导出；三种状态分离，不把候选升级为知识。"""

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta

from .export_schema import EXPORT_KINDS, EXPORT_VERSION
from .extraction import SCHEMA_VERSION, fingerprint, validate_result
from .models import (
    Entity,
    EntityCandidate,
    ExtractionResult,
    Relation,
    RelationCandidate,
)
from .review import REVIEW_VERSION, ReviewSession
from .serialization import nonempty_text, require_fields, review_item_from_dict


def _json_data(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _counts(papers):
    return {
        "papers": len(papers),
        "entities": sum(len(p["entities"]) for p in papers),
        "relations": sum(len(p["relations"]) for p in papers),
    }


def build_exports(papers, results, sessions=None) -> dict:
    """相同输入和决定产生相同内容；不生成获取时间，不修改审核或输入。"""
    if len(papers) != len(results):
        raise ValueError("Paper and result counts differ")
    sessions = {} if sessions is None else sessions
    paper_ids = [paper.openalex_id for paper in papers]
    if len(set(paper_ids)) != len(paper_ids) or set(sessions) - set(paper_ids):
        raise ValueError("Duplicate papers or unknown review sessions")
    bundle = {
        status: {
            "format_version": EXPORT_VERSION,
            "contract_status": "draft",
            "kind": kind,
            "status": status,
            "papers": [],
            "counts": {},
        }
        for status, kind in EXPORT_KINDS.items()
    }
    for paper, result in zip(papers, results):
        validate_result(paper, result)
        current = sessions.get(paper.openalex_id)
        if current is not None:
            current.check_input(paper)
            if current.original != result:
                raise ValueError("Review session belongs to another extraction")
            session = ReviewSession.replay(paper, result, current.history)
            if session.items != current.items:
                raise ValueError("Review state does not match its history")
        else:
            session = ReviewSession(paper, result)
        latest = {event.after.candidate_id: event for event in session.history}

        def entry(item):
            event = latest.get(item.candidate_id)
            review = (
                None
                if event is None
                else {
                    key: getattr(event, key)
                    for key in (
                        "sequence",
                        "action",
                        "reviewer",
                        "reason",
                        "occurred_at",
                    )
                }
            )
            return {"item": asdict(item), "review": review}

        by_key = {
            item.content.key: item
            for item in session.items
            if isinstance(item.content, Entity)
        }
        for status in bundle:
            selected = session.select(status)
            if not selected.entities and not selected.relations:
                continue
            selected_keys = {item.content.key for item in selected.entities}
            context_keys = {
                key
                for item in selected.relations
                for key in (item.content.source, item.content.target)
            } - selected_keys
            bundle[status]["papers"].append(
                {
                    "input": asdict(paper),
                    "origin": {
                        "source_schema_version": result.schema_version,
                        "input_fingerprint": result.input_fingerprint,
                        "extraction_fingerprint": fingerprint(asdict(result)),
                        "rule_version": result.rule_version,
                        "vocabulary_version": result.vocabulary_version,
                        "vocabulary_fingerprint": result.vocabulary_fingerprint,
                        "review_version": REVIEW_VERSION,
                    },
                    "entities": [entry(item) for item in selected.entities],
                    "relations": [entry(item) for item in selected.relations],
                    "endpoint_context": [
                        entry(by_key[key]) for key in sorted(context_keys)
                    ],
                    "diagnostics": list(result.diagnostics),
                }
            )
    for document in bundle.values():
        document["counts"] = _counts(document["papers"])
    bundle = _json_data(bundle)
    validate_exports(bundle, papers)
    return bundle


def _validate_review(entry):
    require_fields(entry, ("item", "review"))
    item = review_item_from_dict(entry["item"])
    review = entry["review"]
    if review is None:
        if item.status != "pending":
            raise ValueError("Decided item requires an explicit review record")
        return item
    require_fields(review, ("sequence", "action", "reviewer", "reason", "occurred_at"))
    if type(review["sequence"]) is not int or review["sequence"] < 1:
        raise ValueError("Invalid review sequence")
    for key in ("action", "reviewer", "reason", "occurred_at"):
        nonempty_text(review[key])
    if datetime.fromisoformat(review["occurred_at"]).utcoffset() != timedelta(0):
        raise ValueError("Review record requires UTC time")
    allowed = {
        "confirmed": {"confirm"},
        "rejected": {"reject"},
        "pending": {"correct", "reopen", "reopen_dependency"},
    }
    if review["action"] not in allowed[item.status]:
        raise ValueError("Review action does not match current status")
    return item


def validate_exports(bundle: dict, papers) -> None:
    """验证三份导出的业务约束和真实证据；不是 JSON Schema 引擎或身份认证。"""
    require_fields(bundle, EXPORT_KINDS)
    inputs = {paper.openalex_id: paper for paper in papers}
    if len(inputs) != len(papers):
        raise ValueError("Duplicate input papers")
    all_entities, context_entries, origins = {}, [], {}
    diagnostics_by_paper = {}
    represented_papers = set()
    seen_candidates = set()
    for status, kind in EXPORT_KINDS.items():
        document = bundle[status]
        require_fields(
            document,
            ("format_version", "contract_status", "kind", "status", "papers", "counts"),
        )
        if (
            document["format_version"],
            document["contract_status"],
            document["kind"],
            document["status"],
        ) != (EXPORT_VERSION, "draft", kind, status):
            raise ValueError("Unsupported export version, kind or status")
        if not isinstance(document["papers"], list):
            raise ValueError("Export papers must be a list")
        seen_papers = set()
        for section in document["papers"]:
            require_fields(
                section,
                (
                    "input",
                    "origin",
                    "entities",
                    "relations",
                    "endpoint_context",
                    "diagnostics",
                ),
            )
            raw_input = section["input"]
            if not isinstance(raw_input, dict):
                raise ValueError("Missing source input")
            paper_id = raw_input.get("openalex_id")
            if (
                not isinstance(paper_id, str)
                or paper_id not in inputs
                or paper_id in seen_papers
            ):
                raise ValueError("Unknown or duplicate exported paper")
            seen_papers.add(paper_id)
            paper = inputs[paper_id]
            if raw_input != _json_data(asdict(paper)):
                raise ValueError("Export input differs from source paper")
            origin = section["origin"]
            require_fields(
                origin,
                (
                    "source_schema_version",
                    "input_fingerprint",
                    "extraction_fingerprint",
                    "rule_version",
                    "vocabulary_version",
                    "vocabulary_fingerprint",
                    "review_version",
                ),
            )
            if (
                origin["source_schema_version"] != SCHEMA_VERSION
                or origin["review_version"] != REVIEW_VERSION
                or origin["input_fingerprint"] != fingerprint(asdict(paper))
            ):
                raise ValueError("Incompatible source version or input fingerprint")
            for key in (
                "input_fingerprint",
                "extraction_fingerprint",
                "vocabulary_fingerprint",
            ):
                if not isinstance(origin[key], str) or not re.fullmatch(
                    "[a-f0-9]{64}", origin[key]
                ):
                    raise ValueError("Invalid source fingerprint")
            for key in ("rule_version", "vocabulary_version"):
                nonempty_text(origin[key])
            if paper_id in origins and origin != origins[paper_id]:
                raise ValueError("Conflicting export origins")
            origins[paper_id] = origin
            for key in ("entities", "relations", "endpoint_context", "diagnostics"):
                if not isinstance(section[key], list):
                    raise ValueError("Invalid export list")
            if not section["entities"] and not section["relations"]:
                raise ValueError("Empty paper sections must be omitted")
            for diagnostic in section["diagnostics"]:
                nonempty_text(diagnostic)
            if (
                paper_id in diagnostics_by_paper
                and section["diagnostics"] != diagnostics_by_paper[paper_id]
            ):
                raise ValueError("Conflicting source diagnostics")
            diagnostics_by_paper[paper_id] = section["diagnostics"]
            parsed = {}
            for key in ("entities", "relations", "endpoint_context"):
                parsed[key] = []
                for entry in section[key]:
                    item = _validate_review(entry)
                    expected_type = Relation if key == "relations" else Entity
                    if not isinstance(item.content, expected_type):
                        raise ValueError("Wrong entity or relation collection")
                    parsed[key].append(item)
                    if key == "endpoint_context":
                        context_entries.append((paper_id, entry))
                        continue
                    if item.status != status:
                        raise ValueError("Review statuses must be separated")
                    identifier = (paper_id, item.candidate_id)
                    if identifier in seen_candidates:
                        raise ValueError("Candidate appears more than once")
                    seen_candidates.add(identifier)
                    if key == "entities":
                        all_entities[identifier] = entry
                        if item.content.kind == "paper":
                            if (
                                item.content.key != "paper:" + paper_id
                                or item.content.source_id != paper_id
                            ):
                                raise ValueError(
                                    "Paper entity does not identify its source input"
                                )
                            represented_papers.add(paper_id)
            entities = parsed["entities"] + parsed["endpoint_context"]
            by_key = {item.content.key: item for item in entities}
            if len(by_key) != len(entities):
                raise ValueError("Duplicate entity or endpoint context")
            needed = {
                key
                for item in parsed["relations"]
                for key in (item.content.source, item.content.target)
            } - {item.content.key for item in parsed["entities"]}
            if needed != {item.content.key for item in parsed["endpoint_context"]}:
                raise ValueError("Missing or unnecessary endpoint context")
            if status == "confirmed" and parsed["endpoint_context"]:
                raise ValueError(
                    "Confirmed relations require confirmed entities in the knowledge file"
                )
            temporary = ExtractionResult(
                paper_id,
                origin["input_fingerprint"],
                SCHEMA_VERSION,
                origin["rule_version"],
                origin["vocabulary_version"],
                origin["vocabulary_fingerprint"],
                [
                    EntityCandidate(
                        item.candidate_id, item.content, list(item.evidence)
                    )
                    for item in entities
                ],
                [
                    RelationCandidate(
                        item.candidate_id,
                        item.content.source,
                        item.content.kind,
                        item.content.target,
                        list(item.evidence),
                    )
                    for item in parsed["relations"]
                ],
                section["diagnostics"],
            )
            validate_result(paper, temporary)
        require_fields(document["counts"], ("papers", "entities", "relations"))
        if any(
            type(value) is not int for value in document["counts"].values()
        ) or document["counts"] != _counts(document["papers"]):
            raise ValueError("Export counts do not match contents")
    for paper_id, entry in context_entries:
        if all_entities.get((paper_id, entry["item"]["candidate_id"])) != entry:
            raise ValueError(
                "Endpoint context does not match the entity in its own status file"
            )
    if represented_papers != set(inputs):
        raise ValueError(
            "Export must include the paper candidate for every source input"
        )
