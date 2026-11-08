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
    ExtractionResult,
    PaperInput,
    ReviewEvent,
)
from .review import REVIEW_VERSION, ReviewSession
from .serialization import (
    nonempty_text,
    require_fields,
    review_item_from_dict,
)

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


def _event(data):
    require_fields(data, [field.name for field in fields(ReviewEvent)])
    if type(data["sequence"]) is not int or data["sequence"] < 1:
        raise ValueError("Invalid event sequence")
    for key in ("action", "reviewer", "reason", "occurred_at"):
        nonempty_text(data[key])
    return ReviewEvent(
        **{
            **data,
            "before": review_item_from_dict(data["before"]),
            "after": review_item_from_dict(data["after"]),
        }
    )


def restore_review(
    document: dict, paper: PaperInput, result: ExtractionResult
) -> ReviewSession:
    require_fields(document, ("payload", "sha256"))
    payload = document["payload"]
    if fingerprint(payload) != document["sha256"]:
        raise ValueError("Archive checksum mismatch")
    require_fields(
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
    items = tuple(review_item_from_dict(item) for item in payload["items"])
    if items != session.items:
        raise ValueError("Archive current state does not match replayed events")
    return session


def load_review(
    path: str | Path, paper: PaperInput, result: ExtractionResult
) -> StoredReview:
    body = Path(path).read_bytes()
    session = restore_review(json.loads(body.decode("utf-8")), paper, result)
    return StoredReview(session, hashlib.sha256(body).hexdigest())


def load_review_records(directory: str | Path, papers, results) -> dict:
    """扫描专用目录并验证每份存档；重复、损坏或不属于本次样本时拒绝。"""
    directory = Path(directory)
    if directory.exists() and not directory.is_dir():
        raise ValueError("Reviews path must be a directory")
    if len(papers) != len(results):
        raise ValueError("Paper and result counts differ")
    inputs = {
        paper.openalex_id: (paper, result) for paper, result in zip(papers, results)
    }
    if len(inputs) != len(papers):
        raise ValueError("Duplicate input papers")
    sessions = {}
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(
            document.get("payload"), dict
        ):
            raise ValueError(f"Invalid review archive: {path}")
        paper_id = document["payload"].get("paper_id")
        if not isinstance(paper_id, str) or paper_id not in inputs:
            raise ValueError(f"Archive refers to a paper outside this sample: {path}")
        if paper_id in sessions:
            raise ValueError(f"Multiple review archives for one paper: {path}")
        paper, result = inputs[paper_id]
        sessions[paper_id] = (path, load_review(path, paper, result))
    return sessions


def load_review_sessions(directory: str | Path, papers, results) -> dict:
    return {
        identifier: stored.session
        for identifier, (_, stored) in load_review_records(
            directory, papers, results
        ).items()
    }


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
