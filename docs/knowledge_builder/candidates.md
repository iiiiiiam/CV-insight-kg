# 候选抽取：从论文资料卡到待审核清单

后续更新：默认词表已为 cv-terms/0.2，53 个词条，真实样本 285 个实体、341 条关系。
本文 238/294、8 个词条等属于 cv-terms/0.1 的历史结果；旧词表与复现方式见 [vocabulary.md](vocabulary.md)。

## 现在能做什么

之前 PaperInput 只是论文资料卡。现在把它交给 `extract_candidates`，会返回：

- `entities`：找到了哪些点，例如作者、方法、任务。
- `relations`：这些点如何连接，例如论文提及方法。
- `evidence`：每条候选的原文位置或元数据位置。
- `diagnostics`：缺失信息等需要注意的问题。

抽取结果全部为 `pending`（待审核）。抽取阶段不直接确认知识。
后续已增加独立审核核心，见 [review.md](review.md)，以及[文件保存与恢复](storage.md)。
规范版本为 `b-knowledge/0.1-draft`，仍是 B 本地草案，不是团队正式接口。

## 最短调用示例

从 Team 根目录、已有 insight 环境运行，无需启动服务或连接数据库：

```powershell
python -m scripts.knowledge_builder.preview
```

核心调用只有两步，输入读取器继续复用：

```python
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.extraction import extract_candidates

papers = load_openalex_sample("examples/week1_baseline.json")
result = extract_candidates(papers[0])

for candidate in result.entities:
    print(candidate.entity.kind, candidate.entity.name, candidate.status)
```

函数返回 Python 数据对象，不自动写入文件或数据库。

## 程序怎样找到这些内容

第一条路线读取已有元数据：

```text
authorships 中的作者 → 作者候选
同一作者记录中的机构 → 作者—机构候选关系
venue → 发表载体候选
```

不会把作者 A 错接到作者 B 那条记录中的机构。源数据没有机构就记录缺失信息，不补造。
同名作者按来源 ID 区分；缺少 ID 时保留论文内部位置生成的本地键，不凭名字跨论文合并。

第二条路线用小词表查找标题和摘要。`vocabulary.json` 中的例子：

```json
{"key": "yolo", "kind": "method", "name": "YOLO", "aliases": ["YOLO", "YOLOs"]}
```

`name` 是显示的规范名称，`aliases` 是允许程序识别的写法，`key` 是这个词条的固定编号。
例如标题有 YOLOs、摘要有 YOLO，它们合并为同一篇论文里的一个 YOLO 候选，并保留多段证据。
只匹配明确别名，忽略大小写；优先较长的重叠别名，避免 MS COCO 中再重复计算 COCO。
字母、数字、下划线及连字符被视为词内字符，避免从 RT-DETR 中额外抽出 DETR，
或把 YOLO-World 当成 YOLO。这会漏掉未列出的连字符变体，是首版的保守取舍。

## 用真实论文理解证据

第一篇标题为 `DETRs Beat YOLOs on Real-time Object Detection`。
程序实际得到：

```text
任务候选：Object Detection
状态：pending
证据：title[30:46] = 'Object Detection'
关系：这篇论文 ──mentions_task──→ Object Detection
```

抽取器保留原文字段、起止位置及原文切片。校验器的核心条件是：

```python
value[evidence.start:evidence.end] == evidence.quote
```

字符位置按 Python 字符串计算，从 0 开始，包含 start、不包含 end。
摘要位置针对现有读取器还原的字符串，不代表 PDF 位置。
元数据证据则使用路径，例如 `("authorships", 0, "author", "id")`，并保存该位置的值。
程序还检查作者—机构关系的两端证据属于同一条 authorship。

这篇论文还找到 DETR、YOLO、RT-DETR、COCO 和 Objects365 等候选。
这些关系只表示“提及”；不会自动断言作者提出 YOLO 或使用了某数据集做实验。

## 如何区分重复、变化和缺失

- 同一论文中同一实体只保留一个候选；相同关系也合并，保留不同证据。
- 候选 ID 按规范版本、论文 ID、实体键或关系三元组确定；重跑相同输入结果一致。
- 输入指纹覆盖 PaperInput 全部字段：先用 UTF-8 编码的规范 JSON（键排序、无额外空格、不转义中文），再算 SHA256。
- 结果另带规则版本、词表版本和词表指纹；同一版本号下词表内容改变也能识别。
- 输入变化后，旧证据校验会失败；相同候选 ID 不代表旧审核可以自动沿用。
- 缺少摘要、作者 ID、机构等会进入 diagnostics；没有 ID 不等于没有这个作者。

## 本阶段实际验证（2026-10-30）

20 篇真实样本得到 238 个实体候选、294 个关系候选。
这里是逐篇计数之和，例如 CVPR 在每篇各算一个候选，不是全局去重实体总数。

| 类型 | 实体候选数 |
| --- | ---: |
| 论文 | 20 |
| 作者 | 116 |
| 机构 | 52 |
| 会议/期刊 | 20 |
| 任务 | 19 |
| 方法 | 7 |
| 数据集 | 4 |
| 主题 | 0 |

17 条诊断分别是 9 条作者 ID 缺失和 8 条作者记录缺少机构。
这些是当前输入中的缺失情况，不将其补写成已知事实。
没有命中主题词表时不强行生成主题；方法和数据集词条也只有少数几个，覆盖很有限。

本轮 unittest 全套 42 项通过（原 31 项 + 新增 11 项），包括：
别名合并、误匹配边界、中文字符位置、缺失信息、稳定重跑、输入不被修改、
伪造证据拒绝、错误关系方向及端点拒绝、跨作者记录的机构关系拒绝，以及全部 20 篇真实样本校验。
真实清单及 JSONL 文件在测试前后逐字节一致。
Ruff 检查及格式检查通过。独立运行 B 抽取没有导入 sqlalchemy 或 app.db。
全套测试仅在进程内设置 DATABASE_URL=sqlite://；仍有原有 httpx 弃用提醒，未改依赖。

## 本阶段边界及下一步

程序检查通过只说明结果结构和证据位置符合规则，不等于人工判断内容正确。
当前小词表会漏掉未知名称，也会抽到背景讨论或否定句中的提及；未做正式准确率评估。
原文有不合理数字或其他上游错误时保留输入，不擅自修复为“真实证据”。
后续已经实现：查看候选与证据、人工确认/驳回/显示名称和证据纠正、内存操作记录，
并把已确认结果与待审核候选分开读取。本地保存与恢复、[带版本业务导出草案](export.md)也已完成；评估另行推进。
UI、在线 API、MySQL/Neo4j 接入和团队联调均未在抽取阶段实现。
后续的 JSON 业务导出仍标为本地草案，不能宣称团队接口已经冻结。
