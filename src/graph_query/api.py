"""Standalone C API. D's authenticated gateway can proxy the admin routes."""

import hmac

import os

from contextlib import asynccontextmanager

from pathlib import Path

from typing import Annotated, Literal



from fastapi import Depends, FastAPI, Header, Query

from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

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



    def stage(request, code=None):
        if code == 'INVALID_EFFECTIVE_SNAPSHOT':
            return 'validate'
        if code == 'QUALITY_CHECK_FAILED':
            return 'integrity_check'
        if code == 'ACTIVE_BATCH_CHANGED':
            return 'compare_and_swap'
        if request.url.path.endswith('/publish'):
            return 'publish'
        if request.url.path.endswith('/effective'):
            return 'import'
        return 'read'

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(status_code=422, content={
            'detail': jsonable_encoder(error.errors()),
            'error': {'code':'INVALID_REQUEST','message':'请求参数或 JSON 格式不合法',
                      'stage':'request_validation','retryable':False}})

    @app.exception_handler(GraphError)

    async def graph_error(request, error):

        return JSONResponse(

            status_code=error.status,

            content={"error": {"code": error.code, "message": error.message,
                               "stage":stage(request,error.code),"retryable":False}},

        )



    async def database_error(request, error):

        return JSONResponse(

            status_code=503,

            content={

                "error": {"code": "GRAPH_UNAVAILABLE", "message": "图数据库暂不可用，请查询发布状态后重试",
                          "stage":stage(request),"retryable":isinstance(error,(ServiceUnavailable,SessionExpired)) or error.is_retryable(),
                          "publication_outcome_unknown":request.url.path.endswith('/publish')}

            },

        )



    for kind in (Neo4jError, ServiceUnavailable, SessionExpired):

        app.add_exception_handler(kind, database_error)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse(status_code=500, content={'error':{
            'code':'GRAPH_INTERNAL_ERROR','message':'图服务执行异常，请检查服务日志并核对活动版本',
            'stage':stage(request),'retryable':False,
            'publication_outcome_unknown':request.url.path.endswith('/publish')}})



    @app.get("/api/health")

    def health(r=Depends(repo)):

        r.run(lambda tx: tx.run("RETURN 1").consume())

        return {"status": "ok", "storage": "neo4j", "contract_version": "c-graph/1.0", "implementation_revision":"c-effective-graph-v4"}



    def filters(
        q: str | None=Query(None,max_length=200),
        topic: Annotated[list[str] | None,Query(max_length=50)]=None,
        method: Annotated[list[str] | None,Query(max_length=50)]=None,
        author: Annotated[list[str] | None,Query(max_length=50)]=None,
        author_id: Annotated[list[str] | None,Query(max_length=50)]=None,
        institution: Annotated[list[str] | None,Query(max_length=50)]=None,
        task: Annotated[list[str] | None,Query(max_length=50)]=None,
        dataset: Annotated[list[str] | None,Query(max_length=50)]=None,
        venue: Annotated[list[str] | None,Query(max_length=50)]=None,
        direction: Annotated[list[str] | None,Query(max_length=50)]=None,
        year: Annotated[list[int] | None,Query()]=None,
    ):
        values=locals().copy()
        if year and (len(year)>50 or any(y<1900 or y>2100 for y in year)):raise GraphError(422,'INVALID_YEAR','年份应在1900到2100之间，最多50项')
        if any(isinstance(v,list) and any(isinstance(x,str) and len(x)>500 for x in v) for v in values.values()):raise GraphError(422,'INVALID_FILTER','筛选值过长')
        return {k:v for k,v in values.items() if v is not None and v!='' and v!=[]}

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



    @app.get("/api/research/statistics")

    def statistics(

        batch_id: str = Query(..., min_length=1, max_length=80),

        limit: int = Query(30, ge=1, le=100),

        f=Depends(filters),

        r=Depends(repo),

    ):

        return r.statistics(f, batch_id, limit)



    @app.get("/api/research/author-profiles/{entity_id:path}")

    def author_profile(

        entity_id: str,

        batch_id: str = Query(..., min_length=1, max_length=80),

        page: int = Query(1, ge=1, le=100000),

        page_size: int = Query(20, ge=1, le=100),

        limit: int = Query(30, ge=1, le=100),

        r=Depends(repo),

    ):

        return r.author_profile(entity_id, batch_id, page, page_size, limit)



    @app.get('/api/research/coauthors')
    def coauthors(anchor_id: str=Query(...,min_length=1,max_length=500),
                  batch_id: str=Query(...,min_length=1,max_length=80),
                  page: int=Query(1,ge=1,le=100000), page_size: int=Query(20,ge=1,le=100),
                  shared_paper_limit: int=Query(10,ge=1,le=100), f=Depends(filters), r=Depends(repo)):
        return r.partners(anchor_id,batch_id,'author',f,page,page_size,shared_paper_limit)

    @app.get('/api/research/institution-collaborations')
    def institution_collaborations(institution_id: str=Query(...,min_length=1,max_length=500),
                  batch_id: str=Query(...,min_length=1,max_length=80),
                  page: int=Query(1,ge=1,le=100000), page_size: int=Query(20,ge=1,le=100),
                  shared_paper_limit: int=Query(10,ge=1,le=100), f=Depends(filters), r=Depends(repo)):
        return r.partners(institution_id,batch_id,'institution',f,page,page_size,shared_paper_limit)

    @app.get('/api/research/report-statistics')
    def report_statistics(batch_id: str=Query(...,min_length=1,max_length=80),
                          expected_revision: str | None=Query(None,pattern='^[0-9a-f]{64}$'),
                          limit: int=Query(30,ge=1,le=100),
                          coauthor_id: str | None=Query(None,min_length=1,max_length=500),
                          institution_id: str | None=Query(None,min_length=1,max_length=500),
                          f=Depends(filters),r=Depends(repo)):
        return r.report_statistics(batch_id,expected_revision,f,limit,coauthor_id,institution_id)

    @app.get('/api/admin/graph/publication-status',dependencies=[Depends(admin)])
    def publication_status(page: int=Query(1,ge=1,le=100000),
                           page_size: int=Query(20,ge=1,le=100), r=Depends(repo)):
        return r.publication_status(page,page_size)

    @app.get("/research/analytics", include_in_schema=False)

    def analytics_preview():

        return FileResponse(Path(__file__).with_name("analytics.html"))



    @app.get("/api/research/institutions/{entity_id:path}")

    def institution(entity_id: str, batch_id: str | None = None, r=Depends(repo)):

        return r.detail(entity_id, batch_id, "institution")



    @app.post("/api/admin/graph/batches", dependencies=[Depends(admin)])

    def ingest(body: BatchInput, r=Depends(repo)):

        return r.ingest(body)

    @app.post('/api/admin/graph/effective',dependencies=[Depends(admin)])
    def ingest_effective(body: dict,r=Depends(repo)):
        try:
            return r.ingest_effective(body)
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            raise GraphError(422,'INVALID_EFFECTIVE_SNAPSHOT','有效知识快照结构、证据、计数或版本校验失败') from exc



    @app.get("/api/admin/batches/{batch_id}", dependencies=[Depends(admin)])

    def batch(batch_id: str, r=Depends(repo)):

        return r.batch(batch_id)



    @app.post("/api/admin/batches/{batch_id}/publish", dependencies=[Depends(admin)])

    def publish(batch_id: str, body: PublishInput, r=Depends(repo)):

        return r.publish(

            batch_id, body.expected_active_batch_id, body.allow_developer_fixture,
            expected_generation=body.expected_publish_generation

        )



    @app.get("/research/papers/{paper_id:path}", include_in_schema=False)

    @app.get("/research", include_in_schema=False)

    def preview(paper_id: str = ""):

        return FileResponse(Path(__file__).with_name("detail.html"))



    @app.get('/assets/c-graph-view.js',include_in_schema=False)
    def graph_component():
        return FileResponse(Path(__file__).with_name('graph-view.js'),media_type='text/javascript')

    @app.get('/api/research/diagnostics')
    def diagnostics(batch_id: str=Query(...,min_length=1,max_length=80),r=Depends(repo)):
        def operation(tx):
            batch=r.resolve(tx,batch_id)
            counts=[dict(x) for x in tx.run("MATCH (:CVEntity {batch_id:$b})-[r:CV_LINK]->(:CVEntity {batch_id:$b}) RETURN r.kind AS kind,r.status AS status,count(r) AS count ORDER BY kind,status",b=batch)]
            return {'batch_id':batch,'relations':counts,'implementation_revision':'c-effective-graph-v3'}
        return r.run(operation)

    @app.get("/assets/c-paper-detail.js", include_in_schema=False)

    def component():

        return FileResponse(

            Path(__file__).with_name("paper-detail.js"), media_type="text/javascript"

        )



    return app





app = create_app()
