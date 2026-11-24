# Week 3 · C FR01/FR02 与真实批次验收

## 范围与材料核验

没有执行 Git 命令，没有修改 A/B/D 参考代码或 Docker 数据。A 参考目录实际只有 examples，未提供 docs/week3-a.md；本轮完整读取用户另附的《Part A 第三周进展与团队接入说明》，并读取 B docs/knowledge_builder/team_handoff.md、批次/effective 说明及对应源码。四份 A JSON 均通过各自 SHA256 文件核验：两批论文、撤回核对、B 接收结果。

D 当前 Filters 仍是单值契约。按项目八类实体扣除论文、会议，六维为 author/institution/topic/method/task/dataset；year、venue 为附加条件。研究子方向 direction 作为独立来源分类筛选加入，不擅自替换 topic/task。若团队需求文档对“六维”命名另有决定，可在 D 层调整分组；本实现同时支持这些维度，不把第七项混称为六维。

## FR01 请求与查询规则

原 GET /api/research/papers、/statistics、/graph 路径保留。六维参数、direction、venue、author_id 支持重复 query 参数；year 支持重复整数。一次请求中同参数 OR，不同参数 AND；q 仍为单个标题包含搜索。旧单值请求不变：它自然被解析为长度1的数组。

```http
GET /api/research/papers?batch_id=已发布批次&author=稳定ID1&author=稳定ID2&method=YOLO&method=DETR&year=2023&year=2024&venue=CVPR&direction=cv-direction:object-detection&page=1&page_size=20&sort=year_desc
```

不能用逗号拼接多个值，名称本身可能有逗号。每维最多50项、每字符串最多500字符；年份1900—2100。空筛选不生效；未知名称/ID返回空集合，不编造匹配。author_id 是独立的精确作者身份限制，与 author 同时提供时仍取交集。

名称做大小写、首尾和连续空格规范化。作者可用 C id、原始来源 id、真实显示名/同一身份的名称变体；同名不会合并成同一自然人。方法/主题等使用 C 固定的 B 参考词表别名目录及本批原文命中别名；不自行猜测作者昵称。新增 alias 目录只用于检索规范化，不制造知识关系或改变审核状态；未知昵称若必须支持，需 B 提供可信的名称—稳定 ID 映射。

筛选在 Neo4j 的整个已发布批次内执行后，再 count、ORDER BY、SKIP/LIMIT。使用 EXISTS 避免多标签 JOIN 导致重复论文。sort 保留 year_desc、year_asc、title，最后都以稳定 p.id 打破平局。page 从1开始，page_size默认20最大100。超出页返回空 items，total 仍是全量条件总数。

D 应用 URLSearchParams.append 保留重复参数；后端代理也必须传多值参数列表，不能 dict(request.query_params) 压成最后一个值。不要在加载的一页上补做筛选，也不要把数组隐式转换为逗号串。返回的 filters 可能为规范化后的数组，不再假定全是字符串。

## FR02 新字段及空值

items 和详情 node 保留原字段，论文新增：

| 字段 | 含义 |
| --- | --- |
| id/title/year/venue | C 稳定论文身份、标题、来源年份与会议 |
| openalex_id | 可用的来源论文身份；不替换 C id |
| authors | 源 authorships 投影的 id/source_id/name 列表；身份缺失为 null，不猜测 |
| author_names | 显示名称数组；完整图身份仍在 effective_partition.entities/relations |
| citation_count | 当前 B PaperInput/effective 没有引用次数，因此 null，不能当0 |
| sources/source_url | 真实 PaperInput 来源 URL 和来源 ID，不伪造抓取时间 |
| metadata | 本次发布所对应的完整 PaperInput，而非 B 当前可变结果 |
| source_updated_at | 当前来源契约未提供，null |
| knowledge_exported_at | 首次保存此 revision 的 B generated_at |
| graph_published_at | 此快照首次发布时刻；恢复旧快照保留首次时刻 |
| data_revision | B effective 的内容 revision |
| field_notes | 缺失值及兼容时间字段的解释 |

旧 updated_at 保留兼容含义，不作为来源更新时间。没有从 A 原始文件直接挪用未进入 B 快照的引用次数、机构或日期。若需要引用次数与来源更新时间，建议 B 在版本化契约中增加带提供者/采集时间的可选元数据；目前 A→B 的 PaperInput 不传这些字段。D 显示“未知”，不能默认0或用导出时间替代。

详情继续提供 related/relations 及完整 effective_partition：原文、实体、关系、证据、origin、source_classifications、generation/review_state/rule_adjusted 不丢失。所有列表、详情、统计和图谱均从同一 batch_id 读；D 必须携带首次响应的 batch_id 下钻。

错误保留：422 参数不合法（标准 detail 或 error/code/message）；404 无已发布批次/实体；409 版本/CAS/完整性冲突；503 数据库不可用。大批次不要一次请求超过100条列表。完整参数定义见 openapi.week3.json。

## 研究子方向

B 实际 effective 根分区字段为 source_classifications，内容来自公共投影 source_enrichment.source_classifications。C 已保留原分区；本轮只对 kind=research_direction 增加论文属性索引 direction_ids/direction_labels/direction_tokens，完全不增加图节点或 mentions_topic/mentions_task 边。

使用 direction=稳定 cv-direction ID 或标签；同维 OR、可与六维/年份/会议 AND。statistics.distributions.research_direction 返回 id/name/paper_count（去重论文）、truncated、独立口径说明。只返回当前批次实际出现的方向，不伪造全部18类都有论文。目录17类+“其他”由 B 维护，“其他”只采用 B 给出的分类，不由 C 给未分类论文补齐。

投影版本2用于新快照；旧已发布快照按原投影版本校验，不原地重写。旧150篇原始 effective 尚无 research_direction，因此方向统计为空合理。更早版本如果只保存原分区、没有方向索引，不应声称已经自动迁移；如需重投影这类历史数据，需另行约定迁移批次，不能覆盖历史。

## 实际 A→B→C 验收

本轮并非用手填数字模拟：运行 scripts/build_week3_b_exports.py，从只读 B-reference 导入 BatchRegistry 与真实 effective exporter。独立 ledger、feedback 和输出全部位于 C work/week3-b-exports。禁用参考源码字节码写入；只读取 B，未启动其团队服务，也未联网 prepare 来源补充。

结果与 A 提供的接收回执相符：

| 阶段 | 有效论文 | B 结果 |
| --- | ---: | --- |
| 第一批 | 20 | 新增20 |
| 合并第二批 | 30 | 新增10、重复7、更新3 |
| 撤回第二批 | 20 | 移除10、共有保留10、恢复旧输入3 |
| 撤回第一批（全部撤回） | 0 | 不回退原150篇 |

四份真实 B 输出随后导入隔离 Neo4j Harness 5.26.0 发布并验收。前后20篇输入字典逐项相等，不只是数量一致。恢复后的 B revision 与首批相同，C 幂等复用原批次；历史30篇仍按 batch_id 可查。检索按7条分页核对无重复无遗漏；测试六维单维多值 OR、六维同时 AND、跨维 AND/OR、年份会议组合、作者统计、方向筛选、元数据与错误状态。错误文件导入、错误 CAS 不改变当前快照。

实际批次ID见 week3-results.json：首批 effective-4a163561ce55…，合并 effective-915398814c8a…，撤回后复用首批，合法空快照 effective-5855d30e13e7…。本轮只在隔离引擎发布，不影响用户现有 Docker 中150篇的批次和发布指针。

这属于**真实论文文件 + B 未修改参考代码 + C + 真实 Neo4j 的离线程序链路验收**，不是 A/B/D 运行服务、真实管理员操作和统一页面的在线联调。外部来源补充在本轮未联网执行，导出使用 B 自己的规则/原文回退能力。D 仍需在集成环境验收导入按钮、后台来源任务、自动同步、发布状态与页面三视图。

空快照要求完整 effective 格式、正确 revision、0计数及空 papers；通过管理员导入并显式 CAS 发布才生效。{}、缺字段、哈希/计数错误不算合法空结果。旧 confirmed 的空输入仍拒绝，不放宽旧审核语义。C 不从空文件推断撤回原因，本次有 B 全部撤回回执作业务证据。

## 作者画像跨批次口径

本轮保持单快照画像：最新有效数据指当前 active 快照；历史画像指某个曾发布 batch_id。新版本替换和撤回不会让历史内容被累计进最新结果。

D 需要先决定“跨批次”究竟是当前多个来源合并后的唯一论文集，还是历史曾出现论文的回顾。不能把多个完整快照直接相加；同一稳定论文会重复，撤回论文也会混入。若做历史回顾，需明确时间范围、按论文ID去重、论文版本选择及是否包含已撤回内容。C 本轮不擅自新增历史累计 API。

## 复现和接口接入

原有 C 启动不变，保留用户当前 Neo4j 环境变量。新接口不需要重新导入旧150篇；本周新方向及名称变体索引在新 effective 投影时生成。

独立生成 B 快照（out 必须是新目录，不能指向运行中 B 账本）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-week3-dev.txt
.\.venv\Scripts\python.exe scripts/build_week3_b_exports.py --b-root ..\CV-insight-kg-B-reference --a-root ..\CV-insight-kg-A-reference --out work\another-week3-run
```

准备独立 Java21/Harness 后，设置 WEEK3_EXPORTS 指向上述输出目录，用 verify_effective_isolated.py --java JAVA_EXE --file ../effective.json --port 17703 运行全套测试。脚本只启动自己的隔离引擎并在结束后停止；不能把 GRAPH_TEST_URI 指向当前 Docker 演示库。普通 CI 运行其他回归，缺少 WEEK3_EXPORTS 的真实交接用例明确 skip。

需要 D 配合：多值请求/代理不丢参数、处理新增可选字段、缺失引用数显示未知、按固定 batch_id 下钻，以及决定历史画像和“六维”UI标签口径。需要 B 配合：可用引用次数、来源更新时间及可信作者别名映射如有；在线服务导出的相同数据范围与版本回执。A 四份文件已足够本轮离线验收，无需重采。

本轮没有前端美化、Git操作、A/B/D改动或现有Docker发布切换。

实际最终验证：49项全套通过（12项真实Neo4j、37项非数据库），111.57秒；补充六维同时AND与多值OR/AND断言后，Week3两项定向复跑通过，41.78秒。两次各有1条已有Starlette/httpx弃用提示。无在线团队HTTP/浏览器验收声明。
