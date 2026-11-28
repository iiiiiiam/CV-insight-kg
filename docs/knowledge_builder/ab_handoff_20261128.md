# A/B 自动交接核对与本轮适配

日期：2026-11-28。本轮适配及核对提交 `0d902d7`、`7216678` 已推送至 `deploy/windows-installer`；本页后续细化以当前提交状态为准。目标：复用已有自动流程，减少手工交接及重复联网；局部适配，不重构或整体合并。最终分支合并仍请组长统一处理。

## 1. 已确认的版本关系

已执行 `git fetch origin`，当前分支为 `deploy/windows-installer`，检查起点 `b285043`。当前基于 `graph-front-v4@b6923d8`，已有早期 A、B knowledge-week4、C graph-query-week4 及 D 整合；A 的 `origin/data-pipeline@9cca61d` 仍有以下 3 个提交未进入当前历史：

- `5be1ca5`：第四周交接任务与报告包。
- `bda9d06`：第四周交付说明。
- `9cca61d`：自动知识交接与手动在线采集。

本轮没有合并其他分支或启动 A 的采集/worker，没有调用腾讯云或真实 OpenAlex，也没有改变现有账本和安装数据。A 文档中的“尚未推送”是旧记录，现以远程提交记录为准。

## 2. 流程结论

A 最新代码已经包含“批次成功 → 持久化交接任务 → worker 交给 B → 保存回执”，以及失败退避重试、启动补扫、撤回通知和对账。正常操作不需要再增加手工交接按钮。

B 已有批次幂等接收、按论文 ID 合并、撤回恢复、有效知识与报告导出。补充来源不齐时仍应允许有效规则结果继续被读取及发布；C 发布由现有 D 同步流程处理，不要求用户再次逐阶段确认。数据本身无效或版本不一致仍不冒充成功，但不能用可选字段缺失阻塞全部流程。

### 2.1 实际自动执行顺序

1. 用户选择正式导入或手动在线采集。在线采集发现新论文后进入正式批次处理；没有新增论文时，A 标记本次完成，不制造空交接任务来切换 B 输入。
2. A 将核心论文、来源信息和批次版本入库，成功后创建持久化交接任务。补扫负责恢复遗漏；不需要用户再点击“交给 B”。
3. A worker 根据接入方式调用 B。B 接收保存批次，重复同内容不会重复新增，随后所有阅读/导出都采用当前有效批次集合。
4. B 的知识结果通过现有统一模块按需生成；不是必须先启动一个新的 B worker 或等待外部 API 全成功。已冻结的 A 注释直接作为来源输入。
5. D 开启自动图谱同步时，后台定期读取 B effective，导入并发布对应 C 批次；无变化时不重复发布。C 暂不可用时保留错误并后台重试，不阻止 B 阅读和导出。
6. 报告单独按创建时的范围冻结。C 尚未准备好时，A 最新页面可自动生成 A+B 报告；缺少章节写入报告，不把未取得的统计伪装成已有数据。

以上第 2、3 步 A worker 的实现来自 A 分支代码审查，第 3、4 步 B 行为有本轮离线验证，第 5 步是现有 D 机制；不能把代码具备上述路径写成已完成本机整条链联调。

### 2.2 两种接入方式必须区分

| 方式 | 调用路径 | 必要条件 | 外部来源补充 |
| --- | --- | --- | --- |
| 整合运行 `local` | A `app/delivery.py` 直接调用 `BatchRegistry` | A 与 D/B 使用同一个实际 `B_BATCH_REGISTRY`；A worker 在运行 | 直接复用 A 注释；B 后台自动发现账本变化，补取缺失来源 |
| 分离运行 `http` | A 登录原 B 接口并提交批次 | 正确的 B 地址、服务端账号、会话/CSRF；A/B 可连通 | HTTP 接收成功后自动安排缺失来源补充，已有来源不重复抓取 |

**本轮已补齐自动化缺口**：本地直连虽不经过 HTTP 接收路由，但现在由 B 随软件启动的后台任务发现账本变化，自动复用 `BatchSources.prepare` 补取缺失来源。HTTP 接收与本地检测共用同一个任务协调器，不重复启动任务。已有知识立即可读、可导出，由现有 D 同步发布；不等待来源查询完成。补充内容改变有效知识版本后，D 自动发布新版本。来源失败保留已有结果，后台稍后重试，不要求管理员点按钮。不改 A 接收事务，不另建服务或任务系统。

因此不能再笼统承诺“B 不会访问 OpenAlex”：A 注释有效或已有缓存时不重复请求；缺失来源的 prepare 阶段仍可能访问 OpenAlex/Papers with Code。阅读、依据查询和导出本身不发这些请求。腾讯云反馈是独立服务，不参与论文交接。

## 3. 逐项检查与责任

| 项目 | 本次确认与处理 | 下一步责任 |
| --- | --- | --- |
| A 自动交接和失败恢复 | A 分支已有，不重写、不另加任务框架 | 组长合并 A 工作流、worker 与配套页面 |
| B 批次身份 | 补 `batch_id`、`handoff_digest`、`a_batch_revision`，保留旧字段 | 本轮 B 适配已完成 |
| A 来源字段复用 | B 读取当前有效批次的 `source_annotations`，不重复请求已有 OpenAlex；新批次优先，撤回恢复旧信息 | 本轮 B 适配已完成 |
| 可选来源异常 | 不可用/不匹配的注释不参与知识补充；保留合法核心论文和规则结果继续导出 | 合并时保留本轮非阻塞策略，见下文 |
| 报告知识附件 | A 支持原 `knowledge-report/1` / `knowledge-effective/1.0`，校对论文范围及知识版本；B 协议不改 | 完整合并后做一次离线报告贯通 |
| C 自动发布 | D 现有同步仍负责 B → C，不新增人工按钮 | 整合后最小发布链验证，不把本轮离线检查当作已发布 |
| 启动与冻结程序 | 当前 Windows 用 `module_command('app.worker')`；A 分支改为 `sys.executable -m app.worker` | 合并必须保留当前冻结启动机制，补入 A 的配置即可 |
| 云反馈及团队账号 | 与本轮独立，不改现有功能或权限 | 合并 server/api/main.py 等重叠文件时保留两侧内容 |

## 4. 本轮代码范围与整合注意点

1. `server/api/knowledge_batches.py`：增加批次身份字段，供 A 对账、恢复丢失回执；来源任务改为与本地检测共用协调器，原路由和操作要求保持兼容。
2. `src/knowledge_builder/batch_sources.py`：复用 A 分支已有适配，将有效批次注释作为来源种子，优先于旧缓存，减少重复请求。
3. 新 `src/knowledge_builder/upstream_openalex.py`：复用 A 的字段匹配方法；补可选注释非阻塞读取，采用账本内容指纹核对后直接选择当前批次，避免每次读取再做一轮全量知识抽取。
4. 新增 `server/application/source_preparation.py`，在 `server/api/main.py` 生命周期启动与关闭后台检测；`knowledge_feedback.py` 传递同一协调器，`settings.py` 的正常软件入口默认开启。来源处理支持在关闭时停止安排后续请求。
5. 原 B 测试增加针对性断言，新增 `server/tests/test_source_preparation.py` 验证后台补取与自动发布。不改前端、不改 A 数据库/worker，不新增三方依赖。

**合并差异注意**：A 的原补丁还会在 `batches._prepare` 中校验全部附加注释并拒绝整批。本轮不采用这一段：核心 PaperInput 继续沿用原校验，但无效可选注释不应让有效论文无法交接/发布。`upstream_openalex.annotations` 保留 strict 调用能力，B 的来源读取显式使用非阻塞方式。组长合并不能再直接覆盖回 A 原有整批拒绝策略。

A 的启动补丁需要合入 `A_B_TRANSPORT=local`、指向同一账本的 `B_BATCH_REGISTRY`，但不要覆盖当前 `module_command`。A 新增 `tzdata` 依赖需随其功能合并后进入构建环境；当前这轮 B 适配不引入它、不安装依赖。

前端 `WorkflowCenterView.vue`、`services/workflows.ts` 采用 A 配套自动交接展示时，保留当前云反馈、账号页与登录改动。`server/api/main.py` 的工作流路由注册和当前团队认证/MIME 修复需共存，不能整文件替换。

### 4.1 接口与版本字段对照

| 内容 | 字段/接口 | 用途与容易混淆处 |
| --- | --- | --- |
| 交接文档 | `a-paperinput/1`，`batch_id`、`batch_code`、`items`、数量字段 | 原契约不变；核心论文不合法仍不能当作成功接收 |
| A 版本 | 文档 `batch_revision`；状态 `a_batch_revision` | A 固定的批次版本，不等于 B 全局知识版本 |
| B 写入版本 | 批次状态整数 `revision` | 接收/撤回时使用当前值；不是 report/effective 的字符串 revision |
| 原文档指纹 | `handoff_digest` | 完整交接文档的 fingerprint，包含附加字段，供 A 对账 |
| 合并输入版本 | `snapshot_revision` / `input_snapshot_revision` | A 回执及三阶段核对的 B 输入集合版本 |
| 可用知识版本 | `knowledge_revision` / effective `revision` | D 发布对应 `effective-<revision>`；报告与 C 应按此对齐 |
| 报告自身版本 | `knowledge-report/1.revision` | 报告内容指纹，与知识 revision 含义不同；不能填进 A section 外层 revision |
| B 报告附件 | `/api/admin/knowledge/report-export` | A section 外层 revision 取附件 `scope.knowledge_revision`，paper_ids 取 `scope.paper_ids` |
| B 可用状态 | `/api/admin/knowledge/batches/readiness` | 核对 `results.available`；来源 partial/interrupted 不等于知识不可用 |

HTTP 批次写入使用原管理员会话与 CSRF，调用方自动提供 `acknowledge_switch=true`，不要求使用者每次手填确认。HTTP 200 下业务 `status=failed` 仍表示批次未生效；A 最新 send 已检查业务状态。`accepted` 仅证明 B 接收落盘，不证明可选来源全部完成或 C 已发布。

### 4.2 失败与恢复边界

- B 已接收但 A 未记下回执：A 对账可凭批次身份与指纹补回，不要求重新导入所有论文。
- 网络/服务暂不可用：A 自动退避，预算耗尽后保留任务和原因，才提供例外重试；B 原有有效结果不清空。
- A 撤回：自动排通知；B 独有论文退出、共有论文保留或恢复先前版本，全部撤回后为零，不回退演示样本。
- B 独立撤回、相同编号不同来源、补交旧版本可能覆盖新版本：A 保留冲突供核对，不把他人状态强行覆盖。这是明确冲突的例外，不是正常流程必须人工审批。
- 来源缺失/校验不匹配：忽略不可用的可选注释并沿用可用来源与规则结果；核心论文和存档完整性检查仍保留。
- C 暂未发布：B 功能继续；图谱发布重试与报告缺章处理分开，不以 C 暂不可用阻塞所有操作。

### 4.3 组长整合时的文件与配置清单

| 范围 | 重点文件 | 整合要求 |
| --- | --- | --- |
| A 自动任务 | `app/auto_handoff.py`、`delivery.py`、`workflow_tasks.py`、`worker.py`、`formal_batches.py` | 采用 A 配套实现，任务创建、worker 执行和回执持久化共同接入；避免恢复已取消的手工交接入口 |
| A 在线采集 | `app/online_collection.py`、相关 API/模型 | 新论文入库后复用正式批次处理；无新增时正常完成，不用空批次切换 B |
| B 状态与来源 | `server/api/knowledge_batches.py`、`batch_sources.py`、`upstream_openalex.py` | 保留新状态字段、有效注释复用与撤回恢复；保留可选来源非阻塞策略 |
| B 后台来源补充 | `server/application/source_preparation.py`、`server/api/main.py`、`server/configuration/settings.py`、`server/api/knowledge_feedback.py` | 保留生命周期中的自动检测及路由共享的同一个协调器；不要恢复成仅 HTTP 接收触发，也不要让图谱发布等待外部查询 |
| 源码/冻结启动 | `server/run_a.py`、`server/run_local.py`、`server/process_command.py` | 接入 A 的 local transport 和同一账本；保留源码/EXE 两种启动命令，不能直接覆盖成普通 Python 启动 |
| D API 与任务页面 | `server/api/main.py`、`server/api/workflows.py`、`WorkflowCenterView.vue`、`services/workflows.ts`、导航及路由 | A 配套接口/状态展示与当前团队认证、云反馈、JS MIME 修复共存；不整文件替换 |
| 构建依赖 | `requirements.txt`、Windows 构建环境 | 核对 A 的 `tzdata` 及新增模块；当前 B 适配不要求新依赖或额外服务 |

维护者在整合入口统一设置 `A_B_TRANSPORT=local`、同一 `B_BATCH_REGISTRY`，并核对 `AUTO_GRAPH_SYNC`、C/Neo4j 可用性；这些是服务启动配置，不应要求普通用户填写。HTTP 独立部署才配置 B 服务端账号，不能将云反馈团队密码混当 A/B 的服务端配置。

## 5. 简单功能验证及复用

26 项离线检查通过，复用批次/来源测试并增加 3 项针对性用例，未跑全套独立测试，不消耗云额度：

- A 的注释直接复用，OpenAlex 模拟请求次数为 0；Papers with Code 不可用时仍有结果。
- 同论文新批次的注释覆盖旧缓存，撤回后恢复旧注释。
- 无效可选注释不阻止核心论文接收、阅读与 effective 导出。
- HTTP 批次状态返回真实原文档指纹与 A 版本；来源部分失败时 `results.available=true`。
- 复用幂等、重复论文合并、撤回与全部撤回后空集合检查。

在项目 Python 环境执行以下模块即可复用；临时文件放项目 `.cache/ab-handoff-checks`，不要用正在运行的账本：

```powershell
python -m unittest tests.knowledge_builder.test_batch_sources tests.knowledge_builder.test_batches
python -m unittest tests.knowledge_builder.test_batches_api.BatchAPITests.test_a_handoff_identity_and_missing_optional_source_do_not_block_export tests.knowledge_builder.test_batches_api.BatchAPITests.test_import_dedup_withdraw_updates_reading_and_export_and_empty_stays_empty
```

本轮未运行 A 最新 worker 的联合 HTTP 流程、真实 Neo4j 发布、跨电脑或新版安装包验证，不能将 26 项表述为整合验收。

## 6. 后续安排

先把本轮 B 适配及上述合并注意点交给组长；你继续负责 A/B 契约及整合后必要测试，不把这项责任转交给组长。待完整 A 代码进入整合环境后，复用少量真实文件验证自动接收、重复不新增、撤回恢复和报告版本对齐。只有需要确认冻结启动/新增依赖时才再打包，不因文案调整重复出包。

独立待办：旧浏览器反馈在当前安装数据环境不存在时，改为明确的历史缓存/环境提示，不用笼统“未找到反馈”误导用户。本轮不改该前端，后续随其他小问题独立开发、独立提交。


## 7. 第二批核对结果：撤回、报告与自动继续

已在第一批提交 `0d902d7` 后继续核对 A 的 `app/delivery.py`、`app/report_bundle.py`、`server/api/workflows.py` 与任务中心，未发现需要在当前 B 新增业务流程的缺口，故没有扩展生产代码。

- **撤回**：A 负责同事务排队撤回通知，worker 自动交给 B；B 按既有批次撤回规则恢复其他有效输入。来源注释也随选中批次恢复。本轮未把 A 工作流引入当前分支。
- **任务状态**：A 的三阶段核对使用 B `readiness.results.available`，不是以来源 `complete` 作为继续条件。B 在来源 pending/partial/interrupted 时仍可 available=true；无需管理员先补齐来源再继续。C 实际发布由 D 现有后台同步负责。
- **报告**：A 的 B section 外层 `revision` 应取 `report.scope.knowledge_revision`，不是报告自身 `report.revision`。A 最新适配已经正确这样做，当前 B 无需另改协议。
- **缺少 C**：A 当前任务中心在 C 对应版本尚未准备好时自动改为生成 A+B 报告；A 报告打包允许缺少 C，未增加“全部成功才允许生成”的人为门槛。此项来自代码核对，不冒充已跑完整报告 UI。
- **一致性边界**：不能把不同论文范围或不同知识版本拼成同一报告；这是内容正确性要求，不影响在明确缺少某提供方时先生成可用章节。

新增可复用的离线契约核对工具（只读取 Git 中 A 的两个纯报告校验函数，用真实 B 模块生成附件；不运行 A 的模块初始化、数据库或 worker）：

```powershell
python -m scripts.knowledge_builder.verify_ab_report_contract --a-ref origin/data-pipeline
```

结果默认保存 `.cache/ab-handoff-checks/report-contract.json`。本次 A 精确提交为 `9cca61d827be0677121ac562a5f4d0f6d187433d`，B 检查基线 `0d902d7`；小样例论文数 `2 → 3 → 2 → 0`，六项检查通过：当前 B 附件匹配 A、允许无 C 的 A+B、允许仅 A、撤回恢复原报告版本、历史冻结内容不变、拒绝错配版本。它只检查报告契约，不声称 worker/HTTP/数据库整体联调成功。

另复用 5 项已有测试全部通过：真实历史 A 文件的 `20 → 30 → 20 → 0` 报告变化、时间戳不改变内容版本、来源部分失败仍可读、来源中断与结果可用分离、撤回恢复旧输入。没有增加全量测试或真实联网。

## 8. 可同步给组长的检查点

B 适配 `0d902d7` 与契约核对 `7216678` 已推送至 `deploy/windows-installer`。B 负责人继续跟进 A/B 契约与必要测试；最终整合与合并方式由组长决定，本文只列兼容要求，不规定 Git 合并操作。可同步：

> 我继续核对了 A 最新 data-pipeline 与当前 B 的交接，已补 B 的批次身份和 A 来源字段复用；可选来源失败不会卡住有效知识导出。撤回、报告附件与就绪状态的契约核对已通过，A 的报告页已有 C 暂不可用时先生成 A+B 的处理，因此这部分没有再增加人工步骤。当前仍未合并整套 A 工作流，也未重打包。最终合并时麻烦保留本轮 B 适配、可选注释非阻塞策略，以及 Windows 的 module_command worker 启动方式；A 的自动交接配置和配套任务页面需要共同接入，并保留 B 新增的后台来源检测与共用协调器：先发布已有知识，自动补来源，有效知识变化后再自动发布。具体重叠文件、26 项第一批检查、5 项复用检查和离线报告契约结果见 docs/knowledge_builder/ab_handoff_20261128.md。完整 worker、C 发布和整合包验证仍等整合环境再做，我会继续跟进 A/B 这部分。


## 9. 本次复查结论及整合后最小检查

截至本次已审查代码与离线证据，未发现新增的 **B 核心接收/合并/撤回/报告契约阻断缺口**。不是“整个 A/B/C/D 已完全无问题”：local 模式的来源自动补取缺口已在本轮补齐，并通过模拟 C 的自动发布验证；完整 A worker、真实 C/Neo4j 发布和现有数据升级仍未联调。本轮只增加必要后台协调，不重构整体架构。

整合后在独立账本和数据库中做以下最小检查即可，优先复用离线文件，不批量联网：

1. 使用正常整合启动入口，确认 A worker 正常运行，A 与 B 指向同一账本；无需手动创建交接任务。
2. 导入一小批合法论文，等待 A 自动任务完成，检查 B 论文范围及新对账字段；重复相同任务不重复新增。
3. 用 A 已冻结的 OpenAlex 信息查看依据，确认没有相同论文的重复 OpenAlex 请求；来源暂不可用仍可读 B effective/报告。
4. 从 A 撤回第二批，确认 B 自动收到通知、共有论文保留/恢复、独有论文退出；不手动再撤一次 B 来掩盖通知问题。
5. 核对 D 自动发布同一知识 revision 到 C；C 不可用时 B 可用，C 恢复后后台能继续发布。不要用手工发布替代自动发布测试。
6. 生成一次 A+B 报告；C 对应版本未就绪时仍可生成已有章节。随后导入/撤回不改变历史报告的冻结内容。
7. 若出 Windows 包，再检验 EXE 启动 worker 和相同数据目录重启；此前 11 月 27 日安装包不包含本轮 A/B 新适配，不能直接用旧包当本轮结果。

B 负责人继续推进接入核对和必要测试；组长负责最终整合决策。何时同步、如何合并由团队协商，本文不要求执行指定 Git 合并方案。旧浏览器反馈环境提示继续独立排期、独立提交，不因文案变化重复打包。


## 10. 本轮补充：先发布，后台自动取来源

正常软件启动后自动执行，普通用户无需配置或手动触发：

1. A 写入 B 账本；已有 A 注释直接使用，核心规则知识立即可读取和导出。
2. B 后台每 10 秒检查受管理批次，发现新版本或待补来源后自动补取。HTTP 接收也可立即安排同一个任务；并发触发共用执行槽。
3. 已有有效来源和缓存不重复请求。缺失的 OpenAlex/Papers with Code 使用原来源客户端及匹配规则；不是保证第三方一定能返回数据。
4. 现有 D 自动发布独立运行，不等待外部来源。补充产生有效知识变化时，知识 revision 改变，D 自动发布更新；只有请求时间或无效信息变化时不制造无意义版本。
5. 来源部分失败或任务中断后，已有知识保留，同一输入首次约 5 分钟后自动重试，连续无进展按 10、20、40 分钟递增，最长 1 小时；新输入或补取有进展时恢复较短间隔。新输入可在下一轮检测时处理；重启软件也会重新检查已有账本。关闭时停止安排后续来源请求，已发出的请求仍按原超时结束。

`Settings.from_env()` 默认启用 `B_AUTO_SOURCE_ENRICHMENT=true`，不要求用户添加环境变量；测试直接构造 Settings 时默认关闭，避免无意联网。`AUTO_GRAPH_SYNC` 只控制图谱同步，来源补充独立执行。只有未启用离线模式且来源确实缺失时才会产生外部请求。没有受管理批次时，不自动抓取演示语料。

本轮复用原批次 API、来源和报告检查 **25 项通过**；新增自动化检查 **3 项通过**，均为离线模拟，不消耗云额度：

- 直接写账本，不调用 HTTP 接收或手动补充接口，也会自动开始缺失来源查询；A 已提供的 OpenAlex 不重复请求。
- 故意阻塞来源查询期间，真实 D 自动同步循环仍向模拟 C 完成首次发布；释放查询后，有效知识版本变化，D 自动再次发布。
- 部分来源失败后自动重试；HTTP 与本地检测不会重复启动任务；没有受管理批次时不联网。

可复用命令（在项目 Python 环境，临时目录使用新的独立路径）：

```powershell
python -m pytest server/tests/test_source_preparation.py -q --basetemp .cache/ab-source-auto-check
python -m unittest tests.knowledge_builder.test_batches_api tests.knowledge_builder.test_report_api tests.knowledge_builder.test_batch_sources
```

这证明后台协调和发布之间的自动化契约，不替代完整 A worker 与真实 C/Neo4j 的整合验证。11 月 27 日旧安装包不包含本轮代码；本轮未重新打包。


### 后续独立优化与测试安排（2026-11-28）

- B 来源重试改为有上限的退避，避免永久缺失来源每 5 分钟反复查询。新输入不受旧输入长间隔阻挡；有效来源补全后重置退避。间隔状态保存在当前进程内，重启自动重新检查，不增加数据库或用户配置。
- 旧反馈历史提示另行提交，见 `deploy/cloudbase/ri-feedback-api/BUGFIXES.md` CF-11；不属于 A/B 来源处理改动。
- 仍沿用 `reports/week_five/personal_finish/testing/第二轮独立测试计划.md`，本轮开发检查不冒充第二轮已完成。已有批次/来源/报告检查复用，不重跑全量；合并后先按 G1 固定基线与断言映射，再优先完成 G4 真实交接、撤回及 B/C 同版本发布。G2 页面代表性检查、G3 隔离故障检查、G5 安装兼容及计划中的其他专项按原范围补缺口，不新建一套重复计划。
- 当前可独立完成修复的离线验证；真实 A worker、C/Neo4j、跨电脑及新版安装包验证待对应整合环境。无需为了这两项小改动立即重打包。

本次独立修复验证：反馈回执 7 项通过、前端类型检查和构建通过；B 后台来源 4 项通过（复用 3 项并新增退避用例）。全部为本机离线开发检查，未运行云请求、未重打安装包，真实页面效果仍待使用者运行新版源码确认。
