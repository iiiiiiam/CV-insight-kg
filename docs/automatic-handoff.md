# A→B 自动交接与 OpenAlex 字段接入

更新：2026-11-24。本轮为本地开发版本，尚未推送；在 data-pipeline@bda9d06 上继续开发。

## 正常流程

正式批次或补充论文库批次全部导入成功后，A 在同一事务创建持久化交接任务，由已有 worker 调用 B 批次处理模块或独立接收接口，保存真实回执。页面只查询处理状态，正常使用无需点击交接按钮。原 `POST /api/admin/handoffs` 创建入口已取消；任务查询、失败重试和三阶段核对保留。

报告任务继续使用原有队列与下载接口。自动交接与在线定时采集分别运行。2026-11-24 按用户要求恢复采集页面和调度服务，计划暂保持关闭；Docker 不在本轮范围。

## 补扫、重试与对账

- 启动及运行中补扫带版本账本的 formal/reserve 批次。每个批次版本只创建一份自动任务；初始样本与演示历史沿用原有管理方式。
- 交接网络失败或服务暂不可用时，自动按 30、60、120、240 秒退避重试，包含首次共 5 次。到上限后保留失败原因，可在页面处理后立即重试；立即重试重新提供 5 次预算。
- 部分导入失败只重试失败记录，最多自动重试 3 次。已有成功记录、稳定论文 ID 与批次编号保留。来源停用或同会议年度有其他活跃导入时等待。
- 撤回已交接或正在交接的批次时，在同一事务创建 B 撤回通知。旧版本任务停止重试，新撤回任务独立处理；重复撤回沿用原任务。
- 每分钟读取 B 批次状态，对比批次编号、有效状态及交接文档 SHA-256。B 已提交、A 回执尚未落库时自动补回回执；B 丢失最新批次时自动补交。
- B 独立撤回、同编号不同内容、或补交旧批次会改变既有新批次优先级时，记录冲突供核对，保留 B 的有效状态。A 不撤回 B 中来自其他提供方的批次。
- 暂时无法连接 B 时保留上次结果并退避重查；接收、来源补充与 C 发布继续分别核对。

整合启动入口默认以 local 模式直接调用 B 模块，使用同一 B_BATCH_REGISTRY。独立部署使用 http 模式时，继续配置 B_API_BASE_URL、B_ADMIN_USERNAME、B_ADMIN_PASSWORD。A_AUTO_HANDOFF 默认启用；隔离测试可关闭自动任务创建和补扫。

## 给 D 的读取接口

| 接口 | 用途 |
| --- | --- |
| GET /api/admin/handoffs | 自动交接任务及状态 |
| GET /api/admin/handoffs/{id} | 实际进度、尝试次数、错误和下次重试时间 |
| POST /api/admin/handoffs/{id}/retry | 处理失败原因后立即重试 |
| GET /api/admin/handoffs/{id}/pipeline | A、B、C 三阶段状态 |
| GET /api/admin/handoff-sync | 最近对账结果、冲突、待补交及下次检查时间 |
| GET /api/admin/formal/batches/{id}/receipts | 原接收回执，新增 automatic_task |

任务新增 automatic、retryable、max_attempts、next_attempt_at；导入详情新增 retry_attempts、next_retry_at。下游交接状态区会自动读取进度，显示自动重试时间并保留立即重试入口。已复用 graph-front-v4 的 WorkflowCenterView 任务中心，将一键交接按钮替换为自动交接、对账和失败重试展示；保留原报告创建与下载操作。整合时采用本轮任务中心和 services/workflows.ts 的配套版本。

## 与 B 的 OpenAlex 字段对齐

A 同一轮 OpenAlex 请求覆盖基础字段，以及 primary_topic、topics、keywords、ids、locations、best_oa_location。新的正式采集命令和 OpenAlex 批量下载命令默认开启扩展字段；Python 函数原有默认参数保留。续跑原基础字段批次可显式使用 --without-annotations；冻结目录与断点仍按原请求字段核对。

```bash
python -m app.formal_collection CVPR:2024 --output data/collection-next
python -m scripts.fetch_openalex_batch CVPR 2024 data/collection-next/cvpr-2024.jsonl
```

带注释的论文仍使用原 PaperInput 字段；交接文档 a-paperinput/1 在顶层可附 source_annotations。每项包含 paper_id 与来源记录 record：source、url、fetched_at、payload、digest。旧文件没有该字段时，原处理流程不变。

B 接收前校验论文 ID、标题、年份、来源和内容 SHA-256。读取和来源补充直接复用 A 保存的 OpenAlex 注释，避免为已有字段再请求 OpenAlex。多个批次存在同一论文时沿用 B 的批次选择规则；撤回后恢复仍有效批次的注释。Papers with Code 的请求与解析逻辑未作调整。

B 的批次状态返回值额外包含 batch_id、handoff_digest、a_batch_revision，供 A 对账。B 的知识抽取、作者标签及 effective 格式保持原有契约；本轮不修改 C 的发布逻辑。

## 验证

新增覆盖自动任务创建、补扫、断点恢复、退避与预算、丢失回执、B 批次丢失、撤回通知、B 独立撤回、失败记录增量重试、注释复用和注释撤回恢复的测试。

```bash
python -m pytest -q tests/test_auto_handoff.py
python -m scripts.verify_week4_a --output reports/auto-handoff-check
```

HTTP 验收使用临时 A/B 数据、真实论文与离线来源。验证全程不调用手动创建交接接口，论文数为 20→30→20→0，并验证报告下载和历史报告保持原内容。C 实际发布仍由后续统一环境联调验证。


## 11 月 24 日收尾记录

完整后端回归 501 项通过、17 项可选检查跳过、103 个子用例通过。追加边界测试覆盖持续失败的导入重试预算、B 同编号异源批次不被撤回、旧批次补交不覆盖新版本、无可交接论文不切换 B 输入。前端 56 项测试和生产构建通过。任务中心同时修正了请求重叠和报告任务切换时旧下载链接残留的问题。最终浏览器复核结果随本地验收记录保存。


## 11 月 24 日：恢复定时采集

来源配置页和独立调度进程已恢复，计划保持关闭，具体时间及范围等待用户后续要求。定时批次成功后统一自动交接给 B；采集任务保留自己的失败重试预算，避免与普通导入自动重试重复执行。新计划默认同时获取 B 所需 OpenAlex 注释字段，已有保存参数继续沿用。


## 11 月 25 日：手动在线采集与后台直连

按用户具体演示要求，定时设置入口改为论文导入页的手动在线采集：默认 CVPR 2025、每次 20 篇，可选择年份、数量及关键词。整合启动默认直接调用 B 批次模块，省去内部 HTTP 与登录。原定时采集进程不再随启动入口运行。详情见[手动在线采集](manual-online-collection.md)。
