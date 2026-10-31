"""业务 JSON 的机器可读结构说明；只使用标准库，不执行 JSON Schema 引擎。"""

from typing import get_args

from .extraction import RELATIONS, SCHEMA_VERSION
from .models import EntityType
from .review import REVIEW_VERSION

EXPORT_VERSION = "b-knowledge-export/0.1-draft"
EXPORT_KINDS = {
    "pending": "pending_candidates",
    "confirmed": "confirmed_knowledge",
    "rejected": "rejected_candidates",
}


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def export_schema() -> dict:
    text = {"type": "string", "pattern": r"\S"}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    status = {"enum": list(EXPORT_KINDS)}
    evidence = object_schema(
        {
            "paper_id": text,
            "dataset_id": text,
            "source_url": text,
            "input_fingerprint": digest,
            "field": {"enum": ["title", "abstract", "metadata"]},
            "quote": text,
            "start": {"type": ["integer", "null"], "minimum": 0},
            "end": {"type": ["integer", "null"], "minimum": 1},
            "path": {
                "type": "array",
                "items": {"oneOf": [text, {"type": "integer", "minimum": 0}]},
            },
        }
    )
    evidence["allOf"] = [
        {
            "if": {"properties": {"field": {"const": "metadata"}}},
            "then": {
                "properties": {
                    "start": {"type": "null"},
                    "end": {"type": "null"},
                    "path": {"minItems": 1},
                }
            },
            "else": {
                "properties": {
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "path": {"maxItems": 0},
                }
            },
        }
    ]
    entity = object_schema(
        {
            "key": text,
            "kind": {"enum": list(get_args(EntityType))},
            "name": text,
            "source_id": {"oneOf": [text, {"type": "null"}]},
        }
    )
    relation = object_schema(
        {"source": text, "kind": {"enum": list(RELATIONS)}, "target": text}
    )
    review = object_schema(
        {
            "sequence": {"type": "integer", "minimum": 1},
            "action": {
                "enum": ["confirm", "reject", "correct", "reopen", "reopen_dependency"]
            },
            "reviewer": text,
            "reason": text,
            "occurred_at": {"type": "string", "format": "date-time"},
        }
    )
    definitions = {
        "evidence": evidence,
        "entity": entity,
        "relation": relation,
        "review": review,
    }
    for kind in ("entity", "relation"):
        definitions[kind + "_entry"] = object_schema(
            {
                "item": object_schema(
                    {
                        "candidate_id": digest,
                        "content": {"$ref": "#/$defs/" + kind},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"$ref": "#/$defs/evidence"},
                        },
                        "status": status,
                    }
                ),
                "review": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/review"}]},
            }
        )
    definitions["paper"] = object_schema(
        {
            "input": object_schema(
                {
                    "openalex_id": text,
                    "title": text,
                    "abstract": {"type": ["string", "null"]},
                    "year": {"type": "integer"},
                    "venue": text,
                    "authorships": {"type": "array", "items": {"type": "object"}},
                    "source_url": text,
                    "dataset_id": text,
                }
            ),
            "origin": object_schema(
                {
                    "source_schema_version": {"const": SCHEMA_VERSION},
                    "input_fingerprint": digest,
                    "extraction_fingerprint": digest,
                    "rule_version": text,
                    "vocabulary_version": text,
                    "vocabulary_fingerprint": digest,
                    "review_version": {"const": REVIEW_VERSION},
                }
            ),
            "entities": {"type": "array", "items": {"$ref": "#/$defs/entity_entry"}},
            "relations": {"type": "array", "items": {"$ref": "#/$defs/relation_entry"}},
            "endpoint_context": {
                "type": "array",
                "items": {"$ref": "#/$defs/entity_entry"},
            },
            "diagnostics": {"type": "array", "items": text},
        }
    )
    schema = object_schema(
        {
            "format_version": {"const": EXPORT_VERSION},
            "contract_status": {"const": "draft"},
            "kind": {"enum": list(EXPORT_KINDS.values())},
            "status": status,
            "papers": {"type": "array", "items": {"$ref": "#/$defs/paper"}},
            "counts": object_schema(
                {
                    key: {"type": "integer", "minimum": 0}
                    for key in ("papers", "entities", "relations")
                }
            ),
        }
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$defs"] = definitions
    schema["allOf"] = []
    for value, kind in EXPORT_KINDS.items():
        paper_rules = {
            key: {
                "items": {
                    "properties": {"item": {"properties": {"status": {"const": value}}}}
                }
            }
            for key in ("entities", "relations")
        }
        if value == "confirmed":
            paper_rules["endpoint_context"] = {"maxItems": 0}
        schema["allOf"].append(
            {
                "if": {"properties": {"status": {"const": value}}},
                "then": {
                    "properties": {
                        "kind": {"const": kind},
                        "papers": {"items": {"properties": paper_rules}},
                    }
                },
            }
        )
    return schema
