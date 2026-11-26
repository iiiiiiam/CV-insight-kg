"""B-owned reading and feedback routes; shared login remains D-owned."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from server.application.knowledge import KnowledgeSnapshot, KnowledgeSnapshotInvalid
from server.domain.auth import Session, require_admin, require_admin_write
from server.application.knowledge_reading import reading_workspace, reading_report, reading_effective
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStoreInvalid
from server.application.cloud_feedback import CloudFeedback, CloudFeedbackError
from server.application.feedback_workflow import FeedbackWorkflow
from src.knowledge_builder.extraction import fingerprint
import hmac
import sqlite3
import time


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
    cloud_revision: int | None = Field(default=None, ge=0)


class FeedbackReopen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    cloud_revision: int | None = Field(default=None, ge=0)


class CloudReply(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: Literal['open', 'resolved', 'dismissed']
    processing_note: str = Field(min_length=1, max_length=2000)
    expected_revision: int = Field(ge=0)


class TeamAccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(pattern='^[a-z][a-z0-9_.-]{2,49}$')
    password: str = Field(min_length=12, max_length=256)
    role: Literal['owner', 'admin']


class TeamAccountUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    role: Literal['owner', 'admin'] | None = None
    enabled: bool | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=256)


class TeamPasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def feedback_router(settings):
    router = APIRouter()
    cloud = CloudFeedback(settings)
    from server.api.knowledge_batches import batch_router
    router.include_router(batch_router(settings))

    def workspace():
        return reading_workspace(settings, snapshot_factory=KnowledgeSnapshot)

    workflow=FeedbackWorkflow(cloud,workspace)

    def team_token(session):
        return cloud.admin or team_session(session)

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
        completed_ids=set()
        if cloud.enabled and body.owner_token:
            try:
                completed_ids=cloud.completed_feedback_ids(body.owner_token)
            except (CloudFeedbackError,OSError,sqlite3.Error,ValueError):
                pass  # Cache failure must not prevent local saving.
        result = call("submit", completed_ids=completed_ids, **body.model_dump())
        stored=next(row for row in workspace().store.read()["requests"] if row["id"]==result["id"])
        result["message"]=stored["message"]
        if cloud.enabled and body.owner_token:
            payload = dict(message=stored["message"], paper_id=body.paper_id, knowledge_revision=body.revision)
            if body.candidate_id:
                payload['candidate_id'] = body.candidate_id
            if body.term:
                payload['display_name'] = body.term
            try:
                cloud.prepare(result['id'], body.owner_token, payload)
                result['cloud'] = cloud.cached(result['id'], body.owner_token)
                if result['cloud'] and result['cloud']['delivery'] != 'sent':
                    try:
                        result['cloud'] = cloud.exchange(result['id'], body.owner_token, 'send')
                    except CloudFeedbackError as exc:
                        result['cloud_error'] = '本地反馈已保存，云端未完成：' + str(exc)
            except (CloudFeedbackError, OSError, sqlite3.Error):
                result['cloud_error'] = '本地反馈已保存，云端回执准备失败；请联系维护者。'
        return result

    @router.get("/api/knowledge/feedback/{identifier}")
    def status(identifier: str, x_feedback_owner: str | None = Header(default=None)):
        result = call("status", identifier)
        if cloud.enabled and x_feedback_owner:
            result['cloud'] = cloud_call(lambda: cloud.cached(identifier, x_feedback_owner))
        if x_feedback_owner:
            request=next((row for row in workspace().store.read()['requests'] if row['id']==identifier),None)
            if request and request.get('owner_digest') and hmac.compare_digest(request['owner_digest'],fingerprint(x_feedback_owner)):
                result['reply_note']=(request.get('resolution') or {}).get('reason','')
        return result

    def cloud_call(operation):
        try:
            return operation()
        except CloudFeedbackError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except LookupError:
            raise HTTPException(404, '未找到当前用户的云反馈回执。') from None
        except ValueError:
            raise HTTPException(422, '云反馈参数无效。') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, '云反馈本地存档暂不可用，原记录保留。') from None

    @router.post('/api/knowledge/feedback/{identifier}/cloud/{operation}')
    def exchange(identifier: str, operation: Literal['send', 'refresh'], body: FeedbackWithdrawal):
        if not cloud.enabled:
            raise HTTPException(409, '此环境未启用云反馈。')
        # Honor existing withdrawal: do not newly submit a withdrawn local record.
        if operation == 'send' and call('status', identifier)['status'] == 'withdrawn':
            raise HTTPException(409, '本地反馈已撤回，不再向云端发送。')
        return cloud_call(lambda: cloud.exchange(identifier, body.owner_token, operation))

    @router.get('/api/admin/knowledge/cloud-feedback/config')
    def cloud_config(_session: Session = Depends(require_admin)):
        return {'enabled': cloud.enabled, 'team_enabled': bool(cloud.enabled and (cloud.admin or
            (_session.cloud_feedback_token and _session.cloud_feedback_expires > time.time()))),
            'account_management': bool(_session.cloud_feedback_role=='owner'
                                      and _session.cloud_feedback_expires>time.time()),
            'team_username': _session.cloud_feedback_username}

    def team_session(session, owner=False):
        if not session.cloud_feedback_token or session.cloud_feedback_expires <= time.time():
            raise HTTPException(401, '请使用团队管理员账号重新登录。')
        if owner and session.cloud_feedback_role != 'owner':
            raise HTTPException(403, '需要账号管理员权限。')
        return session.cloud_feedback_token

    @router.post('/api/admin/knowledge/cloud-feedback/accounts/refresh')
    def accounts_list(session: Session = Depends(require_admin_write)):
        token=team_session(session, owner=True)
        return cloud_call(lambda: cloud.accounts(token))

    @router.post('/api/admin/knowledge/cloud-feedback/accounts/create')
    def account_create(body: TeamAccountCreate, session: Session = Depends(require_admin_write)):
        token=team_session(session, owner=True)
        return cloud_call(lambda: cloud.add_account(body.model_dump(),token))

    @router.post('/api/admin/knowledge/cloud-feedback/accounts/{username}/update')
    def account_update(username: str, body: TeamAccountUpdate, session: Session = Depends(require_admin_write)):
        token=team_session(session, owner=True)
        return cloud_call(lambda: cloud.update_account(username,body.model_dump(exclude_none=True),token))

    @router.post('/api/admin/knowledge/cloud-feedback/password')
    def account_password(body: TeamPasswordChange, session: Session = Depends(require_admin_write)):
        token=team_session(session)
        return cloud_call(lambda: cloud.change_password(body.model_dump(),token))

    @router.post('/api/admin/knowledge/cloud-feedback/refresh')
    def cloud_queue(_session: Session = Depends(require_admin_write)):
        result=cloud_call(lambda: cloud.queue(_session.cloud_feedback_token))
        cloud_call(lambda: cloud.remember_team(result['requests']))
        return result  # Legacy compatibility; main UI uses unified workflow-refresh below.

    @router.post('/api/admin/knowledge/feedback/team-refresh')
    def team_refresh(session: Session = Depends(require_admin_write)):
        return execute(lambda: cloud_call(lambda: workflow.refresh(team_token(session))))

    @router.post('/api/admin/knowledge/feedback/{identifier}/reply-retry')
    def reply_retry(identifier: str, session: Session = Depends(require_admin_write)):
        return execute(lambda: cloud_call(lambda: workflow.retry(identifier,team_token(session))))

    @router.post('/api/admin/knowledge/cloud-feedback/{identifier}/reply')
    def cloud_reply(identifier: str, body: CloudReply, _session: Session = Depends(require_admin_write)):
        return cloud_call(lambda: cloud.reply(identifier, body.status, body.processing_note, body.expected_revision,
                                              _session.cloud_feedback_token))

    @router.post("/api/knowledge/feedback/{identifier}/withdraw")
    def withdraw(identifier: str, body: FeedbackWithdrawal):
        return call("withdraw", identifier, owner_token=body.owner_token)

    @router.get("/api/admin/knowledge/feedback")
    def queue(_session: Session = Depends(require_admin)):
        if cloud.enabled and (cloud.admin or (_session.cloud_feedback_token and _session.cloud_feedback_expires>time.time())):
            return execute(lambda: cloud_call(workflow.queue))
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
        if identifier.startswith('cloud:'):
            return execute(lambda: cloud_call(lambda: workflow.resolve(identifier,body.model_dump(),session.username,team_token(session))))
        values=body.model_dump(exclude={'cloud_revision'})
        return call("resolve", identifier, reviewer=session.username, **values)

    @router.post("/api/admin/knowledge/feedback/{identifier}/reopen")
    def reopen(identifier: str, body: FeedbackReopen,
               session: Session = Depends(require_admin_write)):
        if identifier.startswith('cloud:'):
            return execute(lambda: cloud_call(lambda: workflow.reopen(identifier,body.model_dump(),session.username,team_token(session))))
        return call("reopen", identifier, revision=body.revision, reviewer=session.username)

    return router
