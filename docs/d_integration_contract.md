# D 端原型接入契约 v0.3.0

## 1. 分层与数据来源

```text
Vue 页面 / 三级菜单
  └─ 通用组件：StatePanel / DetailDrawer / GraphPanel / AppIcon
      └─ services/research.ts、admin.ts、knowledge.ts、stores/auth.ts
          └─ D FastAPI 路由与权限依赖（server/api、server/domain）
              ├─ AServiceClient → A 原有 HTTP API → A 数据库
              └─ KnowledgeSnapshot → B 原有抽取函数 → 已校验 A 固定快照

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
| `GET /admin/knowledge/snapshot` | 管理员 | B 固定快照概览：实际计数、版本、论文清单，read_only=true、confirmed_count=0 |
| `GET /admin/knowledge/candidates?paper_id=...` | 管理员 | 完整 OpenAlex ID；返回 `{paper,result,read_only,confirmed_count,scope,notice}`；非固定样本 404 |

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
| `CandidateView` | 路由 paper_id | 只读 | 候选切换、精确证据、原文高亮；不提供审核写入 |

`GraphData.batch_id` 是本轮沿用的前端接口字段，值表示查询范围（例如“A 当前数据库”或“批次 ID 1”），不是 C 已发布图谱批次，也不是不可变快照承诺。之后由 C 提供正式批次契约时再替换。

检索与图谱请求支持 AbortSignal 和请求序号，旧响应不覆盖新筛选结果。错误不回退合成数据。来源链接只接受 HTTP/HTTPS；证据文本使用 Vue 文本插值，不执行 HTML。B 的偏移是 Python Unicode 字符索引，高亮使用 `Array.from(text)`，不是 JavaScript UTF-16 索引。

## 4. 菜单及接入边界

菜单 ID NAV01—NAV20 保留在 `navigation.ts`；已实现与占位以 `implemented` 区分。占位页面不模拟提交成功。

- NAV01—04：A 论文工作台、详情和元数据图。
- NAV05：C 多跳扩展待接入。
- NAV06—11：完整导出流程、趋势、作者/机构分析等后续入口。
- NAV12—15：真实基准、导入、任务与错误/重试。
- NAV16：B 真实候选只读；NAV17 人工审核待接入。
- NAV18—19：C 质量校验与发布待接入。
- NAV20：D 真实会话与权限检查。

这份契约描述当前 D 实现及预留边界；没有把 A/B 草案升级成全团队已冻结的正式业务契约。
