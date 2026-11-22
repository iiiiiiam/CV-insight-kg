# Part A 第四周：任务后台、一键交接与报告包

更新日期：2026 年 11 月 22 日。开发基于第三周整合版 `20994e6`，代码保存在本地 `a-week4`，本轮尚未推送。

## 本周计划与实际推进

| 推进顺序 | 本周工作 | 当前实现 |
| --- | --- | --- |
| 1 | 复用正式导入、去重、撤回与重试 | 沿用第三周实现，补齐 D 网关的正式批次创建、列表接口 |
| 2 | 一键交接后台 | 持久化任务、异步发送给 B、撤回交接、版本核对、回执及失败重试 |
| 3 | 报告任务 | 复用 A worker，支持创建、分页查询、进度、失败重试、服务恢复和下载 |
| 4 | A 的报告章节 | 冻结论文明细、来源、字段质量、正式采集覆盖及批次信息 |
| 5 | 文件组织 | Markdown、HTML、CSV、JSON、manifest、SHA-256 和 ZIP 下载 |
| 6 | B/C 数据接入 | 可附带固定范围和版本的数据；已接 B 的 knowledge-report/1，C 沿用现有统计接口，新增统计待 C 提供 |
| 7 | 配合 D | 已提供网关路由、TypeScript 调用文件和 A/B/C 三阶段状态查询，正式页面由 D 接入 |

任务通过新表 `a_workflow_tasks` 持久化，仍由 `app.worker` 执行，沿用既有 worker 互斥和恢复入口。导入任务的表、编号及状态保持原有语义。

## 运行

本周提交包含任务后台、B 第四周报告接入及 CVPR 2024 覆盖核对资料；来源配置沿用上周页面。定时采集已撤下，Docker 留待后续迭代。

按现有方式启动 A、worker 和网关。综合本地预览可执行：

```bash
python -m pip install -r requirements-dev.txt
python -m server.run_local --demo
```

D 分别启动服务时继续使用 `python -m server.run_a` 与原网关入口。启动器在服务端复用现有管理员配置连接 B；独立部署时配置 `B_API_BASE_URL`、`B_ADMIN_USERNAME`、`B_ADMIN_PASSWORD`。凭据不放入浏览器请求或任务内容。

报告产物默认写入相对目录 `data/report-tasks`；可通过 `A_REPORT_ROOT` 指定位置。任务结果在应用数据库中保存，重启会恢复未完成任务。

## 给 D：任务与下载接口

以下路径均由网关提供，沿用管理员会话；POST 使用现有 `X-CSRF-Token`。前端可直接复用 `frontend/src/services/workflows.ts`。

| 接口 | 用途 |
| --- | --- |
| `POST /api/admin/formal/batches` | 提交正式批次 |
| `GET /api/admin/formal/batches` | 正式批次列表 |
| `POST /api/admin/handoffs` | 创建一键交接任务 |
| `GET /api/admin/handoffs` | 交接任务列表 |
| `GET /api/admin/handoffs/{id}` | 交接进度、结果和错误 |
| `POST /api/admin/handoffs/{id}/retry` | 重试失败交接 |
| `GET /api/admin/handoffs/{id}/pipeline` | 核对 A 导入、B 知识与 C 发布状态 |
| `POST /api/admin/reports` | 创建报告任务 |
| `GET /api/admin/reports` | 分页查询报告任务 |
| `GET /api/admin/reports/{id}` | 进度、阶段、错误、结果与事件 |
| `POST /api/admin/reports/{id}/retry` | 用原冻结输入重试失败报告 |
| `GET /api/admin/reports/{id}/download` | 下载 ZIP |
| `GET /api/admin/reports/{id}/files/{filename}` | 下载 manifest、报告或明细文件 |
| `GET /api/admin/report-inputs/B` | 读取 B 当前有效知识，转换为报告章节输入 |
| `GET /api/admin/report-inputs/C?expected_revision=…` | 读取与 B 同版本的 C 统计 |

列表支持 `page`、`page_size`、`status`。任务状态为 `queued`、`running`、`succeeded`、`failed`；`progress` 为 0—100，`stage` 和 `events` 给出实际阶段。重试保留原任务 ID，增加 `attempts`。

同一次点击生成一个 `request_key`，网络重发沿用该值。相同编号和参数返回已有任务；参数改变返回 409。点击失败重试时调用 `/retry`，无需重新创建任务。

### 一键交接

先读取批次得到当前 `batch_revision`，然后提交：

```json
{
  "request_key": "week4-handoff-1",
  "batch_id": 1,
  "expected_revision": "读取到的64位批次版本",
  "acknowledge_switch": true
}
```

返回 202 和任务 ID，页面轮询交接任务。完成后使用 `/pipeline` 核对三阶段；B 已接收与 C 已发布分别取实际状态，不用任务完成代替全链路成功。

A 撤回已交接过的批次时，自动持久化一条 B 撤回通知任务，与 A 撤回在同一事务保存。返回值 b_notification 包含任务 ID、状态和错误；重复撤回沿用原通知任务。失败时调用交接任务的 /retry。未向 B 交接过的批次返回 not_required，不改变 B 的输入集合。页面显示通知状态并提供重试按钮。共有论文保留，独有论文移除。

B 首次接收仍沿用其既有输入集合切换规则；`acknowledge_switch` 对应这一确认。B/C 的知识抽取、规则和发布算法继续使用各自模块。

### 报告创建

仅生成 A 当前有效论文报告：

```json
{
  "request_key": "week4-report-1",
  "title": "本周论文数据报告",
  "scope": {"venues": ["CVPR"], "years": [2024]}
}
```

`scope` 可按会议、年份和来源论文 ID 数组 `paper_ids` 限定范围。不传筛选即当前全部有效论文；包含不在范围内或已撤回的指定论文时返回 409，刷新后重新选择。

指定 `batch_ids` 时，使用这些批次的冻结历史内容：相同论文选择编号较大的所选批次版本，报告明确标记为 `selected_batches_historical`，可以包含已撤回批次的历史论文。未指定批次时标记为 `current_effective`。任务创建后再导入、更新或撤回，不改变该报告；重试也使用原冻结输入。

附带 B/C 章节时，在 `sections` 中传入：

```json
{
  "provider": "B",
  "revision": "提供方数据版本",
  "paper_ids": ["https://openalex.org/W…"],
  "data": {"由提供方输出的知识或统计数据": "完整结构"}
}
```

`/report-inputs/B` 返回值可直接作为一个 section。若 A 总库大于 B 当前知识范围，可用 B 返回的 `paper_ids` 限定 `scope.paper_ids`。A 会核对论文范围；对于 B 新版报告附件或原生 effective，还校验内容哈希与论文版本。C 原生统计核对发布批次、论文数量及 B revision。

需要 C 内容时，先固定 B revision，再以该 revision 读取 C 输入。C 暂时没有相应版本时保留错误状态，待发布完成重试。只附 A 或 A+B 也可以生成报告，manifest 会列出本次未附的提供方。

## 报告包内容

| 文件 | 内容 |
| --- | --- |
| `report.md`、`report.html` | 可阅读的报告及章节说明 |
| `summary.md`、`summary.json` | A 的数据概述，包含论文范围、会议年份、来源覆盖、字段完整度和所选批次回执汇总 |
| `papers.csv`、`papers.json` | 稳定 ID、标题、作者、会议、年份、摘要、DOI、引用数和来源链接 |
| `sources.csv`、`sources.json` | 论文来源、来源 ID、链接及原始记录指纹 |
| `quality.md`、`quality.json` | 字段完整度、缺失清单，以及可用的正式采集覆盖记录 |
| `batches.json` | 所选历史批次及版本 |
| `b-data.json` | 附带的完整 B 章节 |
| `b-entities.json`、`b-relations.json`、`b-evidence.json` | 从 B effective 保留的实体、关系和证据明细 |
| `b-report.json`、`b-author-tags.json`、`b-labels.json` | B 第四周完整知识附件及作者论文知识标签，保留支持论文和证据 |
| `b-quality.json`、`b-source-classifications.json` | B 知识质量事实及论文来源分类 |
| `c-data.json`、`c-statistics.json`、`c-years.csv` | 本次附带的 C 统计及年份分布 |
| `manifest.json` | 数据范围、A/B/C 版本、内容文件大小及 SHA-256 |
| `checksums.sha256` | 内容文件和 manifest 的校验值 |
| `README.md` | 文件使用说明 |

B/C 文件按本次实际输入生成。ZIP 的 SHA-256 随任务结果和下载响应头 `X-Content-SHA256` 返回；下载接口保留 `Content-Disposition`，浏览器可直接保存附件。

## 给 B / C：本轮接入范围

B 继续使用现有批次接收、去重、撤回及 `knowledge-effective/1.0`。A 的交接任务调用这些接口并保存真实回执。报告现接入 B 第四周 `knowledge-report/1`，一次冻结完整 knowledge、author_tags、quality，保留作者标签的支持论文和原文证据。

C 的当前适配读取同 revision 的年份及分布统计。第四周新增的双序列趋势、共同作者、作者与机构统计，待 C 给出接口后补入对应章节。章节输入同时支持 `trends`、`distributions`、`authors`、`institutions`、`coauthors` 数据项，保持提供方版本和论文范围。

D 复用任务和下载接口实现报告页面、一键交接按钮与三阶段显示。公共导航、研究页面布局和最终联调沿用 D 的统一版本。

## 实际验证与后续安排

已完成隔离 HTTP 验证，使用现有 CVPR 2024 真实论文输入：

验收使用独立数据库和 B 离线来源模式，验证已有真实论文的接收与报告生成；联网来源补充及 C 实际发布随后按团队环境验证。

- A 正式导入、worker 处理、网关一键交接，B 数量为 20 → 30 → 撤回后 20。
- 重复交接返回 unchanged，论文不重复。
- 生成包含 A 数据与 B 有效知识的 30 篇报告，ZIP 下载及 manifest 文件校验通过。
- 撤回后，原 30 篇报告保持相同内容；新建报告为 20 篇。
- C 实际发布未在本轮运行，三阶段状态保留待核对。

复核命令：

```bash
python -m pytest -q tests/test_workflows.py server/tests/test_workflows_gateway.py
python -m scripts.verify_week4_a
npm --prefix frontend test
npm --prefix frontend run build
```

验证记录保存于本地 `reports/`。B 第四周作者标签和知识质量已接入；后续补入 C 新统计，由 D 在统一页面完成在线全链路验收。给老师的进度材料按本周实际完成和确认结果继续更新。

本轮检查记录：

- 综合单元回归执行 326 项，5 项可选原型测试跳过，其余通过；随后追加的工作流与网关定向检查 22 项通过，包含旧任务升级和轻量进度查询。
- 导入、去重、撤回、启动和网关的阶段性回归 84 项通过。
- 前端既有 54 项测试及生产构建通过，新增调用文件通过 TypeScript 检查。
- 10 组实际浏览器流程通过，JavaScript 异常和意外失败请求均为 0；覆盖导入、进度、搜索、分页、批次对比、选批撤回、返回、错误恢复及 390px 布局。检查使用原数据库副本，原库未修改。

## A 的 summary 接入

创建报告时自动生成 A 的数据概述，写入 report.md 和 report.html，同时生成 summary.md、summary.json。概述与明细沿用同一冻结范围和版本，重试时继续使用原输入。

D 沿用现有创建、进度和下载接口。任务完成后，可调用 `GET /api/admin/reports/{id}/files/summary.json` 读取 A 的结构化概述，或下载 summary.md。两个文件同时包含在 ZIP、manifest 和 SHA-256 校验中。

来源按各来源覆盖的唯一论文数统计。一篇论文有多个来源时可计入多个来源。批次处理次数按所选批次的完整回执累计，概述列出统计口径。按当前论文范围生成而未选批次时，batch_changes 为 null。空报告的完整率为 null。


## 11 月 21 日补充：对接 B 第四周

本地联调采用 `knowledge-week4@a9c9378` 的 B 代码，起点与 A 同为 `graph-front-v3@20994e6`。整合时先接入 B 本周提交，再接入 A 本轮改动。B 文件沿用原提交，A 不另复制一套知识实现。

### 报告附件与版本

`GET /api/admin/report-inputs/B` 现读取 B 的完整 `knowledge-report/1`，转换为原有 ReportSection。外层 `revision` 始终是知识版本 `data.scope.knowledge_revision`；B 附件自己的内容版本为 `data.revision`。C 继续按知识版本核对，不能拿 B 报告内容版本查询 C。

创建报告时校验 B 附件校验值、论文范围、A 冻结论文内容，以及 B/C 知识版本。B 当前导出完整有效集合；与 A 选择范围不同时返回 409，不截取或拼接标签。历史报告与重试沿用冻结附件。

新增完整附件 b-report.json、作者标签 b-author-tags.json、知识质量 b-quality.json；b-labels.json 与作者标签一致，原论文来源分类另存 b-source-classifications.json。文件统一进入 manifest 和 SHA-256 校验。旧 effective 输入继续兼容。

作者标签只表达“作者参与论文涉及的主题、方法、任务和数据集”。知识质量按论文累计有效条目次数；证据覆盖率不写成准确率，未知准确率保留 null。

### 状态接入

三阶段查询复用 B 的 `/api/admin/knowledge/batches/readiness`。B 已接收、知识结果可读、外部来源补充状态分别呈现；来源 partial/interrupted 时只要结果可读，B 知识阶段可完成。C 阶段仍查询对应知识版本的真实发布状态。

### 联调复现

```bash
python -m scripts.verify_week4_a --output reports/b-week4-check
```

使用隔离数据库、现有真实论文和离线补充来源，验证 20→30→20→0、重复交接、自动撤回通知及重复撤回幂等、新版报告附件、版本冲突与文件校验。C 实际发布由后续统一环境联调验证。

本轮最终复核：后端 505 项通过、17 项可选检查跳过、107 个子用例通过；前端 54 项测试及构建通过。原有 10 组页面流程复跑通过；新增真实浏览器验证 B 撤回通知失败重试、成功显示和刷新保留状态。


## 11 月 21 日补充：展示 CVPR 2024 覆盖核对结果

复用已保存的 CVPR 2024 正式采集记录，对照冻结官方目录重新核对：官方 2,716 篇，精确匹配 2,678 篇，覆盖率 98.60%，待核对 38 篇。官方目录及覆盖快照位于相对目录 examples/collection_coverage，随代码提供，换目录或换电脑后可直接读取。A_COLLECTION_ROOT 中保存的同名报告优先使用。

质量页分开展示正式采集快照的覆盖率与当前库该会议年度的有效论文数。待核对论文可查看标题及官方来源；原始未匹配原因保留在质量导出数据中。覆盖资料的接入不增加当前库或补充库的论文。


## 11 月 22 日：待提交版本最终复核

来源配置按用户确认保留。当前版本已排除定时自动采集的页面、接口、调度进程及对应测试；Docker 不纳入本周提交。最终完整后端回归 488 项通过、17 项可选检查跳过、103 个子用例通过；前端 54 项测试和生产构建通过。当前预览已确认质量页读取 CVPR 2024 覆盖资料，当前库仍为 420 篇，补充库仍为 2,534 篇。本轮等待用户检查后决定推送。
