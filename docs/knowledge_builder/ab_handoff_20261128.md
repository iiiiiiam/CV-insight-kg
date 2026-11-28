# A/B 自动交接实现与整合说明

更新日期：2026-11-28。本文供组长整合时核对当前 B 适配、A 分支接口及重叠文件；最终合并方式由组长决定，不规定 Git 操作。B 负责人继续承担 A/B 接入核对及后续必要测试。

## 1. 当前交付状态与分支

**当前 B 接收、来源复用和后台自动补充已完成适配；A 最新自动交接工作流尚未合入本分支。整合后的目标是：一次导入后自动交接，已有知识先发布，后台补来源，有效知识变化后自动更新发布。普通用户无需逐阶段确认或配置内部服务。**

| 分支/版本 | 当前角色与范围 |
| --- | --- |
| `graph-front-v4@b6923d8` | 当前开发的整合基础，已包含此前 A、B knowledge-week4、C graph-query-week4 及 D 整合，不等于 A 后续更新已全部进入 |
| `data-pipeline@9cca61d` | 本次审查的 A 最新版本，包含自动交接、恢复、对账和手动在线采集；后续提交仍待组长整合 |
| `deploy/windows-installer@07b4750` | 当前交付分支，包含 Windows 安装/启动、云反馈与团队账号，以及本轮 B 交接适配和独立修复；本地与远程引用已核对至此提交 |
| 11 月 27 日 Windows 安装包 | 已有安装和云反馈闭环验证；不包含 11 月 28 日本轮 B 适配与最新修复，本轮未重新打包 |

本轮相关提交：

| 提交 | 内容 |
| --- | --- |
| `0d902d7` | B 批次身份字段、A OpenAlex 注释复用及非阻塞兼容 |
| `7216678` | A/B 报告契约核对工具与交接边界记录 |
| `ffa1699` | 本地账本自动发现、缺失来源后台补取，与现有自动发布独立运行 |
| `da73532` | 独立前端修复：旧反馈历史缓存提示与已有回复保留 |
| `07b4750` | B 来源失败渐进退避，保留自动恢复；不改变发布主流程 |

A 尚未进入当前分支历史的提交为 `5be1ca5`（第四周交接任务与报告包）、`bda9d06`（说明）、`9cca61d`（自动交接与手动在线采集）。这里列出分支关系，不表示已运行完整 A 最新工作流。A 文档里旧的“尚未推送”描述以实际 Git 记录为准。

## 2. 整合后采用的自动流程

下列是双方实现配合后的流程；其中 A 的新任务逻辑仍在 A 分支，不能将整条流程表述为已在当前分支完成真实联调。

```text
用户正式导入 / 发起在线采集
  → A 采集、去重、入库，固定论文与批次版本
  → A 自动建立持久化交接任务，原 worker 执行
  → B 接收批次、按论文 ID 合并，复用 A 已提供的来源
      ├─ 已有知识立即可读、可导出 → D 后台导入并发布到 C
      └─ B 后台自动补缺失来源 → 有效知识版本变化 → D 自动更新发布
```

“先发布”指不等待外部来源、不增加人工确认；实际发布仍取决于 D 同步周期及 C/Neo4j 可用性，不承诺接收返回时图谱已发布。

### 2.1 A 采集、任务和恢复：来自 A 分支

- 正式批次成功后自动建立交接任务，输入和版本持久化；不需要再点击“交给 B”。
- 手动在线采集可选择会议、年份和篇数，新论文进入正式批次处理；没有新增时正常完成，不用空批次切换 B 输入。
- 原 worker 执行交接、保存回执；启动及周期扫描补回遗漏。失败自动重试，超出预算才保留原因供例外处理。
- 对账比较批次身份、状态和文档指纹，可恢复“B 已接收但 A 回执丢失”的情况。
- A 撤回时自动排队通知 B。相同编号来源冲突、B 独立撤回等情况保留供核对，不强行覆盖其他操作。

### 2.2 B 接收、合并和来源复用：当前分支已有

- 保留原 `a-paperinput/1` 接收契约、幂等规则及按稳定论文 ID 合并；重复同内容不重复新增。
- **新增对账字段**：批次状态提供 `batch_id`、`handoff_digest`、`a_batch_revision`，保留旧字段，便于 A 核对和恢复回执。
- **新增 A 来源复用**：读取当前有效批次的 `source_annotations`，有效 OpenAlex 注释优先于旧缓存；同论文新批次优先，撤回后恢复其他有效批次的信息。
- 核心论文继续按原规则校验；可选来源不匹配或不可用时忽略该补充，不因附加字段失败拒绝整批有效论文。
- B 的知识读取、依据查询和导出使用已有来源与规则结果，不在这些请求中等待外部 API。

### 2.3 B 自动补来源与 D 发布：本轮新增连接点

此前只有 HTTP 接收路由安排补来源，A 本地直接调用接收模块会绕过该触发点。现在已补齐：

- **B 随正常软件启动自动检测受管理批次账本**，本地接收也会自动进入补来源流程，不要求用户点击按钮或运行额外脚本。
- HTTP 接收与本地检测共用一个 `SourcePreparation` 协调器，避免重复启动任务；复用原 `BatchSources.prepare` 和来源缓存，不另建服务。
- 已有有效来源直接使用；缺失时才尝试 OpenAlex/Papers with Code。因此不能笼统说“B 不再访问 OpenAlex”，准确说法是“不重复请求 A 已提供的有效信息”。
- 外部请求在后台执行，已有知识继续可用；来源失败保留结果并自动恢复，不影响先发布。
- D 现有自动同步负责 B effective → C。补充产生有效知识变化时 revision 改变，D 自动发布更新；时间戳或无效信息变化不制造无意义版本。
- C 不可用时 D 保留状态并后台重试，B 阅读、导出与来源补充继续工作。

来源补充只是完善知识输入，不是接收成功或发布的前置审批。第三方没有匹配数据时，自动尝试也不保证一定补齐。

### 2.4 撤回、报告与状态含义

- A 撤回通知到 B 后，独有论文退出，共有论文保留或恢复其他有效输入；全部撤回后为空，不回退到演示语料。
- 报告按创建时范围冻结。A 最新任务页面在 C 对应版本尚未就绪时允许自动生成 A+B；缺章明确记录，不拼接不匹配版本。
- `accepted` 仅表示 B 接收落盘；`results.available` 表示有效知识可用；来源完成和 C 发布是另外的状态，不能混为一项成功。
- A 本地接收回执不是来源后台进度的持续订阅。展示后续处理进度时应使用 B readiness 和 D 发布状态，不将接收时的回执字段当作实时进度。

## 3. 本地直连与 HTTP 的定位

| 方式 | 实际调用 | 使用条件 | 自动补来源 |
| --- | --- | --- | --- |
| 整合运行 `local` | A `app/delivery.py` 直接调用 B `BatchRegistry` 接收/撤回 | A worker 正常运行，A 与 D/B 指向同一个实际账本 | B 后台检测账本变化，自动补取 |
| 分离运行 `http` | A 登录原 B HTTP 接口，提交批次或撤回 | B 地址、服务端账号、会话/CSRF 正确，服务可连通 | HTTP 可立即安排同一后台任务 |

当前整合方向优先本地直连，省去内部 HTTP 登录；HTTP 保留兼容独立部署和现有调用。两者都调用 B 正式接收逻辑，不是绕过校验直接篡改文件，也不会因为同时存在两种入口就重复处理。

A 最新 `server/run_a.py` 已为整合入口设置 local transport 和账本路径；这些启动改动仍需合入当前分支。普通使用者不应填写内部地址、服务端凭据或账本路径。腾讯云反馈是另一条独立功能链，不参与 A/B 论文交接。

## 4. 给组长的重点：合并时需要核对和保留什么

以下是 B/Windows 开发视角下已经发现的兼容要求，并非要求组长采用特定合并方法。**重点是配套接入和重叠文件内容共存，避免用一侧整文件覆盖另一侧。**

### 4.1 优先核对的五项

1. **A 自动交接需要配套进入。** 任务创建、模型/持久化、worker、扫描/对账、回执、工作流 API 和页面共同接入；只拿 B 适配或只拿 A 页面都不能构成完整自动流程。无需恢复人工逐阶段确认。
2. **保留 Windows worker 启动兼容。** 当前用 `module_command('app.worker')`，可分别处理源码 Python 与冻结 EXE。A 分支改回 `sys.executable -m app.worker`，直接覆盖会破坏安装包内部模块启动。应将 A 的 local transport/账本配置与当前启动方式结合。
3. **统一账本并保留 B 后台协调器。** A、D/B 必须使用同一个实际 `B_BATCH_REGISTRY`；API 生命周期与 HTTP 路由共享同一 `SourcePreparation`。不能退回只有 HTTP 才补来源，也不能让发布等待来源完成。
4. **保留可选注释非阻塞策略。** A 原补丁在 `batches._prepare` 严格校验附加注释并可能拒绝整批；当前 B 不采用这部分行为。保留核心论文和存档完整性校验，同时跳过无效可选注释，避免有效论文被来源字段卡住。
5. **保留已有整合成果。** `main.py` 等重叠文件中的团队认证、云反馈、工作流注册及 JS MIME 修复需要共存；前端也需保留反馈、账号及当前页面适配。新增依赖随 A 功能一起核对，不用旧安装包代表新代码。

### 4.2 文件与整合关注点

| 范围 | 重点文件 | 核对内容 |
| --- | --- | --- |
| A 自动交接 | A 分支 `app/auto_handoff.py`、`app/delivery.py`、`app/workflow_tasks.py`、`app/worker.py`、`app/formal_batches.py` 及配套模型 | 任务创建、恢复、通知、执行与回执完整接入 |
| A 在线采集与报告 | A 分支 `app/online_collection.py`、`app/report_bundle.py` 及配套 API/模型 | 在线新论文进入正式批次；报告范围和知识版本正确，允许明确缺章 |
| B 接收及注释 | `server/api/knowledge_batches.py`、`src/knowledge_builder/batches.py`、`batch_sources.py`、`upstream_openalex.py` | 新对账字段、选中批次来源优先级、撤回恢复；避免恢复附加注释整批拒绝 |
| B 后台任务 | `server/application/source_preparation.py`、`server/api/main.py`、`server/api/knowledge_feedback.py`、`server/configuration/settings.py` | 自动启动/关闭、共享协调器、默认开启、与发布独立 |
| Windows 启动 | `server/run_a.py`、`server/run_local.py`、`server/process_command.py` | 同一账本、local transport 与源码/EXE 启动方式结合 |
| D 工作流与前端 | `server/api/main.py`、`server/api/workflows.py`、`frontend/src/views/WorkflowCenterView.vue`、`frontend/src/services/workflows.ts` 及导航/路由 | A 配套工作流与当前认证、云反馈、页面修改兼容 |
| 独立反馈提示修复 | `frontend/src/components/MyKnowledgeFeedback.vue`、`frontend/src/services/feedback-receipts.ts` | 旧记录保留已有回复；404 仅说明当前环境无法关联，不误报团队删除；401/服务故障保持原提示 |
| 构建依赖 | `requirements.txt`、Windows 构建环境 | A 新增 `tzdata` 和相关模块随功能进入；本轮 B 后台适配无新三方依赖或额外服务 |

启动配置由整合入口统一管理：`A_B_TRANSPORT=local`、同一 `B_BATCH_REGISTRY`；正常软件入口默认开启 B 来源补充。核对 `AUTO_GRAPH_SYNC` 与 C/Neo4j 可用性。只有独立 HTTP 部署才需 B 服务端登录配置，不能把云反馈团队密码当作 A/B 内部配置。

### 4.3 前端与权限范围说明

本轮 A/B 适配不重构前端、不新增普通用户配置步骤。独立的旧反馈提示修复已完成，不能继续列为待开发：浏览器历史记录在当前服务返回 404 时保留内容、状态及上次回复，说明可能属于不同数据目录/安装环境；无法关联期间隐藏依赖该本机记录的操作，刷新恢复关联后恢复使用。细节及复用方法见 `deploy/cloudbase/ri-feedback-api/BUGFIXES.md` CF-11。

云反馈和团队账号沿用此前实现，与 A/B 论文交接分开。合并不需要重新创建腾讯云表或重建管理员账号。本次也没有实现各安装端公共知识自动同步。

## 5. 接口与版本对照（整合参考）

| 内容 | 字段/接口 | 含义 |
| --- | --- | --- |
| 交接文档 | `a-paperinput/1`、`batch_id`、`batch_code`、`items`、数量字段 | 原接收契约不变，核心论文必须合法 |
| A 批次版本 | 文档 `batch_revision`；状态 `a_batch_revision` | A 固定的批次版本，不是 B 全局知识版本 |
| B 写入版本 | 批次状态整数 `revision` | 接收/撤回的并发版本，不是 effective 的字符串 revision |
| 交接指纹 | `handoff_digest` | 完整交接文档指纹，供 A 对账 |
| 输入集合版本 | `snapshot_revision` / `input_snapshot_revision` | 当前有效输入集合版本 |
| 有效知识版本 | `knowledge_revision` / effective `revision` | D 发布的 `effective-<revision>` 依据，报告与 C 按此对齐 |
| 报告自身版本 | `knowledge-report/1.revision` | 报告内容指纹，不能代替知识版本 |
| B 报告附件 | `/api/admin/knowledge/report-export` | A section 外层 revision 取 `scope.knowledge_revision`，paper_ids 取 `scope.paper_ids` |
| B 可用状态 | `/api/admin/knowledge/batches/readiness` | 看 `results.available`，来源 partial/interrupted 不等于知识不可用 |

HTTP 写入保留管理员会话和 CSRF；A 调用方自动提供 `acknowledge_switch=true`，不要求用户手填。HTTP 200 中业务 `status=failed` 仍不是接收成功，A 最新 send 已检查业务状态。

## 6. 验证证据与尚未完成的范围

以下分批结果有重复覆盖，**不相加为独立用例总数，不当作第二轮独立测试或全链路验收**：

| 检查 | 已有证据 |
| --- | --- |
| 第一批 B 接收/来源适配 | 26 项离线检查通过：A 注释复用、重复请求避免、批次去重、撤回恢复、无效可选来源不阻断 |
| 报告契约 | 读取 A 的纯校验函数，配合真实 B 模块，6 项通过；小样本 `2 → 3 → 2 → 0`；允许无 C 的 A+B、允许仅 A、历史冻结及错配版本拒绝 |
| 已有报告/来源用例复用 | 5 项通过，含历史 A 文件 `20 → 30 → 20 → 0`、时间戳不改版本、来源失败/中断仍可用、撤回恢复 |
| 后台补来源改动 | 原批次 API/报告/来源 25 项通过；后台专项当前 4 项通过，覆盖本地触发、共享任务、自动恢复及退避 |
| 发布独立性 | 故意阻塞外部查询，真实 D 同步循环仍向模拟 C 发布；补充改变有效知识后自动再次发布。不是实际 Neo4j 验证 |
| 独立反馈提示修复 | 回执 7 项通过，前端类型检查和构建通过；真实页面仍待运行新版源码确认 |

本轮没有启动 A 最新采集/worker，没有请求真实 OpenAlex/Papers with Code 或腾讯云，也未改现有业务账本及安装数据。尚未完成完整 A 最新任务→B→真实 C/Neo4j 联调、跨电脑、旧数据升级和新版安装包验证。

可复用检查（使用独立临时目录，不操作运行中的账本）：

```powershell
python -m scripts.knowledge_builder.verify_ab_report_contract --a-ref origin/data-pipeline
python -m pytest server/tests/test_source_preparation.py -q --basetemp .cache/ab-source-handoff-check
python -m unittest tests.knowledge_builder.test_batches_api tests.knowledge_builder.test_report_api tests.knowledge_builder.test_batch_sources
```

报告契约结果默认写 `.cache/ab-handoff-checks/report-contract.json`，包含 A/B 检查版本和范围。反馈修复复用命令见 CF-11。测试无需真实账号或云额度。

## 7. 后续分工与整合后最小检查

- **组长**：决定最终分支整合方式，重点核对第 4 节配套内容与兼容要求。
- **B 负责人**：继续负责 A/B 契约和必要测试，不将测试责任转交组长。
- **安装包**：本轮不重复打包；后续确认整合代码和新增依赖后，再安排安装版验证。

沿用 `reports/week_five/personal_finish/testing/第二轮独立测试计划.md`，不另建重复计划。本轮简单开发验证仅作为可复用证据，不将第二轮状态改成完成。先按 G1 固定基线与断言映射；整合后优先 G4 的真实交接、撤回及 B/C 发布，再按原计划补 G2 页面、G3 安全/异常、G5 非功能/兼容及 G6 收尾缺口。

整合后的最小链路：

1. 正常启动 A worker 和 D/B，确认同一账本，不手工建交接任务。
2. 导入一小批论文，核对自动接收、论文范围和回执；重放不重复新增。
3. 核对 A 来源复用及 B 自动补缺失来源；补取未完成时已有知识仍可读和发布。
4. A 撤回第二批，确认通知自动到 B，独有论文退出、共有信息保留或恢复。
5. 核对 D 自动发布同一有效知识 revision 到真实 C；补充改变知识后自动更新，不用手动发布代替验证。
6. 生成 A+B 报告，缺少 C 时仍有明确可用章节；后续输入变化不改历史冻结内容。
7. 出新 Windows 包时检查 EXE worker 启动和相同数据目录重启，不能用旧包代表本轮结果。

## 附：后台调度细节（不影响主流程）

B 后台约每 10 秒发现账本变化。缺失来源连续无进展时渐进退避，首次约 5 分钟，随后 10、20、40 分钟，最长 1 小时；新输入或有效进展恢复较短间隔，来源补全后重置。间隔状态只在当前进程内，重启重新检查，不增加数据库或人工操作。关闭时停止安排后续请求，已发出的请求仍按原超时结束。

正常入口 `Settings.from_env()` 默认开启 `B_AUTO_SOURCE_ENRICHMENT`；直接构造 Settings 的测试默认关闭以避免无意联网。`AUTO_GRAPH_SYNC` 与来源补充独立，离线模式继续尊重原来源客户端行为。没有受管理批次时不自动抓取演示语料。
