# B 本周进度与团队交接

> 2026-11-28 更新：本页保留第四周历史交付；最新 A/B 版本差异、局部适配和给组长的合并注意点见 [A/B 自动交接核对](ab_handoff_20261128.md)。不能继续以本页“尚需 A/D 明确”为最新状态。

最近核对：2026-11-21。接口、命令与当前 `knowledge-week4` 工作区一致；提交和推送状态仍以 Git 实际状态为准。

## 1. 当前基线与范围

第四周 B 在 `knowledge-week4` 开发，起点为已整合 A/B/C/D 的 `graph-front-v3@20994e6`。旧 `knowledge-topics` 成果已进入整合版，不需要再次盲目合并。当前文档取代第三周“尚未合并、A/C 尚未验证”的旧状态描述；不据此声称本周改动已经 commit、push 或由 D 完成验收。

本轮主要修改 B 核心、B 路由与读取适配和 B 文档；未改 A 数据库、C 发布逻辑、D 公共页面，也未安装 Docker/Neo4j。第四周完整 FR 定义尚未定稿，本轮按已给分工实现可独立交付部分。

## 2. 已有能力，本周继续复用

- 知识阅读、原文依据与高亮、单篇关联图、浏览器个人调整。
- 公共反馈的改名、排除、补词、撤回处理；个人调整不进入公共 effective。
- 17 个研究子方向及“其他”，标题关键词／方向组合筛选。
- `a-paperinput/1` 接收、按 OpenAlex ID 合并、整批校验、幂等、失败记录、成功批次内容冻结和整批撤回。
- 撤回后独有论文退出，共有论文保留，必要时恢复此前输入和对应来源补充；旧公共纠错只对匹配输入与候选生效。
- 来源补充优先复用本地语料／缓存，缺少来源时保留规则结果，可重试；网页读取与导出不联网。
- `knowledge-effective/1.0` 完整结果、原文证据、内容版本及 automatic/human_confirmed/human_corrected 区分。管理员补词产生的关系仍为自动生成。
- D 已有按 B effective 自动导入／发布到 C 的实现。本轮未修改或运行此自动发布流程。

旧第三周交接已有后续证据：A 的 `docs/week3-a.md` 记录独立 B HTTP 验证 20→30→20；C 的 `docs/graph/week3-handoff.md` 记录隔离真实 Neo4j 验证 20→30→20→0。它们不等于本机当前统一页面已经在线验收。

## 3. 本周新增

| 内容 | 输入与输出 |
| --- | --- |
| 作者知识标签 | 从一份当前有效快照的作者与知识关系生成 topic/method/task/dataset 标签；按来源 ID 汇总，缺 ID 留在单篇范围；每个标签保留支持论文和四段证据见证 |
| 报告知识附件 | 完整 effective、作者标签、知识质量事实统一绑定论文范围与知识版本；不另做报告任务、文档或 ZIP |
| 质量摘要 | 统计有效实体／关系、证据、来源 ID 缺失、摘要缺失、自动／人工状态；准确率未知，不拿覆盖率冒充 |
| B 读取接口 | 匿名作者标签、管理员报告 JSON 下载；支持 expected_revision、版本响应头；读取期间检测到变化返回 409 |
| 离线生成 | 从已有 effective 文件生成知识报告，无需启动服务，不联网、不访问默认账本或发布到 C |
| B 状态交付 | readiness 明确区分来源补充状态和已验证可读取的结果；原 effective 下载补齐批次变化复核 |
| 抽取修复与性能 | 明确介绍为数据集／任务的名称不再一律算方法，指标与 benchmark 不强行当方法；多作者证据批量校验只复制一次原文上下文 |

标签的含义是“作者参与的论文涉及该知识”，不评价作者专长、贡献、影响力，不做共同作者或历史累计统计。所有内容和错误行为见唯一接口说明：[作者标签与报告知识契约](report_knowledge.md)。

新增入口：

- `GET /api/knowledge/author-tags`，与 B 原有知识页一样匿名读取。
- `GET /api/admin/knowledge/report-export`，沿用管理员会话，下载 `knowledge-report/1`。
- `GET /api/admin/knowledge/batches/readiness`，沿用管理员会话，查询 B 当前知识版本、来源补充状态和结果是否可读取。
- `python -B -m scripts.knowledge_builder.report_knowledge --effective path/to/effective.json --output path/to/report.json`。

现有 `GET /api/admin/knowledge/effective-export` 不变。报告中的 knowledge 才是 C 可接收的 effective 文件；不要把整个报告发给 C。

## 4. A 批次交接与状态边界

现有 B 管理员接口已可接收程序传入的完整 JSON，不限于网页选文件：

| 操作 | 接口及规则 |
| --- | --- |
| 读取账本与来源状态 | `GET /api/admin/knowledge/batches`，返回整数 revision、snapshot_revision、批次／失败列表、来源 pending/completed/partial/running/error |
| 接收批次 | `POST /api/admin/knowledge/batches`，`{revision, document, acknowledge_switch:true}` |
| 撤回批次 | `POST /api/admin/knowledge/batches/{batch_code}/withdraw`，`{revision}` |
| 重试补充来源 | `POST /api/admin/knowledge/batches/enrich` |

POST 使用已有管理员会话与 CSRF。B 不新增服务间密钥或后台任务框架；A/D 如需另一种认证或回调，应先共同明确契约。

- 接收回执 `accepted`：B 已原子保存批次，不代表外部来源全部补齐或 C 已发布。
- `unchanged`：相同批次幂等接收，没有新增论文。
- HTTP 200 且业务 `status=failed`：已记录失败，整批未生效；A/D 必须检查业务状态，不得当作成功。
- 来源 `running=true`：本进程正在补充；pending/partial/error 表达尚未处理、部分来源缺失或中断。该任务没有持久后台任务 ID；重启后可重试。
- 规则结果不必等待外部来源全部成功。成功读取 report/effective 才表示对应版本可获得；知识版本与 C 发布版本需另行核对。
- readiness 是 B 的聚合状态读取，经过实际 effective 构建和版本复核；partial/interrupted 也可以 results.available=true。publication=not_checked 明确保留 C/D 边界。D 可据此接三阶段页面，不必自行猜测 B 状态。

A 的撤回和 B 的撤回目前仍是独立操作。A/D 的一键交接协调、重试顺序、自动撤回通知及三阶段页面未由本轮替代开发。

## 5. 原演示样本与正式范围

当前代码仍是：首次成功接收前读配置中的演示样本；首次接收后切换到有效批次合并集合，不自动做“150＋新增”；全部撤回后为 0，不回退样本。实际演示数量取决于本机配置，默认固定清单可能为 20 篇。

没有新增一键迁移或改动运行中的账本。保留原 150 篇作为基线，还是统一由 A 正式批次提供，仍由组长决定。本周报告明确输出当前 B 的完整范围，不能据此推断 A 库或 C 已发布范围相同。

## 6. 给 A / C / D 的接入事项

| 成员 | 当前可用内容与仍需对齐的事项 |
| --- | --- |
| A | 可读取一次 report-export 保存知识附件，包含实体、关系、证据、作者标签及质量。负责报告任务、文件、manifest 和 ZIP；一键交接如何调用 B、如何在撤回后通知 B 尚需 A/D 冻结。 |
| C | effective 原格式未加字段。标签不改正式图、不做共同作者统计。报告统计请返回与 B knowledge_revision 对应的发布数据，避免不同快照混算。 |
| D | 作者标签接口可接入页面；报告下载沿用会话。三阶段页面应分别检查 B 接收回执、来源状态和 C 发布状态，不以 HTTP 200 代替整个流程完成。D 负责全系统联调与浏览器最终验收。 |

如组长之后明确更细的标签需求，优先调整独立标签规则版本，不改旧 effective 协议。引用数、历史趋势、共同作者和机构统计仍由 A/C 提供；本轮不猜测这些指标。

## 7. 验证与复现

使用已有 `insight-prototype` Python 3.11 环境，不安装新依赖。B 测试使用临时账本、临时反馈及离线／模拟来源；新增 API 测试明确关闭自动图谱同步。

```powershell
python -B -m unittest discover -s tests/knowledge_builder -t . -q
```

覆盖标签证据链、同名不同 ID、缺 ID、重复作者记录、关系排除、纠错与撤回、补词仍为自动、输入更新后旧纠错失效、旧输入恢复、来源变化、空结果、版本冲突、损坏存档、输出失败保留旧文件、离线 CLI 和 C 旧格式兼容。真实 A 两批文件先核对 SHA256，再验证报告 20→30→20→0 及恢复相同内容版本。

2026-11-21 提交前补齐旧 CLI 的 B_BATCH_REGISTRY 等配置读取和前后版本复核，避免命令行与网页因自定义账本不同而导出不同范围；增加配置账本接收后导出、全部撤回后导出空集合的回归测试。README、批次及 effective 说明也已补齐第四周入口，旧阶段记录已注明历史范围。

最新 B 全套测试共 231 项：226 项通过，5 项可选 Streamlit 原型 UI 测试因环境条件跳过。有一条已有 Starlette/httpx 弃用提示，无测试失败。新增用例包括真实数据集误分类回归、多作者校验效率、来源中断恢复、精确作者选取及 effective 下载期间的批次变化。

真实样例检查发现 OpenStreetView-5M 被旧 introduced_name 规则标为 method；现按明确 dataset 描述输出 dataset。修复的是通用规则，`text_signals` 升级为 explicit-names/0.2，不是给该论文硬编码答案。原 effective 协议未变，规则指纹与知识 revision 会随本轮代码更新，旧快照不原地修改。

初版离线报告在本机 `reports/week_four/verification_20261119/`，属于修复前历史样例；首次完整 HTTP 验收在 `reports/week_four/http_acceptance_20261119/`。2026-11-21 提交前已重新运行完整 HTTP 验收，最新结果在本机 `reports/week_four/http_precommit_20261121/`，14 项检查全部通过，四阶段为 20→30→20→0，临时服务已关闭。可执行 `python -B -m scripts.knowledge_builder.verify_delivery --output-dir reports/week_four/new-http-check` 复现，必须使用新输出目录。命令使用临时管理员／账本、随机本机端口、离线来源并关闭自动发布，完成后关闭自身服务。

收尾版已实际完成上述 HTTP 验收，14 项链路检查通过：真实 A 文件校验、20→30、重复批次幂等、改名影响标签／质量且不泄露私有反馈、排除关系移除支持、撤回反馈恢复版本、精确身份读取、effective 与报告版本一致、HTTP 200 失败回执不生效、撤回恢复旧输入、旧版本查询 409、全部撤回为 0 以及重复撤回幂等。完整结果 passed=true、server_stopped=true，四阶段为 20→30→20→0。

按已给定分工，B 独立功能开发与独立验收已收尾；当前没有刻意留给用户完成的 B 代码或测试任务。A/D 一键协调与页面接入、C 统计和发布版本对齐属于团队接入，接入时若发现 B 缺陷继续修复。没有因此把跨团队全系统验收宣布为完成。

本轮没有连接团队运行中的 A/C/D、写 Neo4j 或发布指针，也未完成全系统浏览器验收。data 和 reports 沿用忽略规则，本机生成的报告不随 Git 自动共享；团队交付依赖本文及可复现代码。

原有细节继续见 [批次处理](batch_processing.md)、[effective 导出](effective_export.md) 和 [本周报告接口](report_knowledge.md)。
