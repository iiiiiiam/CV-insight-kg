"""JSON 边界的严格字段与模型转换；存档和业务导出共用。"""

from dataclasses import fields

from .models import Entity, Evidence, Relation, ReviewItem


def require_fields(data, keys):
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ValueError("Invalid JSON fields")


def nonempty_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty JSON text")
    return value


def evidence_from_dict(data):
    require_fields(data, [field.name for field in fields(Evidence)])
    for key in (
        "paper_id",
        "dataset_id",
        "source_url",
        "input_fingerprint",
        "field",
        "quote",
    ):
        nonempty_text(data[key])
    if not isinstance(data["path"], list) or any(
        type(part) not in (str, int) for part in data["path"]
    ):
        raise ValueError("Invalid evidence path")
    if any(
        data[key] is not None and type(data[key]) is not int for key in ("start", "end")
    ):
        raise ValueError("Invalid evidence offsets")
    return Evidence(**{**data, "path": tuple(data["path"])})


def review_item_from_dict(data):
    require_fields(data, [field.name for field in fields(ReviewItem)])
    nonempty_text(data["candidate_id"])
    content = data["content"]
    if isinstance(content, dict) and "key" in content:
        require_fields(content, [field.name for field in fields(Entity)])
        for key in ("key", "kind", "name"):
            nonempty_text(content[key])
        if content["source_id"] is not None:
            nonempty_text(content["source_id"])
        content = Entity(**content)
    else:
        require_fields(content, [field.name for field in fields(Relation)])
        for value in content.values():
            nonempty_text(value)
        content = Relation(**content)
    if not isinstance(data["status"], str) or data["status"] not in {
        "pending",
        "confirmed",
        "rejected",
    }:
        raise ValueError("Invalid review status")
    if not isinstance(data["evidence"], list) or not data["evidence"]:
        raise ValueError("Missing evidence")
    return ReviewItem(
        data["candidate_id"],
        content,
        tuple(evidence_from_dict(e) for e in data["evidence"]),
        data["status"],
    )
