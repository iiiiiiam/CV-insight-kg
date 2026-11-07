"""B-owned reading and feedback routes; shared login remains D-owned."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.application.knowledge import KnowledgeSnapshot, KnowledgeSnapshotInvalid
from server.domain.auth import Session, require_admin, require_admin_write
from src.knowledge_builder.extraction import load_vocabulary
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStore, FeedbackStoreInvalid, KnowledgeFeedback


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

    def workspace():
        snapshot = KnowledgeSnapshot(vocabulary_path=settings.b_vocabulary_path,
                                    reviews_directory=settings.b_reviews_directory)
        path = Path(settings.b_vocabulary_path) if settings.b_vocabulary_path else None
        if path is not None and not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        vocabulary = load_vocabulary(path)
        return KnowledgeFeedback(snapshot.papers, snapshot.results, snapshot.sessions,
            vocabulary, FeedbackStore(snapshot.review_directory / "_feedback" / "state.json"))

    def call(method, *args, **kwargs):
        try:
            return getattr(workspace(), method)(*args, **kwargs)
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

    @router.get("/api/knowledge/papers")
    def papers():
        return call("list_papers")

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

    @router.post("/api/admin/knowledge/feedback/{identifier}")
    def resolve(identifier: str, body: FeedbackResolution,
                session: Session = Depends(require_admin_write)):
        return call("resolve", identifier, reviewer=session.username, **body.model_dump())

    @router.post("/api/admin/knowledge/feedback/{identifier}/reopen")
    def reopen(identifier: str, body: FeedbackReopen,
               session: Session = Depends(require_admin_write)):
        return call("reopen", identifier, revision=body.revision, reviewer=session.username)

    return router
