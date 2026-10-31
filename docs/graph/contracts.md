# 全项目接口边界 v1 与 C 实现

本文件固定 C 的交付接口，并记录 A/B/D 交互目标；不代表队友已评审签字。对接应经 PR 确认，不修改他人现有接口。参考分支：A `58bbbf0`、B `a32c92a`、D `3e6eaee`。D 当前网关仍读取 A 和 B 快照，尚未改为 C；不能宣称全组端到端集成完成。

## 统一约定

基础路径 `/api`，JSON UTF-8；参数中业务 id 按 URL 编码，允许冒号及完整来源 URL。所有研究响应返回 batch_id；下游再传该值。返回 200 为成功（创建异步任务由负责方约定 202），分页 page 从 1 开始，page_size 默认 20、最大 100；结果稳定排序，空列表 items=[]、total=0。原型尚无数据时 404 PUBLISHED_BATCH_NOT_FOUND。

业务错误：`{"error":{"code":"ENTITY_NOT_FOUND","message":"当前批次中不存在该实体"}}`。结构/参数校验错误是 FastAPI 标准 422 `detail` 数组；401 管理员服务凭据缺失/错误；404 无批次/实体；409 批次不可变、发布指针冲突、夹具未允许、计数校验失败；503 数据库不可用或管理凭据未配置。数据库内部错误脱敏，不向用户返回凭据或 Cypher。

## 本周可调用接口

| HTTP / 路径 | 参数 / 请求 | 结果 |
|---|---|---|
| GET /health | 无 | status/storage/contract_version，真实数据库探活 |
| GET /research/papers | q,topic,method,year,author,institution,task,dataset,venue,batch_id,page,page_size,sort | items,total,page,page_size,batch_id |
| GET /research/papers/{id} | batch_id | node,related,relations,truncated,batch_id；仅 paper |
| GET /research/entities | q,kind,batch_id,limit=30 | items,truncated,batch_id；图谱起点定位 |
| GET /research/entities/{id} | batch_id | 通用节点详情及证据邻居 |
| GET /research/graph | seed 必填，hops=1/2，limit=1..200，types 可重复，以上论文筛选与 batch_id | nodes,edges,truncated,limit_unit,seed,hops,batch_id |
| GET /research/authors/{id} | batch_id | 本周画像骨架：作者节点及有证据邻居 |
| GET /research/institutions/{id} | batch_id | 本周画像骨架：机构节点及有证据邻居 |
| POST /admin/graph/batches | BatchInput；Bearer | 批次元数据与 replay |
| GET /admin/batches/{id} | Bearer | checks,publishable,active_batch_id，批次元数据 |
| POST /admin/batches/{id}/publish | expected_active_batch_id 必填，可为 null；allow_developer_fixture 默认 false；Bearer | batch_id,previous_batch_id,status |

topic/method/其他实体筛选采用**精确 name 或 id**；维度之间 AND。q 对论文标题不区分大小写包含匹配。年份精确，venue 从已确认关系查询。sort 为 year_desc（默认）、year_asc、title，均有 id 打破平局。direction 未额外创建实体，由 B topic 词表编码。

图谱 limit 单位为路径，最多 200 路径，可产生最多 401 节点/400 边，响应带真实 truncated。关系 types 是 kind 允许列表。所有经过的论文都遵循筛选；不满足条件的起点只返回孤立节点，不泄漏关系。图谱按返回的 id 关联 source/target，不使用标题关联。详情关联上限 200，超出时 truncated=true。下钻前携带 batch_id。

示例：

```http
GET /api/research/papers?topic=Object%20Detection&method=YOLO&year=2024&page_size=20
```

```json
{"items":[{"id":"paper:W4402754006","kind":"paper","title":"DETRs Beat YOLOs on Real-time Object Detection","year":2024}],"total":2,"page":1,"page_size":20,"batch_id":"demo-c-week1"}
```

上面 items 是字段节选；完整字段含 name/label/type/source_id/source_url/abstract/updated_at/missing_fields/batch_id，以 `openapi.graph.json` 和运行响应为准。节点详情的 node 为同一结构；related 是邻居节点数组；relations 含 id/kind/type/source/target/status/batch_id/evidence/paper_ids。evidence 为数组，UI 必须展示实际 field/quote/locator/reviewer/source_url，不能把证据概括成“已证实采用”。

## Service / Repository / 组件

- ResearchQueryService → GraphRepository.papers / detail，保持 read transaction 内的批次一致性。
- GraphExploreService → GraphRepository.entities / graph，1—2 跳、类型和论文筛选。
- ProfileQueryService → detail(expected_kind=author/institution) 骨架；完整统计与共同署名分析待后续。
- BatchPublishService → ingest / batch / publish，统一管理员边界和原子发布。

本周业务方法由 Repository 封装，API 只做校验和权限。后续如拆分 service，保持方法和响应契约不变，不增加空壳类。

独立详情组件位于 `src/graph_query/paper-detail.js`，导出 `mountPaperDetail(container, response, onNavigate)`；输入为详情响应、回调参数为实体 id。D 的适配层负责传递 batch_id 和处理 loading/error，组件负责缺失字段、摘要、邻居和逐条证据。独立演示页提供检索、空状态、1/2 跳、节点点击及选中节点高亮；不改 D 的路由或样式。

D 的 Paper/GraphData 目前以 A 数字 ID、Paper/Venue 元数据图为前提，不能直接切换 base URL。需新增 C gateway：将 node.title/name、related 作者／主题等映射到 D 展示字段，保留数组证据；图节点 type 为首字母大写，关系为 B kind。D 的 ResearchGateway 已有批次参数，应全部传递。详情回包为 `{node,...}`，与 A 平铺回包不同。

## 全项目后续边界（本次不实现）

以下是对接目标，不是已可调用接口，也不覆盖队友当前 API。字段新增或路径调整须版本化并经负责成员 Review。NAV01/02/04/05 的页面由 D 持有，查询由 C 提供；NAV03 的 C 组件嵌入 D 路由。

| NAV / 负责方 | API 目标 | 最小输入 | 最小输出 / 约束 |
|---|---|---|---|
| 06/07 D | POST /research/exports；GET /research/exports/{id} | filters,batch_id,format=csv | export_id,status,created_at；成功 download_url，失败 error；仅论文元数据 |
| 08/09 D | GET /research/trends | topic/method,year_from,year_to,batch_id,metric=count/share | series[{id,points[{year,count,share}]}],batch_id；下钻回传同批筛选 |
| 10/11 C 后续 | GET /research/authors/{id}、/institutions/{id} 升级 | batch_id,page,page_size | 保留当前 node/related/relations；新增 papers/topics/coauthors 与论文证据，禁止凭姓名推机构 |
| 12 A | GET/PATCH /admin/sources/{id} | enabled,venue,years,page_size,retries | 来源配置及 credentials_configured，不回传凭据 |
| 13/14/15 A | POST /admin/jobs；GET /admin/jobs/{id}；POST /admin/jobs/{id}/retry | source_id,venue,year,idempotency_key；失败阶段/批次 | job_id,status,stage,processed,success,failed,updated_at,redacted_errors；重复运行任务不得并发 |
| 16/17 B | GET /admin/reviews；GET/PATCH /admin/reviews/{id} | type,job_id,status,page；action,reason,expected_version | evidence,before,after,reviewer,updated_at,version；候选与确认知识隔离 |
| 18/19 C | 当前 batch/check/publish，后续增加报告质量门槛 | evaluation_report_ref,coverage_report_ref,expected_active_batch_id | validation_results,publishable,reasons；失败保留旧发布 |
| 20 D | POST /admin/login；POST /admin/logout；GET /admin/session | username/password；会话 Cookie + CSRF | authenticated,role,expires_at；安全 Cookie，退出立即失效；代理 C 只在服务端加 token |

管理页面均先由 D 校验管理员身份；C 的管理 API 再校验仅服务端持有的 Bearer。尚未配置时 fail closed。C 不公开原始候选，不替 A 提交导入任务，不实现 D 会话。完整项目的 FR07/FR08/FR10/FR12 需各负责方补齐并共同冻结，本文不是它们已经实现的证明。
