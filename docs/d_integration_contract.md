# D 端原型接入契约 v0.5.0

## 1. 分层与数据来源

```text
Vue 页面 / 三级菜单
  └─ 通用组件：StatePanel / DetailDrawer / GraphPanel / AppIcon
      └─ services/research.ts、admin.ts、knowledge.ts、stores/auth.ts
          └─ D FastAPI 路由与权限依赖（server/api、server/domain）
              ├─ AServiceClient → A 原有 HTTP API → A 数据库
              └─ 每次请求新建 KnowledgeSnapshot
                  ├─ B 原有抽取函数 → 已校验 A 固定快照
                  └─ B review_storage → 校验指纹、重放审核历史 → 当前状态
              ├─ 管理员审核 → B ReviewSession → B save_review 原子保存
              └─ 业务下载 → B build_exports / export_files → JSON / ZIP

C 正式 Neo4j 查询、发布批次和多跳查询：待接入
```

读取 A 的当前数据库与读取 B 的固定快照是两个明确的数据范围。A 的整数论文 ID 用于列表、详情及元数据图；B 使用完整 OpenAlex ID，前端由 A 的 `openalex_id` 跳转 B 页面。A 清洗后的标题不作为 B 原文偏移依据，B 高亮只使用 B 返回的原始 `PaperInput`。

## 2. D HTTP API

统一前缀 `/api`，开发环境同源代理，无需前端持有 A Token。

| 方法与路径 | 权限 | 契约/来源 |
| --- | --- | --- |
| `GET /health` | 匿名 | D 自身存活检查，不代表 A 已可用 |
| `GET /papers` | 匿名 | 转发 A；`q`、`year`、`venue`、`batch_id`、`page`、`page_size`，保持 A 校验规则与状态码 |
| `GET /papers/{id}` | 匿名 | 转发 A；包含摘要、sources、batch_ids、batches；不存在为 404 |
| `GET /papers/{id}/graph` | 匿名 | A 实际 `basis=paper_metadata`；仅 Paper、Venue 和 PUBLISHED_IN |
| `POST /admin/sessions` | 匿名、来源检查、限流 | JSON `username`、`password`；成功设置 Cookie 并返回会话 |
| `GET /admin/session` | 管理员 | 当前用户名、角色、到期时间与 CSRF Token |
| `DELETE /admin/session` | 管理员 + CSRF | 撤销服务端会话，清除 Cookie，204 |
| `GET /admin/probe` | 管理员 | 权限读测试，不改变数据 |
| `POST /admin/probe` | 管理员 + CSRF | 写权限/CSRF 测试，不改变数据 |
| `GET /admin/datasets` | 管理员 | A 基准清单原响应 |
| `POST /admin/imports` | 管理员 + CSRF | JSON `dataset_id`；执行 A 真实导入，保持 A 返回码 |
| `GET /admin/jobs` | 管理员 | A 最近任务 |
| `GET /admin/jobs/{id}` | 管理员 | A 任务详情及事件 |
| `GET /admin/jobs/{id}/papers` | 管理员 | A 批次论文分页，转发分页参数 |
| `POST /admin/jobs/{id}/retry` | 管理员 + CSRF | 由 A 判断能否重试；沿用原批次 |
| `GET /admin/export` | 管理员 | 转发 A CSV；支持 A 已有 venue/year/batch_id 参数，保留下载文件名与计数；暂无单独前端导出页 |
| `GET /admin/knowledge/snapshot` | 管理员 | 原始计数、三状态 `review_counts`、版本、论文清单、`snapshot_revision`、`loaded_at`；read_only=true |
| `GET /admin/knowledge/candidates?paper_id=...&snapshot_revision=...` | 管理员 | 完整 OpenAlex ID；返回独立的原始 `result` 和当前 `review`、快照指纹、读取时间；非固定样本 404，快照已变化 409 |
| `POST /admin/knowledge/reviews` | 管理员 + CSRF | 确认、驳回、实体改名、撤回；理由与页面快照指纹必填；审核人由登录会话提供，证据不可写 |
| `GET /admin/knowledge/exports/{filename}?snapshot_revision=...` | 管理员 | filename 为 confirmed.json/pending.json/rejected.json/bundle.zip；固定样本全部论文，保留 B 原格式 |
| `GET /knowledge/confirmed?paper_id=...` | 匿名 | OpenAlex ID；仅返回已确认实体、关系、证据和固定样本原文上下文，不返回操作人、理由、历史或其他状态记录 |

会话示例（所有尖括号字段均为格式占位，不是有效凭据）：

```json
{
  "authenticated": true,
  "username": "admin",
  "role": "admin",
  "csrf_token": "<随机值>",
  "expires_at": "<ISO-8601 UTC 时间>"
}
```

管理写操作带 `X-CSRF-Token`，Cookie 由浏览器自动携带。A 管理令牌只由 `server/application/a_gateway.py` 放入上游请求。Cookie 只有签名后的随机会话 ID；密码不返回前端，服务端使用 Argon2 验证。

D 自身错误格式：

```json
{"error":{"code":"HTTP_401","message":"请先登录管理员账号。"},"request_id":"<请求追踪标识>"}
```

常见状态：401 未登录/密码不正确，403 CSRF 或 Origin 不通过，404 不存在，422 参数无效，429 登录限流，502 A 不可连接。A 返回的业务错误和状态码原样保留，可能为 `{"detail":"..."}`；`requestJson` 同时兼容两种格式。

### B 审核结果读取契约

- `result` 仍为 B 的原始 `ExtractionResult`；其中候选始终 pending，不以审核后的改名、证据或状态覆盖。
- `review.items` 为 B 的 `ReviewItem`：`candidate_id`、`content`（Entity 或 Relation）、`evidence` 和实际 `status`（pending/confirmed/rejected）。`review.history` 保留完整 ReviewEvent，包括操作人、理由、UTC 时间、before/after 及端点撤回联动事件。
- `review.counts` 为该论文三状态实体/关系数；`review.has_archive` 说明是否读取了存档，`review.archive_revision` 为 B 的文件内容 SHA256，无存档时为 null。
- 概览的 `review_counts` 为全部样本的三状态实体/关系数。兼容字段 `confirmed_count` 是已确认实体数与关系数之和；界面分别显示两类数量，避免歧义。
- `snapshot_revision` 覆盖所有原抽取指纹与各论文的存档 revision，不含读取时间。前端从概览取得后带入详情查询；不一致返回 `409 KNOWLEDGE_SNAPSHOT_CHANGED`，要求重新读取整个页面。
- 校验、输入/词表版本、重复存档或目录错误返回 `409 KNOWLEDGE_SNAPSHOT_INVALID`。不会清空审核、回退为原始候选，也不会让登录和 A 接口随坏存档一起失效。
- 每个 GET 在工作线程中新建只读快照，复用 B 的 `load_review_records` 与 `ReviewSession`，不创建或保存存档，不复用全局可变审核会话。
- 历史操作人来自 B 存档，不能把所有历史都视为 D 认证。D 新提交由当前会话账号记录，但仍不将确认直接发布到 C 图谱。
- 兼容字段 `read_only=true` 表示这些 GET 只读取、不落盘，不表示管理员没有独立的审核写接口。

默认审核目录遵循 B 的 `default_review_directory`（含旧目录检测）。可配置 `B_REVIEWS_DIR`、`B_VOCABULARY_PATH`；若前者未设置，则兼容环境变量 `KNOWLEDGE_WORKBENCH_DATA/reviews`。配置相对路径按仓库根目录解析；不把浏览器输入作为磁盘路径。读取旧词表存档必须显式选择匹配词表，不能只因 candidate_id 一样就继承确认。

### 审核写入契约

请求字段：`paper_id`、`candidate_id`、`action`、`reason`、`snapshot_revision`；`correct` 额外传 `name`。action 仅允许 confirm/reject/correct/reopen。理由 1—2000 字，名称 1—300 字，禁止额外字段，包括 reviewer、evidence、任意磁盘路径等。

后端首先重新读取并校验存档，与客户端的快照指纹核对；随后在审核会话副本上调用 B 的方法。确认关系要求端点实体均已确认，改名后仍 pending，决定后的记录须先 reopen，实体撤回会联动已确认关系。D 不另写一套业务状态规则。

通过 B `save_review` 保存，沿用已有存档文件名，无存档时使用 B 默认哈希命名。保存携带读取时的 archive revision，并复用 B 文件锁、临时文件和原子替换。保存成功才更新请求内状态；失败不改候选和历史。首次保存冲突、旧磁盘版本或锁冲突返回 409；业务规则拒绝返回 422；磁盘/权限失败返回 503。客户端网络结果不确定时要求重新读取核对，不自动重试写操作。

成功响应含 `saved`、`paper_id`、`candidate_id`、`action`、`archive_revision`、更新后的 `snapshot_revision`、当前 `item` 和本次 `affected_candidate_ids`。前端重新读取概览/详情后展示新状态。

这是沿用 B 单机文件存档的写入，不是数据库事务或完整多人协作系统；D 与 B 对同一个文件的写入使用相同锁和版本规则。

### 下载与匿名论文详情

下载使用当前快照指纹核对页面统计，随后复用 B `build_exports`、`export_files`。JSON 按三种状态隔离；ZIP 包含 confirmed.json、pending.json、rejected.json、schema.json、manifest.json。范围为所有固定样本，与界面当前论文/筛选无关；内存生成文件，不在业务目录创建导出副本。A 原有 CSV 接口不变。

论文详情通过 A 的 OpenAlex ID 请求已确认内容。仅公开 `ReviewItem` 的已确认内容与证据，附 B 固定样本 title/abstract/source_url 供证据定位，不将其冒充为 A 后续更新后的文本。没有确认时返回明确空结果；不在固定样本中返回 supported=false；坏存档返回 409 且隐藏内部路径。不会把读取失败当作未审核，也不公开审核人、理由或历史。列表标签和 C 正式图谱不在本轮扩展范围内。

## 3. ResearchGateway 与组件

前端接口定义在 `frontend/src/types.ts`。所有论文 ID 在界面层统一为字符串；适配 A 图时，将 `paper:{id}` 映射为 `String(paper_id)`，同时重写关系端点，保证列表选中与图谱节点高亮一致。会议 ID 保留 `venue:CVPR` 等 A 原值。

| 接口/组件 | 输入 | 输出/事件 | 约束 |
| --- | --- | --- | --- |
| `getPapers` | Filters、AbortSignal | PaperPage | 使用 A 的标题/摘要关键词、年份、批次；主题/方法筛选未接入时明确失败 |
| `getPaper` | A 论文 ID、AbortSignal | Paper | 保留 OpenAlex ID、DOI、去重键、sources 与批次；未审核标签明确标记 |
| `getGraph` | seed、hops、Filters、AbortSignal | GraphData | 当前只允许 hops=1；不从 pending 候选拼正式图 |
| `getEntity` | A 会议节点 ID、AbortSignal | EntityDetail | 按会议查询 A 论文；明确为会议范围，非当前列表全部筛选结果 |
| `StatePanel` | kind/title/description/retry | retry | 统一加载、空态与错误重试 |
| `GraphPanel` | graph/selectedId | select(GraphNode) | 类型显隐、拖动、缩放、布局、节点键盘列表；销毁画布和 ResizeObserver |
| `DetailDrawer` | id/type | close、paper(id) | 真实详情、来源；Esc、焦点圈定与关闭后焦点恢复 |
| `CandidateView` | 路由 paper_id、reviewEnabled 页面元信息 | 读取/审核 | NAV16 保持查看，NAV17 显示操作区；原始抽取模式不可提交审核 |
| `ReviewActions` | 当前审核记录与快照 | saved/busy/reload/focus | 理由必填，证据只读；端点定位、改名及撤回；请求不提交审核人 |
| `KnowledgeDownloads` | snapshot revision | 浏览器下载 | 三状态 JSON 与完整 ZIP；错误响应不作为文件下载 |
| `ConfirmedKnowledge` | 论文 OpenAlex ID | 匿名只读 | 仅展示已确认实体、关系、来源证据及原文高亮 |

`GraphData.batch_id` 是本轮沿用的前端接口字段，值表示查询范围（例如“A 当前数据库”或“批次 ID 1”），不是 C 已发布图谱批次，也不是不可变快照承诺。之后由 C 提供正式批次契约时再替换。

检索与图谱请求支持 AbortSignal 和请求序号，旧响应不覆盖新筛选结果。错误不回退合成数据。来源链接只接受 HTTP/HTTPS；证据文本使用 Vue 文本插值，不执行 HTML。B 的偏移是 Python Unicode 字符索引，高亮使用 `Array.from(text)`，不是 JavaScript UTF-16 索引。

## 4. 菜单及接入边界

菜单 ID NAV01—NAV20 保留在 `navigation.ts`；已实现与占位以 `implemented` 区分。占位页面不模拟提交成功。

- NAV01—04：A 论文工作台、详情和元数据图。
- NAV05：C 多跳扩展待接入。
- NAV06—11：完整导出流程、趋势、作者/机构分析等后续入口。
- NAV12—15：真实基准、导入、任务与错误/重试。
- NAV16：B 原始候选与真实存档结果查看；NAV17：管理员审核与改名。两页均提供 B 业务文件下载。
- NAV18—19：C 质量校验与发布待接入。
- NAV20：D 真实会话与权限检查。

这份契约描述当前 D 实现及预留边界；没有把 A/B 草案升级成全团队已冻结的正式业务契约。
