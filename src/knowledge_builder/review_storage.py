"""版本化本地审核存档；恢复通过核心业务重放，不直接信任文件状态。"""

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .extraction import fingerprint
from .models import (
    Entity,
    Evidence,
    ExtractionResult,
    PaperInput,
    Relation,
    ReviewEvent,
    ReviewItem,
)
from .review import REVIEW_VERSION, ReviewSession

FILE_VERSION = "b-review-file/0.1-draft"


@dataclass(frozen=True)
class StoredReview:
    session: ReviewSession
    revision: str


def review_to_dict(session: ReviewSession) -> dict:
    original = session.original
    payload = {
        "format_version": FILE_VERSION,
        "review_version": REVIEW_VERSION,
        "paper_id": original.paper_id,
        "input_fingerprint": original.input_fingerprint,
        "extraction_fingerprint": fingerprint(asdict(original)),
        "items": [asdict(item) for item in session.items],
        "events": [asdict(event) for event in session.history],
    }
    # 转成纯 JSON 数据（包括 tuple → list），与磁盘读取格式一致。
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    return {"payload": payload, "sha256": fingerprint(payload)}


def _record(data, keys):
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ValueError("Invalid archive fields")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty archive text")
    return value


def _evidence(data):
    _record(data, [field.name for field in fields(Evidence)])
    for key in (
        "paper_id",
        "dataset_id",
        "source_url",
        "input_fingerprint",
        "field",
        "quote",
    ):
        _text(data[key])
    if not isinstance(data["path"], list) or any(
        type(part) not in (str, int) for part in data["path"]
    ):
        raise ValueError("Invalid evidence path")
    if any(
        data[key] is not None and type(data[key]) is not int for key in ("start", "end")
    ):
        raise ValueError("Invalid evidence offsets")
    return Evidence(**{**data, "path": tuple(data["path"])})


def _item(data):
    _record(data, [field.name for field in fields(ReviewItem)])
    _text(data["candidate_id"])
    content = data["content"]
    if isinstance(content, dict) and "key" in content:
        _record(content, [field.name for field in fields(Entity)])
        for key in ("key", "kind", "name"):
            _text(content[key])
        if content["source_id"] is not None:
            _text(content["source_id"])
        content = Entity(**content)
    else:
        _record(content, [field.name for field in fields(Relation)])
        for value in content.values():
            _text(value)
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
        tuple(_evidence(e) for e in data["evidence"]),
        data["status"],
    )


def _event(data):
    _record(data, [field.name for field in fields(ReviewEvent)])
    if type(data["sequence"]) is not int or data["sequence"] < 1:
        raise ValueError("Invalid event sequence")
    for key in ("action", "reviewer", "reason", "occurred_at"):
        _text(data[key])
    return ReviewEvent(
        **{**data, "before": _item(data["before"]), "after": _item(data["after"])}
    )


def restore_review(
    document: dict, paper: PaperInput, result: ExtractionResult
) -> ReviewSession:
    _record(document, ("payload", "sha256"))
    payload = document["payload"]
    if fingerprint(payload) != document["sha256"]:
        raise ValueError("Archive checksum mismatch")
    _record(
        payload,
        (
            "format_version",
            "review_version",
            "paper_id",
            "input_fingerprint",
            "extraction_fingerprint",
            "items",
            "events",
        ),
    )
    if (
        payload["format_version"] != FILE_VERSION
        or payload["review_version"] != REVIEW_VERSION
    ):
        raise ValueError("Unsupported review archive version")
    if (
        payload["paper_id"],
        payload["input_fingerprint"],
        payload["extraction_fingerprint"],
    ) != (result.paper_id, result.input_fingerprint, fingerprint(asdict(result))):
        raise ValueError("Archive input or extraction changed")
    if not isinstance(payload["events"], list) or not isinstance(
        payload["items"], list
    ):
        raise ValueError("Archive requires item and event lists")
    events = tuple(_event(event) for event in payload["events"])
    session = ReviewSession.replay(paper, result, events)
    items = tuple(_item(item) for item in payload["items"])
    if items != session.items:
        raise ValueError("Archive current state does not match replayed events")
    return session


def load_review(
    path: str | Path, paper: PaperInput, result: ExtractionResult
) -> StoredReview:
    body = Path(path).read_bytes()
    session = restore_review(json.loads(body.decode("utf-8")), paper, result)
    return StoredReview(session, hashlib.sha256(body).hexdigest())


@contextmanager
def _write_lock(path):
    lock = path.open("x", encoding="utf-8")
    try:
        yield
    finally:
        lock.close()
        path.unlink()


def save_review(
    path: str | Path, session: ReviewSession, *, expected_revision: str | None = None
) -> str:
    """新文件默认不覆盖；更新须带读取时的版本指纹。相同目录临时写入再替换。"""
    document = review_to_dict(session)
    body = (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    temporary_path = None
    # 独占创建简易写锁；同样使用此 API 的写入者不会互相覆盖。
    with _write_lock(lock_path):
        try:
            if path.exists():
                if expected_revision is None:
                    raise FileExistsError(
                        "Archive exists; load it before saving changes"
                    )
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected_revision:
                    raise ValueError("Archive changed on disk; reload before saving")
            elif expected_revision is not None:
                raise ValueError(
                    "Archive was removed; refusing to recreate stale state"
                )
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
            ) as temp:
                temporary_path = Path(temp.name)
                temp.write(body)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(body).hexdigest()
