# A/B 自动交接核对与本轮适配

日期：2026-11-28。目标：复用已有自动流程，减少手工交接及重复联网；局部适配，不重构或整体合并。最终分支合并仍请组长统一处理。

## 1. 已确认的版本关系

已执行 `git fetch origin`，当前分支为 `deploy/windows-installer`，检查起点 `b285043`。当前基于 `graph-front-v4@b6923d8`，已有早期 A、B knowledge-week4、C graph-query-week4 及 D 整合；A 的 `origin/data-pipeline@9cca61d` 仍有以下 3 个提交未进入当前历史：

- `5be1ca5`：第四周交接任务与报告包。
- `bda9d06`：第四周交付说明。
- `9cca61d`：自动知识交接与手动在线采集。

本轮没有执行 merge、cherry-pick 或启动 A 的采集/worker，没有调用腾讯云或真实 OpenAlex，也没有改变现有账本和安装数据。A 文档中的“尚未推送”是旧记录，现以远程提交记录为准。

## 2. 流程结论

A 最新代码已经包含“批次成功 → 持久化交接任务 → worker 交给 B → 保存回执”，以及失败退避重试、启动补扫、撤回通知和对账。正常操作不需要再增加手工交接按钮。

B 已有批次幂等接收、按论文 ID 合并、撤回恢复、有效知识与报告导出。补充来源不齐时仍应允许有效规则结果继续被读取及发布；C 发布由现有 D 同步流程处理，不要求用户再次逐阶段确认。数据本身无效或版本不一致仍不冒充成功，但不能用可选字段缺失阻塞全部流程。

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

## 4. 本轮代码范围与合并方法

1. `server/api/knowledge_batches.py`：只增加批次身份字段，供 A 对账、恢复丢失回执，不改原路由或操作要求。
2. `src/knowledge_builder/batch_sources.py`：复用 A 分支已有适配，将有效批次注释作为来源种子，优先于旧缓存，减少重复请求。
3. 新 `src/knowledge_builder/upstream_openalex.py`：复用 A 的字段匹配方法；补可选注释非阻塞读取，采用账本内容指纹核对后直接选择当前批次，避免每次读取再做一轮全量知识抽取。
4. 两份原 B 测试文件增加针对性断言，不改前端、不改 A 数据库/worker，也不新增三方依赖。

**合并差异注意**：A 的原补丁还会在 `batches._prepare` 中校验全部附加注释并拒绝整批。本轮不采用这一段：核心 PaperInput 继续沿用原校验，但无效可选注释不应让有效论文无法交接/发布。`upstream_openalex.annotations` 保留 strict 调用能力，B 的来源读取显式使用非阻塞方式。组长合并不能再直接覆盖回 A 原有整批拒绝策略。

A 的启动补丁需要合入 `A_B_TRANSPORT=local`、指向同一账本的 `B_BATCH_REGISTRY`，但不要覆盖当前 `module_command`。A 新增 `tzdata` 依赖需随其功能合并后进入构建环境；当前这轮 B 适配不引入它、不安装依赖。

前端 `WorkflowCenterView.vue`、`services/workflows.ts` 采用 A 配套自动交接展示时，保留当前云反馈、账号页与登录改动。`server/api/main.py` 的工作流路由注册和当前团队认证/MIME 修复需共存，不能整文件替换。

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
