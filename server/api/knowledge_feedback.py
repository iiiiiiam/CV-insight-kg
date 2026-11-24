"""B-owned reading and feedback routes; shared login remains D-owned."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from server.application.knowledge import KnowledgeSnapshot, KnowledgeSnapshotInvalid
from server.domain.auth import Session, require_admin, require_admin_write
from server.application.knowledge_reading import reading_workspace, reading_report, reading_effective
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStoreInvalid


class FeedbackSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    paper_id: str = Field(min_length=1, max_length=300)
    revision: str = Field(pattern="^[0-9a-f]{64}$")
    message: str = Field(min_length=1, max_length=2000)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=128)
    term: str | None = Field(default=None, min_length=1, max_length=200)
    owner_token: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class FeedbackWithdrawal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_token: str = Field(pattern="^[0-9a-f]{64}$")


class FeedbackResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=0)
    action: Literal["dismiss", "exclude", "rename", "add_term"]
    reason: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, max_length=300)
    kind: Literal["topic", "method", "task", "dataset"] | None = None
    aliases: list[str] | None = Field(default=None, max_length=8)
    source_url: str | None = Field(default=None, max_length=2000)


class FeedbackReopen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


def feedback_router(settings):
    router = APIRouter()
    from server.api.knowledge_batches import batch_router
    router.include_router(batch_router(settings))

    def workspace():
        return reading_workspace(settings, snapshot_factory=KnowledgeSnapshot)

    def execute(operation):
        try:
            return operation()
        except FeedbackConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (FeedbackStoreInvalid, KnowledgeSnapshotInvalid) as exc:
            raise HTTPException(503, "知识或反馈存档暂不可用；原记录保留，请维护人员检查") from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "知识或反馈记录暂不可用，请稍后重试") from exc

    def call(method, *args, **kwargs):
        return execute(lambda: getattr(workspace(), method)(*args, **kwargs))

    def report(expected_revision):
        return execute(lambda: reading_report(settings, expected_revision=expected_revision,
                                              snapshot_factory=KnowledgeSnapshot))

    @router.get("/api/knowledge/papers")
    def papers():
        return call("list_papers")

    @router.get("/api/knowledge/research-directions")
    def directions():
        return call("direction_catalog")

    @router.get("/api/knowledge/paper")
    def paper(paper_id: str = Query(min_length=1, max_length=300)):
        return call("view", paper_id)

    @router.post("/api/knowledge/feedback", status_code=201)
    def submit(body: FeedbackSubmission):
        return call("submit", **body.model_dump())

    @router.get("/api/knowledge/feedback/{identifier}")
    def status(identifier: str):
        return call("status", identifier)

    @router.post("/api/knowledge/feedback/{identifier}/withdraw")
    def withdraw(identifier: str, body: FeedbackWithdrawal):
        return call("withdraw", identifier, owner_token=body.owner_token)

    @router.get("/api/admin/knowledge/feedback")
    def queue(_session: Session = Depends(require_admin)):
        return call("queue")

    @router.get("/api/admin/knowledge/effective-export")
    def export_effective(expected_revision: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
                         _session: Session = Depends(require_admin)):
        document = execute(lambda: reading_effective(settings, expected_revision=expected_revision,
                                                     snapshot_factory=KnowledgeSnapshot))
        return Response(json.dumps(document, ensure_ascii=False, indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="effective-{document["revision"][:12]}.json"',
                     "Cache-Control": "no-store", "X-Knowledge-Revision": document["revision"]})

    @router.get("/api/admin/knowledge/report-export")
    def export_report(expected_revision: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
                      _session: Session = Depends(require_admin)):
        document = report(expected_revision)
        return Response(json.dumps(document, ensure_ascii=False, indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="knowledge-report-{document["revision"][:12]}.json"',
                     "Cache-Control": "no-store", "X-Knowledge-Revision": document["scope"]["knowledge_revision"],
                     "X-Report-Revision": document["revision"]})

    @router.get("/api/knowledge/author-tags")
    def author_tags(expected_revision: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
                    source_id: str | None = Query(default=None, min_length=1, max_length=500),
                    author_ref: str | None = Query(default=None, pattern="^author-ref:[0-9a-f]{64}$")):
        document = report(expected_revision)["author_tags"]
        if source_id is not None or author_ref is not None:
            # Filter exact identities only. Unknown IDs yield an explicit empty
            # selection, never a same-name match or the complete author list.
            selected = [author for author in document["authors"]
                        if (source_id is None or author["source_id"] == source_id)
                        and (author_ref is None or author["author_ref"] == author_ref)]
            document = {**document, "authors": selected,
                        "selection": dict(source_id=source_id, author_ref=author_ref)}
            from src.knowledge_builder.extraction import fingerprint
            document["revision"] = fingerprint({key: value for key, value in document.items() if key != "revision"})
        return Response(json.dumps(document, ensure_ascii=False), media_type="application/json",
            headers={"Cache-Control": "no-store", "X-Knowledge-Revision": document["knowledge_revision"]})

    @router.post("/api/admin/knowledge/feedback/{identifier}")
    def resolve(identifier: str, body: FeedbackResolution,
                session: Session = Depends(require_admin_write)):
        return call("resolve", identifier, reviewer=session.username, **body.model_dump())

    @router.post("/api/admin/knowledge/feedback/{identifier}/reopen")
    def reopen(identifier: str, body: FeedbackReopen,
               session: Session = Depends(require_admin_write)):
        return call("reopen", identifier, revision=body.revision, reviewer=session.username)

    return router
