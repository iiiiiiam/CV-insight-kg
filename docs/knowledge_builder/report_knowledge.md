# B 第四周：作者知识标签与报告知识接口

## 范围与规则

本轮依据第四周分工独立开发；FR 编号完整定义尚未定稿，不能把本文称为全组冻结需求。B 负责实体、关系、证据、反馈 effective、作者知识标签及知识质量事实；A 负责报告任务、文档、manifest、校验和 ZIP；C 负责趋势、共同作者、作者/机构统计及发布；D 负责页面、认证框架和全系统验收。

本版标签明确表示：**“该作者参与的当前有效论文涉及此主题／方法／任务／数据集”**。例如一篇论文有 `has_author` 指向作者 A，同时有 `mentions_dataset` 指向 COCO，则 A 有“论文涉及数据集：COCO”的标签。它不表示作者擅长、实际使用、提出了该方法，也不推断贡献、水平或影响力。

规则 `effective-paper-mentions/1`：

- 只使用一份完整 effective 快照，按来源作者 ID 精确分组；姓名变化保留为 names，不按姓名合并不同 ID。
- 来源 ID 直接沿用有效输入，本版不猜别名、不跨提供者匹配 ID，也不做自然人身份核验。缺 ID 时仅按单篇实体区分；`author_ref` 是本输出的定位引用，不是补造的作者来源 ID。
- 仅统计当前仍存在的 `has_author` 与 `mentions_topic/method/task/dataset` 两段关系；只剩实体、对应关系已排除时，不产生标签支持。
- 每个标签至少有 1 篇支持论文。同一篇的重复作者元数据不重复计数；所有标签均返回，不另设未经约定的 Top N 或强弱阈值。
- 按支持论文数降序、再按 kind/entity_key 排序；数量只表示支持篇数，不是置信度。
- 每个 support 保留 paper_id、输入指纹及 author/authorship/knowledge/mention 四组 witnesses，包含原候选 ID、内容、证据和自动／人工来源状态。
- 原文中的外部主题、研究子方向分类继续保留在 knowledge 中，不直接转成作者标签；没有对应提及关系时不会因外部分类而制造标签。
- 管理员补词产生的新实体和关系仍为 automatic，携带 rule_adjusted；人工改名保留 human_corrected。标签本身始终是规则计算结果。

## HTTP 读取

沿用 B 现有路由注册和管理员会话，不新增服务端口、任务系统、权限体系或 C 发布行为。

| 接口 | 权限 | 返回 |
| --- | --- | --- |
| `GET /api/knowledge/author-tags` | 与 B 原有知识读取相同，匿名可读 | `knowledge-author-tags/1`，规则、作者、标签及证据链 |
| `GET /api/admin/knowledge/report-export` | 现有管理员会话 | `knowledge-report/1` JSON 下载，含完整 knowledge、author_tags、quality |
| `GET /api/admin/knowledge/batches/readiness` | 现有管理员会话 | B 当前输入模式、知识版本、来源补充状态及结果可读状态；不检查 C 发布 |

标签和报告两个接口均支持 `?expected_revision=<64位effective revision>`。这是 **effective 的版本**，不是报告版本或批次账本整数 revision。返回 `X-Knowledge-Revision`；报告另外返回 `X-Report-Revision`。均 `Cache-Control: no-store`。

作者标签还支持可选 `source_id`（精确来源 ID）和 `author_ref`（精确本地定位引用）。同时提供时取交集；未知身份返回 authors=[]，不回退到同名作者或全量结果。筛选响应增加 selection，并重新计算标签 revision；knowledge_revision 仍是原完整快照版本。未传筛选时格式不变。D 可以先从画像取得稳定来源 ID，再只取该作者的标签；缺来源 ID 时使用 B 返回的 author_ref。

readiness 也支持 expected_revision。返回的 `results.available=true` 表示本次确实成功构建并校验了 effective，`results.empty=true` 表示合法空集合；存档损坏返回 503，不能当作空成功。`source_enrichment.state` 为 pending/running/partial/complete/interrupted/empty；partial 包括已尝试但外部来源部分或全部缺失。来源中断仍可有规则结果，重试来源不等于重新接收批次。`publication.state=not_checked, owner=C/D`，不冒充已发布。

已知快照版本不符或构建期间检测到输入／来源／反馈变化返回 409；参数不合法为 422；未登录读取报告为 401；存档损坏或不可读为 503。不会把损坏解释为空结果，也不会返回一半报告。读取只使用本地快照，不补充联网来源，不写默认账本，不调用 A/C。

报告读取会建立工作区、导出 effective、构建输出，并以第二个新工作区再次核对 effective 版本。它防止构建期间检测到的变化；不是跨进程事务或报告生成后长期锁定当前数据。成功返回的文件是一份固定快照附件。

原有 B 管理员 effective-export 也已加上前后新工作区复核，批次撤回／更新中途被检测到时返回 409，输出字段与协议不变。

## 报告结构与版本

```text
format_version: knowledge-report/1
revision: B 报告内容 SHA256
generated_at: 内嵌 effective 的生成时间
scope:
  mode: full_effective_snapshot
  knowledge_revision: effective.revision
  paper_ids: 排序后的全部当前有效论文 ID
  paper_count: 当前有效论文数
knowledge: 完整且未改格式的 knowledge-effective/1.0
author_tags:
  format_version: knowledge-author-tags/1
  revision: 标签内容 SHA256
  knowledge_revision / paper_ids / rule / authors
quality: effective-facts/1 的事实计数与逐篇明细
```

本版范围固定为 **B 当前完整有效集合**，不支持任意筛选子集或历史累计；不能将前端一页结果冒充完整范围。A 保存这一个附件即可避免分别读取标签、知识时混用版本；如另取 C 统计，需核对 C 的 data_revision 与 scope.knowledge_revision 相同。不保证 C 已发布此版本；发布状态继续由 D/C 现有接口提供。

报告 revision 覆盖知识内容、论文范围、标签规则与结果、质量规则与结果；不含 generated_at，包括内嵌 knowledge.generated_at。相同内容多次导出时版本相同；公共纠错、有效输入或来源分类变化会反映在知识与报告版本中。全部撤回返回明确空快照，恢复此前内容可恢复此前内容版本。规则算法发生语义变化时必须升级对应 rule version。

`knowledge` 保留原 `knowledge-effective/1.0`，未增加顶层或分区字段；C 仍接收其中的 knowledge，**不能把整个 report 文件提交给 C effective 导入接口**。

## 质量口径

所有实体／关系数量均为 **按论文分区累计的有效条目次数**，不是跨论文去重实体数或自然人数。空分母的 ratio 为 null；所有计数为零。

| 字段 | 实际含义 |
| --- | --- |
| counts / entities_by_kind / relations_by_kind | 当前生效知识条目数量及类型 |
| review_states | automatic、human_confirmed、human_corrected 条目数 |
| rule_adjusted_items | 受管理员补词影响的条目数，不等于人工确认 |
| evidence_coverage | 有有效证据条目数 / 全部条目数；导出要求每项有证据，因此合法非空快照为 1，不是准确率 |
| evidence_occurrences_by_field | 证据被条目引用的次数，区分 title/abstract/metadata；同段被不同条目引用会重复计数 |
| identified_author_coverage | 有来源 ID 的作者条目数 / 全部作者条目数，不是身份核验准确率 |
| papers_with_abstract | 非空摘要论文数 / 当前有效论文数 |
| papers_with_source_classifications | 有分类记录论文数 / 当前有效论文数，可能包含本地规则方向，不是外部来源覆盖率 |
| per_paper | 逐篇数量、输入指纹、缺摘要、未解析作者、分类数、未出现的知识类别 |
| accuracy | precision/recall/f1 为 null，status=no_independent_annotations；没有人工独立标注基准 |
| external_source_availability | pending/failed/with_sources 为 null；effective 协议没有保存抓取任务状态，不能据分类数量猜测 |

来源任务的实时 pending/partial/running/error 仍读取原 `GET /api/admin/knowledge/batches`。这是运行状态，不能混入固定知识附件当作同版内容。坏批次、被排除条目及反馈私人描述不进入报告；缺类别不代表论文一定没有该知识。

需要同时判断知识结果能否读取时，使用 readiness 而不是仅依据来源 completed 数量；它核对当次知识版本与来源状态。状态查询期间观察到变化返回 409，调用方重新读取即可，不要重发已成功批次。

## 离线使用

在仓库根目录使用已有 Python 环境，无需启动 D、A、C、Neo4j 或安装 Docker：

```powershell
python -B -m scripts.knowledge_builder.report_knowledge --effective path/to/effective.json --output path/to/knowledge-report.json
```

输入必须是已校验的完整 effective 文件，可加 `--expected-revision` 固定知识版本。命令不访问运行中的账本、不会联网或自动发布；校验失败以非零状态退出。输出不能覆盖输入；写入使用同目录临时文件和原子替换，失败保留旧目标文件。报告内部完整性可用 `validate_report_knowledge` 重新计算校验。

本地验证：

```powershell
python -B -m unittest tests.knowledge_builder.test_report_knowledge tests.knowledge_builder.test_report_api -q
```

测试使用临时账本、临时反馈和离线来源；真实两批文件测试先检查 SHA256，再验证 20→30→20→0、恢复相同报告版本及 C 旧格式兼容。API 测试关闭自动图谱同步。本轮不代表运行服务联调或全系统浏览器验收。

另提供 B 独立真实 HTTP 验收命令（需已有 server 运行依赖）：

```powershell
python -B -m scripts.knowledge_builder.verify_delivery --output-dir reports/week_four/new-http-check
```

该命令只绑定 127.0.0.1 随机端口，使用随机临时管理员和临时账本，明确关闭图谱自动同步；来源离线且额外禁止外部 requests HTTP。它验证真实 A 两批接收、重复接收、错误批次、反馈改名／排除／撤回、作者精确选取、版本一致及全部撤回。结束自动关闭自己启动的服务，不启动 A/C 或浏览器；不代表全组线上联调。输出目录必须为新目录，避免覆盖已有验收材料。
