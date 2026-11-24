# Week 2 · C 作者画像、研究统计与接入边界

本轮只修改 C 模块、C 测试和说明，没有执行 Git 命令，没有修改 B/D 源码或进行跨模块合并。

## 差距评估与实现

Week 1 的不可变快照、发布 CAS、证据校验、检索、详情和 1—2 跳查询继续复用。新增 `analytics.py`，通过现有 Repository 的同一读事务解析并固定批次，完成作者画像与研究分布。原 `/authors/{id}` 邻居接口保持兼容；新增画像接口，避免破坏 D 已有消费结构。

独立页面 `/research/analytics` 提供指定批次统计、按姓名/ID 搜索作者、选择同名作者、作者论文分页、主题/方法和年份下钻、论文详情以及两跳子图节点列表。正式可视图谱仍可使用原 `/research` 页面。页面不会自动创建、导入或发布批次。

## D 可调用接口

基础 URL 为 C 服务地址（建议独立端口 8002）。以下均为 GET，无管理员凭据，**batch_id 必填且必须已经发布**。

| 路径 | 参数 | 返回 |
| --- | --- | --- |
| `/api/research/statistics` | batch_id；原论文筛选 q/topic/method/year/author/institution/task/dataset/venue；新增精确 author_id；limit 默认 30，1—100 | batch_id/provenance/schema_version/vocabulary_version/source_batch_id/filters/paper_count/years/distributions/basis |
| `/api/research/author-profiles/{id}` | URL 编码稳定作者 ID；batch_id；page 默认 1；page_size 默认 20，1—100；limit 默认 30，1—100 | author、papers、statistics、institutions、institution_status、identity、batch_id |

论文接口新增 author_id 精确筛选，可供作者统计下钻；原 author 参数继续支持名称或 ID。查找作者沿用 `/api/research/entities?kind=author&q=姓名&batch_id=...`。不同 ID 即使姓名相同也分别显示，不以姓名合并；画像不接受作者名称代替 ID。

请求示例（ID 请从真实批次的实体查询获得）：

```http
GET /api/research/statistics?batch_id=demo-c-week1&year=2024
GET /api/research/entities?kind=author&q=Cheng&batch_id=demo-c-week1
GET /api/research/author-profiles/author%3A实际ID?batch_id=demo-c-week1&page=1&page_size=20
GET /api/research/papers?batch_id=demo-c-week1&author_id=author%3A实际ID&topic=topic%3A实际ID
GET /api/research/graph?batch_id=demo-c-week1&seed=paper%3A实际ID&hops=2
```

statistics 返回结构示例（数值仅解释格式，不作为某批次验收结果）：

```json
{
  "batch_id": "reviewed-example",
  "provenance": "reviewed_export",
  "schema_version": "b-knowledge/0.1-draft",
  "vocabulary_version": "example",
  "source_batch_id": "A-example",
  "filters": {},
  "paper_count": 2,
  "years": [{"year": 2024, "paper_count": 2}],
  "distributions": {
    "topic": {"items": [{"id": "topic:x", "name": "示例主题", "paper_count": 1, "share": 0.5}], "truncated": false, "papers_with_confirmed_relation": 1, "papers_without_confirmed_relation": 1},
    "method": {"items": [], "truncated": false, "papers_with_confirmed_relation": 0, "papers_without_confirmed_relation": 2}
  },
  "basis": {"unit": "distinct_papers", "denominator": "all_matching_papers_in_published_batch", "relations": "confirmed_only", "multi_label": true, "fixture": false, "notice": "运行响应包含中文口径说明"}
}
```

画像 papers 为 items/total/page/page_size；statistics 是**作者全部关联论文**的统计，不受论文分页影响。institutions 的每项包含 id/name/paper_ids，只计具有同篇论文隶属证据的机构；为空时 institution_status=not_confirmed，不虚构任职。identity 含 stable_entity_id、same_name_other_ids、merged_by_name=false。

口径：每个分组 count(DISTINCT paper)，不按重复证据、关系路径或作者数量累计；share 分母是当前筛选命中的全部论文。多标签占比总和可超过 100%。无确认关联单独计数，不能解读为没有此研究内容。limit 仅截断主题/方法列表，truncated 明确告知；覆盖数仍是全量。年份按来源元数据，统计不等于影响力或学术贡献评价。演示夹具返回 provenance=developer_fixture、basis.fixture=true，页面醒目标注。

错误：缺少 batch_id、非法分页/年份/limit 返回 422；未发布/不存在的批次返回 404 PUBLISHED_BATCH_NOT_FOUND；不存在或类型不是作者返回 404 AUTHOR_NOT_FOUND；数据库异常 503 GRAPH_UNAVAILABLE。沿用 `{error:{code,message}}`；FastAPI 参数校验为标准 detail 数组。完整路由参数见 `openapi.week2.json` 或运行服务 `/docs`。

## B 最新机制核查：公共同步尚未接通

核查目录：用户提供的 `CV-insight-kg-knowledge-builder-v2`；操作指南 003，日期 2026-11-07。

实际代码的三条链路：

1. `server/application/knowledge.py` 的 KnowledgeSnapshot.download 调用 build_exports，导出 ReviewSession 中 confirmed/pending/rejected。
2. `server/application/graph_batches.py` 的 prepare_graph_batch 仍只读取上述 sessions，然后调用 C 的旧 adapt_confirmed。
3. `src/knowledge_builder/feedback.py` 的 KnowledgeFeedback._material 独立重新抽取，应用反馈 decisions（rename/exclude）、terms、撤回，生成公共阅读视图；该视图没有逐条正式审核状态/确认事件。个人调整由前端存储管理，不在此正式导出中。

因此旧 confirmed 导出**不包含所有公共反馈改动**，公共 view 也**不能整体冒充 confirmed**。本轮没有改写 B、不把公共阅读候选批量自动确认、不伪造反馈同步成功。现有 confirmed 导出仍可走旧适配器，但那不代表最新公共反馈已进入 Neo4j。

B 需要提供一个版本化的、原子固定的**完整正式快照导出**，至少包含：

- 输入数据范围/完整论文清单及原始元数据、source_batch_id、schema/vocabulary 版本、snapshot_revision、public_revision（反馈版本）、各论文输入指纹；多篇读取必须固定同一公共修订，不能逐篇取可变 view 拼接。
- 逐条实体/关系的稳定 ID、有效内容、审核状态、显式确认事件、证据、管理员改名/排除/补词操作及撤回后的最终有效状态。程序重新识别不自动视作真人已确认，需明确其审批范围和规则依据。
- 全量快照/范围完整标志及清单校验值；撤回全部确认后也需带完整论文范围，明确“空关系是正式撤回结果”，避免空文件被误作丢失数据。个人改名/隐藏/补充必须排除。
- 全局公共改名若对同一稳定实体在不同论文产生不同名称，B 应定义统一名称或论文局部覆盖结构；C 旧适配器会拒绝冲突，不采用最后一条覆盖。

收到该契约后，C 可将最终正式快照导入**新批次**，校验后显式发布。移除用新快照缺少该关系表达；撤回处理用下一快照恢复有效记录。相同 batch_id+内容幂等，内容变更必须新 batch_id；完整快照取代补丁应用，避免重复导入或撤回重放造成累积。导入/发布失败保留旧版本。旧已发布快照仍可按批次读取，撤回只改变新发布版本，不会就地修改历史；D 刷新最新批次后更新三视图。

## 启动与演示

保留用户当前 Docker 实例和数据。按现有方式向进程配置 NEO4J_URI/USER/PASSWORD/DATABASE；不要在文档或日志打印密码。现有 `.venv` 可直接使用：

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.graph_query.api:app --host 127.0.0.1 --port 8002
```

1. 打开 `http://127.0.0.1:8002/research/analytics`，输入实际已发布批次号，读取统计。
2. 搜索作者名称，按显示的稳定 ID 选择作者；看论文总数、年份、主题、方法、机构缺失提示。
3. 点主题/方法/年份查看相同 batch_id 与 author_id 的论文；点标题进入详情，点“关联图谱”查看两跳节点列表；原图谱可从 `/research` 页面查看。
4. `demo-c-week1` 是现有演示夹具，会明确标注；要展示正式知识必须由真实审核导出生成 reviewed_export 批次，不能给它换个标识冒充正式数据。

## 验证方式

本轮新增真实 Neo4j 测试包含：未发布批次拒绝统计、去重证据、多标签截断、空结果、画像分页、同名区分、错误实体类型、API 参数边界、新快照移除与恢复及旧版本固定读取。移除/恢复测试是 C 快照机制验证，不是 B 反馈同步验收。

```powershell
# 只使用可丢弃的专用测试实例！旧测试会切换该实例的 registry。
$env:GRAPH_TEST_URI='bolt://127.0.0.1:17689'
$env:GRAPH_TEST_PASSWORD='专用测试库密码'
.\.venv\Scripts\python.exe -m pytest tests/graph -q -p no:cacheprovider
```

保留原 CI 专用 Neo4j service 配置，测试自动发现 Week 2 新测试。**不要把 GRAPH_TEST_URI 指向用户当前生产/演示持久化库**。Harness 可通过 JVM 参数 `-Dgraph.test.port=17689` 指定独立端口，默认端口兼容 Week 1。

整合由 D 负责：消费新接口、显示 provenance 和统计口径、保留 ID 与 batch_id、分页及下钻条件；C 未修改统一导航或工作台。

本轮实际结果：35 项测试通过（26 项契约/API、9 项真实 Neo4j 集成），耗时 29.65 秒，1 条已有 Starlette/httpx 弃用提示。Docker 管道在当前执行环境拒绝访问，改用隔离的官方 Neo4j Harness 5.26.0；测试结束后该实例已停止。独立页面已通过 HTTP 返回与 JavaScript 语法检查，本轮未进行浏览器手工点击验收。详情记录见 week2-verification.json。
