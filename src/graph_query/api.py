"""Standalone C API. D's authenticated gateway can proxy the admin routes."""
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import FileResponse, JSONResponse
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from .models import BatchInput, PublishInput, RELATIONS, EntityKind
from .repository import GraphError, GraphRepository


def create_app(repository=None, admin_token=None):
    @asynccontextmanager
    async def lifespan(app):
        if repository is None:
            app.state.repo = GraphRepository(
                os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
                os.getenv("NEO4J_USER", "neo4j"),
                os.environ["NEO4J_PASSWORD"],
                os.getenv("NEO4J_DATABASE", "neo4j"),
            )
        else:
            app.state.repo = repository
        try:
            app.state.repo.initialize()
            yield
        finally:
            if repository is None:
                app.state.repo.close()

    app = FastAPI(title="CV Insight C Graph API", version="1.0.0", lifespan=lifespan)

    def repo():
        return app.state.repo

    def admin(authorization: Annotated[str | None, Header()] = None):
        token = (
            admin_token if admin_token is not None else os.getenv("GRAPH_ADMIN_TOKEN")
        )
        if not token:
            raise GraphError(503, "ADMIN_NOT_CONFIGURED", "管理接口未配置服务凭据")
        supplied = (
            authorization.removeprefix("Bearer ")
            if authorization and authorization.startswith("Bearer ")
            else ""
        )
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise GraphError(401, "ADMIN_REQUIRED", "需要管理员服务凭据")

    @app.exception_handler(GraphError)
    async def graph_error(request, error):
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
        )

    async def database_error(request, error):
        return JSONResponse(
            status_code=503,
            content={
                "error": {"code": "GRAPH_UNAVAILABLE", "message": "图数据库暂不可用，请稍后重试"}
            },
        )

    for kind in (Neo4jError, ServiceUnavailable, SessionExpired):
        app.add_exception_handler(kind, database_error)

    @app.get("/api/health")
    def health(r=Depends(repo)):
        r.run(lambda tx: tx.run("RETURN 1").consume())
        return {"status": "ok", "storage": "neo4j", "contract_version": "c-graph/1.0"}

    def filters(
        q: str | None = Query(None, max_length=200),
        topic: str | None = Query(None, max_length=500),
        method: str | None = Query(None, max_length=500),
        year: int | None = Query(None, ge=1900, le=2100),
        author: str | None = Query(None, max_length=500),
        institution: str | None = Query(None, max_length=500),
        task: str | None = Query(None, max_length=500),
        dataset: str | None = Query(None, max_length=500),
        venue: str | None = Query(None, max_length=500),
    ):
        return {k: v for k, v in locals().items() if v is not None and v != ""}

    @app.get("/api/research/papers")
    def papers(
        f=Depends(filters),
        batch_id: str | None = None,
        page: int = Query(1, ge=1, le=100000),
        page_size: int = Query(20, ge=1, le=100),
        sort: Literal["year_desc", "year_asc", "title"] = "year_desc",
        r=Depends(repo),
    ):
        return r.papers(f, batch_id, page, page_size, sort)

    @app.get("/api/research/papers/{paper_id:path}")
    def detail(paper_id: str, batch_id: str | None = None, r=Depends(repo)):
        return r.detail(paper_id, batch_id, "paper")

    @app.get("/api/research/entities")
    def entity_search(
        q: str = Query("", max_length=200),
        kind: EntityKind | None = None,
        batch_id: str | None = None,
        limit: int = Query(30, ge=1, le=100),
        r=Depends(repo),
    ):
        return r.entities(q, kind, batch_id, limit)

    @app.get("/api/research/entities/{entity_id:path}")
    def entity(entity_id: str, batch_id: str | None = None, r=Depends(repo)):
        return r.detail(entity_id, batch_id)

    @app.get("/api/research/graph")
    def graph(
        seed: str = Query(..., min_length=1, max_length=500),
        hops: int = Query(1, ge=1, le=2),
        limit: int = Query(100, ge=1, le=200),
        batch_id: str | None = None,
        types: Annotated[list[str] | None, Query()] = None,
        f=Depends(filters),
        r=Depends(repo),
    ):
        if types and not set(types) <= RELATIONS.keys():
            raise GraphError(422, "INVALID_RELATION_TYPE", "关系类型不在 Schema 中")
        return r.graph(seed, hops, batch_id, limit, types, f)

    @app.get("/api/research/authors/{entity_id:path}")
    def author(entity_id: str, batch_id: str | None = None, r=Depends(repo)):
        # Week-one profile skeleton: evidenced neighbours only, no inferred affiliation.
        return r.detail(entity_id, batch_id, "author")

    @app.get("/api/research/institutions/{entity_id:path}")
    def institution(entity_id: str, batch_id: str | None = None, r=Depends(repo)):
        return r.detail(entity_id, batch_id, "institution")

    @app.post("/api/admin/graph/batches", dependencies=[Depends(admin)])
    def ingest(body: BatchInput, r=Depends(repo)):
        return r.ingest(body)

    @app.get("/api/admin/batches/{batch_id}", dependencies=[Depends(admin)])
    def batch(batch_id: str, r=Depends(repo)):
        return r.batch(batch_id)

    @app.post("/api/admin/batches/{batch_id}/publish", dependencies=[Depends(admin)])
    def publish(batch_id: str, body: PublishInput, r=Depends(repo)):
        return r.publish(
            batch_id, body.expected_active_batch_id, body.allow_developer_fixture
        )

    @app.get("/research/papers/{paper_id:path}", include_in_schema=False)
    @app.get("/research", include_in_schema=False)
    def preview(paper_id: str = ""):
        return FileResponse(Path(__file__).with_name("detail.html"))

    @app.get("/assets/c-paper-detail.js", include_in_schema=False)
    def component():
        return FileResponse(
            Path(__file__).with_name("paper-detail.js"), media_type="text/javascript"
        )

    return app


app = create_app()
