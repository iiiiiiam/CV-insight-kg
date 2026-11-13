"""Small admin-only JSON handoff API; no A database or C graph mutations."""
from typing import Any
import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.application.knowledge_batches import batch_registry, batch_sources
from server.domain.auth import Session, require_admin, require_admin_write
from src.knowledge_builder.batches import BatchConflict, BatchStoreInvalid, _snapshot
from src.knowledge_builder.batch_sources import BatchSourcesInvalid
from src.knowledge_builder.models import PaperInput


class BatchImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    document: dict[str, Any]
    acknowledge_switch: bool = False


class BatchWithdrawal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


def batch_router(settings):
    router = APIRouter(prefix="/api/admin/knowledge/batches")
    job_lock = threading.Lock()
    job = dict(running=False, error=None)

    def prepare_sources():
        try:
            while True:
                registry = batch_registry(settings)
                snapshot = registry.snapshot()
                batch_sources(settings).prepare([PaperInput(**p["input"]) for p in snapshot["papers"]])
                with job_lock:
                    # Catch a batch arriving while the previous snapshot was processed.
                    if registry.snapshot()["revision"] == snapshot["revision"]:
                        job["running"] = False
                        return
        except Exception:
            logging.getLogger(__name__).exception("B batch source preparation stopped")
            with job_lock:
                job.update(running=False, error="来源补充中断，已有结果保留，可重新尝试补充")

    def schedule(tasks):
        with job_lock:
            if job["running"]:
                return
            job.update(running=True, error=None)
            tasks.add_task(prepare_sources)

    def call(operation):
        try:
            return operation(batch_registry(settings))
        except BatchConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (BatchStoreInvalid, BatchSourcesInvalid, OSError) as exc:
            raise HTTPException(503, "批次存档暂不可用，原记录保留，请检查后重试") from exc
        except LookupError as exc:
            raise HTTPException(404, "未找到该批次") from exc

    @router.get("")
    def status(_session: Session = Depends(require_admin)):
        def read(registry):
            state = registry.read()
            snapshot = _snapshot(state)
            papers = [PaperInput(**p["input"]) for p in snapshot["papers"]]
            return dict(revision=state["revision"], managed=bool(state["batches"]),
                paper_count=snapshot["paper_count"], snapshot_revision=snapshot["revision"],
                source_enrichment={**batch_sources(settings).summary(papers), **job},
                batches=[dict(batch_code=b["batch_code"], active=b["active"],
                    paper_count=len(b["papers"]), receipt=b["receipt"]) for b in reversed(state["batches"])],
                failures=[e for e in reversed(state["events"]) if e["action"] == "ingest_failed"][:10])
        return call(read)

    @router.post("")
    def ingest(body: BatchImport, tasks: BackgroundTasks, _session: Session = Depends(require_admin_write)):
        if not body.acknowledge_switch:
            raise HTTPException(422, "请先确认导入将影响当前 B 知识和有效结果导出")
        result = call(lambda registry: registry.ingest(body.document, expected_revision=body.revision))
        if result["status"] in {"accepted", "unchanged"}:
            schedule(tasks)
        return result

    @router.post("/enrich")
    def enrich(tasks: BackgroundTasks, _session: Session = Depends(require_admin_write)):
        call(lambda registry: registry.read())
        schedule(tasks)
        return dict(status="scheduled")

    @router.post("/{batch_code}/withdraw")
    def withdraw(batch_code: str, body: BatchWithdrawal, _session: Session = Depends(require_admin_write)):
        return call(lambda registry: registry.withdraw(batch_code, expected_revision=body.revision))

    return router
