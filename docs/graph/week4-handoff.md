# Week 4 · C 统计、报告与发布交接

## 范围与需求差距

基于 Week 3 原实现扩展，保留 confirmed、effective、FR01/FR02、画像、研究子方向、一跳/两跳图谱。只修改 C、C 测试与文档；没有执行 Git 操作，没有连接或变更 Docker 中现有150篇的数据库、发布指针和数据卷。

已核对 A 当前 `docs/week4-a.md`、报告网关与 `app/report_bundle.py`，B `knowledge-week4` 的 `team_handoff.md`、effective、作者标签、报告知识及批次实现。参考目录也带有整合版 D 的 `server/api/main.py`：D 已有同步锁、轮询、effective 导入、完整性检查及 CAS 发布。本轮不新增同步后台，不修改这些参考文件。

原有能力：去重论文统计、主题/方法及来源研究子方向分布、固定已发布批次、完整快照校验与原子发布。新增能力：任务/数据集/会议分布、作者与机构汇总、分页共同作者及机构共现、固定版本报告包、发布历史状态与可选发布代数、失败阶段诊断。

**双序列趋势待需求确认，不计入完成验收。** 用户已明确暂不定义两条业务序列、时间粒度或快照口径。未增加双序列公开 API，未把导入事件当论文趋势。现有 `statistics.years` 继续按一个发布快照中论文的来源年份、稳定论文 ID 去重聚合；新增内部 `annual.annual_axis` 接收此聚合结果，支持年份补零、范围边界与缺失年份分开记录，不与任何业务序列绑定，也没有改变原有 years 输出。待组长确认两序列、粒度、横轴及版本口径后再开发。

## 共同作者与机构共现

```http
GET /api/research/coauthors?batch_id=effective-REV&anchor_id=author:稳定ID&page=1&page_size=20&shared_paper_limit=10
GET /api/research/institution-collaborations?batch_id=effective-REV&institution_id=institution:稳定ID&page=1&page_size=20
```

ID 按 URL 编码。两接口支持原有 FR01 多值筛选；筛选限制论文范围，批次必填。`anchor_id` 指共同作者查询的中心作者，不与 FR01 `author_id` 筛选参数混用。必须使用 C 实体稳定 ID，不能仅传同名显示名称。

返回 `batch_id/revision/anchor/items/total/page/page_size/truncated/shared_paper_limit/filters/basis`。

* `anchor.paper_count`：中心实体在筛选范围内关联的去重论文数。
* `items[].id/source_id/name/identity_state/paper_count`：共同实体及共享论文数。按共享数降序、稳定实体 ID 升序排序；同名不同 ID 保留为不同记录。
* `shared_papers[]`：稳定 C 论文 ID、标题、年份、来源 ID、来源 URL 和 sources。每对实体仅按 distinct paper 计一次，多条署名/机构路径不放大计数。
* `shared_papers_truncated`：该对共享论文明细超出上限；不影响准确的 paper_count。明细默认10、最大100；共同实体分页默认20、最大100。超出末页 items=[]，total 仍正确。
* 作者 `identity_state=source_identified` 表示有来源 ID；`paper_local_unresolved` 表示 B 的局部未消歧身份；其他缺来源 ID 的旧节点标记 `entity_id_only`。不能把这些局部身份当成已消歧的自然人。

机构统计必须由“论文→真实作者→机构”且该机构边 evidence 的 `paper_ids` 含本论文推导。不会把同一作者另一篇论文的机构自动挪到本篇。机构共现要求双方机构各有本篇的真实署名机构证据，仅表示共同出现在一篇论文中，不声称合同合作或作者贡献。

实现只枚举一个指定中心的邻域，再读取一页共同实体的有限共享论文；不枚举整个图谱的作者两两组合。既有作者画像增加 `paper_count` 和 `coauthors_query`，原字段和口径不变。共同署名不表示导师关系、贡献程度或专长；B 作者知识标签仍由 B 提供。

## 报告接口与 A 输入契约

```http
GET /api/research/report-statistics?batch_id=effective-REV&expected_revision=REV&limit=30
```

`batch_id` 必填且必须已发布；`expected_revision` 可选，推荐报告请求必传，必须是 B effective 的64位知识 revision。不是 B `knowledge-report/1` 自身的附件 revision。`limit` 默认30最大100，限制分布/作者/机构榜单和共同实体列表，不限制准确总数；超过上限均有截断字段。`coauthor_id`、`institution_id` 可指定报告中的共同作者/机构共现中心；未指定时各选择当前筛选范围中论文数最多、稳定 ID 排序最前的实体，返回 `selection`，**这是一份中心邻域摘要，不是全局所有作者组合**。可从分页接口读取其他中心。

沿用 FR01 筛选（跨维 AND、同维多值 OR）；不传筛选即整个发布快照。注意 `author_id` 筛选整个报告的论文集，而 `coauthor_id` 仅选择共同作者摘要中心。完整报告请求固定一次 batch，所有 C 章节在同一次 read transaction 中产生，之后下钻必须继续传同一 batch。历史快照不累计到最新快照。

返回外层可直接作为 A 报告的一个 C section：

```json
{
  "provider": "C",
  "revision": "B effective knowledge revision",
  "paper_ids": ["https://openalex.org/W..."],
  "data": {
    "format_version": "c-report-statistics/1",
    "batch_id": "effective-REV",
    "revision": "REV",
    "statistics": {"batch_id": "effective-REV", "paper_count": 20},
    "years": [],
    "distributions": {},
    "authors": {},
    "institutions": {},
    "coauthors": {},
    "institution_collaborations": {},
    "trends": {"status": "definition_pending", "series": null},
    "scope": {},
    "times": {},
    "coverage": {},
    "pending_sections": ["dual_trends"]
  }
}
```

上例省略章节内容，不能作为业务输入。实际字段：

| 字段 | 含义 |
| --- | --- |
| statistics | 复用原 statistics 服务；同筛选、同 limit 返回完全一致的计数和分布 |
| distributions.topic/method/task/dataset | 真实 mentions 对应的 distinct paper 数、占比、截断及有/无关联的论文数；无关联不表示没有研究内容 |
| distributions.research_direction | 仅 B source_classification，绝不是 mentions_topic/task；含有/无来源分类论文数 |
| distributions.venue | 真实 published_in 来源会议，按稳定会议实体统计，不按显示名合并 |
| years | 来源发表年份的去重论文数，按年份升序；保持旧接口不补零的行为 |
| authors/institutions | items/total/limit/truncated、关联覆盖论文数、来源 ID 完整性；作者 total 是实体身份数，含明确标记的未消歧实体，不宣称真实人数 |
| scope | published_snapshot 或 filtered_published_snapshot、规范化筛选、distinct_papers、paper_count；historical_accumulation=false |
| times | B 首次保存的 knowledge_exported_at、graph_first_published_at、graph_last_activated_at、statistics_generated_at；source_updated_at=null，不能互相替代 |
| coverage.missing | 年份、摘要、来源链接、来源论文 ID、来源更新时间、引用次数的缺失论文数；当前 PaperInput 未提供后两项，所以缺失数等于论文数，不能填0引用 |
| basis/review_state_counts | 区分公共有效自动知识和人工处理；覆盖率不代表准确率，不提供编造的准确率 |

同一论文可属于多个分类，分类计数和占比之和可超过总论文数/100%。缺失字段用 null/明确缺失数量；合法空快照返回200、paper_ids=[]、paper_count=0、空榜单、零覆盖缺失数。没有指定已发布快照为404，不把格式错误视为空快照。

A 当前 `/api/admin/report-inputs/C` 仍调用旧 `/api/research/statistics` 并返回待补章节。**需 A/D 把这次固定 batch/revision 的调用改为 report-statistics 并直接转发整个 section**；C 没有改网关。A 现有生成器能保存 trends/distributions/authors/institutions/coauthors JSON，且会明确列出 dual_trends 未提供；机构共现目前嵌入 C section，若希望单独附件由 A/D 决定。C 不生成文件或任务。

A 会核对 section 的 paper_ids 与 A 冻结报告论文范围完全相同、数量及 batch/revision 相符。筛选后范围改变，A 的 scope.paper_ids 也应相应固定；不可把全部快照统计冒充某个子范围报告。旧 confirmed 可查询 C 统计，但 revision 可能为 null、batch 不属于 effective-REV，不适用 A 的原生 effective section 校验。

## 自动发布、历史与错误

保持 D→C 三步：POST `/api/admin/graph/effective` → GET `/api/admin/batches/{id}` → POST `/api/admin/batches/{id}/publish`。导入不自动修改活动指针。需要发布成功才能把同步标为成功。完整性检查仍逐节点、关系、端点、证据与版本比较整个有效快照；合法空快照同样验证 revision/counts，旧 confirmed 兼容规则不放宽。

新增只读管理员接口：

```http
GET /api/admin/graph/publication-status?page=1&page_size=20
Authorization: Bearer <由环境或服务配置提供的 GRAPH_ADMIN_TOKEN>
```

返回活动批次、活动版本元数据、`publish_generation`、历史/ready 批次分页。仅返回元数据，不传完整 effective 或证据归档。历史 status=published 表示曾发布，是否当前活动以 active_batch_id 判断；首次发布时间与最近激活时间分开。旧批次未存的时间/计数字段为 null。没有活动版本时 active=null；空快照已发布时 active 仍是该空快照 ID。

发布请求保留 `expected_active_batch_id`、`allow_developer_fixture`；新增可选非负整数 `expected_publish_generation`。发布持有原有 registry 写锁，检查活动 ID 和可选代数，再检查完整性，最后在同一写事务更新指针与状态。真正切换才递增代数；目标已经活动且 CAS 匹配时返回 unchanged=true，代数和首次时间不变。

```json
{"expected_active_batch_id":"此前活动批次或null","expected_publish_generation":12,"allow_developer_fixture":false}
```

**D 推荐在开始一次同步、读取 B 前固定 publication-status 的 ID/代数，发布时原样传回，不能失败后仅刷新 CAS 再强推旧文档。** 这能拦截并发和活动指针 A→B→A 后的旧请求。旧 D 不传代数仍兼容现有 ID CAS。重复旧通知携带过期 CAS 返回409，刷新并确认 B 当前 revision 后再决策；同 revision 导入幂等、已活动目标不重复切换。

必须明确：revision 是内容哈希，没有时间顺序；恢复旧快照是合法操作（20→30→20 也会恢复原 revision）。**C 无法仅靠哈希判定“旧通知”还是“有意撤回恢复”**。D 需在同步锁内读取 B 当前 effective，固定预期活动版本，过期时重新读 B；多 D 实例还需共享同步协调或单一发布者。若需要 C 自己辨别所有乱序来源事件，B/D 需提供可靠单调事件序号及其含义。目前未伪称完成此跨服务保障。

错误保留 `error.code/message`，增加 stage/retryable；422 仍有标准 detail（请求参数错误）。常见错误：INVALID_REQUEST、INVALID_EFFECTIVE_SNAPSHOT、REPORT_REVISION_MISMATCH、ACTIVE_BATCH_CHANGED、QUALITY_CHECK_FAILED、PUBLISHED_BATCH_NOT_FOUND、GRAPH_UNAVAILABLE、GRAPH_INTERNAL_ERROR。阶段包括 request_validation、validate、import、integrity_check、compare_and_swap、publish、read。冲突需重新核对版本；不能无条件自动重试旧发布。不会返回原始异常、数据库地址或凭据。

导入或事务内发布异常会回滚，旧活动版本仍可读。若数据库连接在提交结果返回途中中断，服务无法确定提交是否成功，503/500 会标记 `publication_outcome_unknown=true`，D 必须恢复连接后查询 publication-status，不能把异常当发布成功，也不能盲目删除新批次“回退”。本轮不另建重试队列，复用 D 的现有任务与状态框架。

## 手动检查与隔离复现

现有8002若未重启仍运行旧代码：在原 C 启动终端 Ctrl+C，保留原环境变量和凭据，再在 C 根目录启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.graph_query.api:app --host 127.0.0.1 --port 8002
```

以下只读检查不会导入或发布，保留现有150篇。凭据从现有环境读取；不要粘贴到文档或截图：

```powershell
$base = 'http://127.0.0.1:8002'
Invoke-RestMethod "$base/api/health" # implementation_revision 应为 c-effective-graph-v4
$papers = Invoke-RestMethod "$base/api/research/papers?page_size=1"
$batch = $papers.batch_id
$encBatch = [uri]::EscapeDataString($batch)
$report = Invoke-RestMethod "$base/api/research/report-statistics?batch_id=$encBatch"
$report.data.statistics.paper_count
$report.data.distributions
$report.data.authors
$author = $report.data.authors.items[0].id
$encAuthor = [uri]::EscapeDataString($author)
Invoke-RestMethod "$base/api/research/coauthors?batch_id=$encBatch&anchor_id=$encAuthor&page_size=5"
Invoke-RestMethod "$base/api/admin/graph/publication-status" -Headers @{Authorization="Bearer $env:GRAPH_ADMIN_TOKEN"}
```

浏览器打开 `/docs` 可测试新增只读统计接口；`/research`、`/research/analytics` 保留原页面。没有新增 D 页面、没有代替 D 的浏览器在线联调。API 和页面仍应携带同一 batch，不能把页面默认新版本与旧报告混用。

隔离测试（out 必须是新的目录，不要指向 B 正在使用的账本）：

```powershell
.\.venv\Scripts\python.exe -B scripts/build_week3_b_exports.py --b-root ..\CV-insight-kg-B-reference --a-root ..\CV-insight-kg-A-reference --out work\week4-new-run
.\.venv\Scripts\python.exe scripts/verify_effective_isolated.py --java ..\runtime\zulu21.40.17-ca-jdk21.0.6-win_x64\bin\java.exe --file ..\effective.json --port 17744 --exports work\week4-new-run --a-reference ..\CV-insight-kg-A-reference --report work\week4-new-run\c-150-results.json --junit work\week4-new-run\tests.xml
node tests/graph/graph-view.test.mjs
```

复用现有 `requirements-week3-dev.txt`（含 C 测试及 B 离线导出需要的依赖）。Harness 用预构建的官方 Neo4j 5.26 测试依赖和 Java21，无认证、随机驱动测试占位值，进程结束即停止其临时库。指定不同空闲端口即可，不使用 Docker 现有端口/卷。脚本不会启动 A/D 服务，也不访问在线来源。大型快照、临时账本和完整临时数据库均在本地测试目录，不作为源码交付。

详细数量和批次 ID 见 `week4-results.json`；验证分类与未完成事项见 `week4-verification.md`；提交文件清单见 `week4-files.txt`。OpenAPI 完整参数见 `openapi.week4.json`。
