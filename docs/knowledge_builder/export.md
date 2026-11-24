# 带版本的业务 JSON 导出

版本：`b-knowledge-export/0.1-draft`。这是 B 的集成草案，尚未与 C/D 冻结正式接口。
前置：[候选抽取](candidates.md)、[审核](review.md)、[进度存档](storage.md)。

## 一条命令运行

从仓库根目录、已有 insight 环境执行：

```powershell
python -m scripts.knowledge_builder.export
```

默认读取 A 的 20 篇固定样本和 `data/knowledge_builder/reviews/` 中已有的 JSON 存档；没有存档时保持全待审。
自定义文件名的存档同样支持，但每篇只能有一个；损坏、版本不符、重复或超出本次样本范围的存档会报错。
读取存档会复用历史重放校验，不修改存档、不创建人工决定。

默认输出到 `data/knowledge_builder/exports/<UTC时间>/`，也可指定一个尚不存在的目录：

```powershell
python -m scripts.knowledge_builder.export --output data/knowledge_builder/exports/first-delivery
```

输出目录不覆盖，重复执行请换新目录或使用默认自动生成路径。
可用 `--manifest` 指定符合现有输入适配约定的样本清单、`--reviews-dir` 指定专用审核存档目录。
运行仅使用标准库，不需要网络、数据库、LLM 或额外安装依赖。

## 五个文件

| 文件 | 内容 | 接收方应如何使用 |
| --- | --- | --- |
| confirmed.json | 仅已确认实体及关系 | 可作为后续知识入库的草案输入，仍需正式对接 |
| pending.json | 待审核候选 | 可供检查、评估或待审预览，不能当作已确认知识 |
| rejected.json | 已驳回记录 | 用于分析规则问题，不进入已确认知识 |
| schema.json | JSON Schema 结构说明 | 机器读取的字段、类型、枚举、必填项及状态约束 |
| manifest.json | 文件 SHA256、处理范围、分组计数、诊断数 | 检查文件是否完整；不代表准确率评估 |

导出阶段 cv-terms/0.1 实测为待审 20 篇、238 实体、294 关系；已确认及驳回均为 0。
后续默认词表已更新为 cv-terms/0.2，候选为 285 实体、341 关系，详见 [vocabulary.md](vocabulary.md)。
旧存档请通过 --vocabulary examples/knowledge_builder/vocabulary_v0.1.json 指定原词表，不自动继承确认。
空的已确认文件是正确结果，不自动补成“至少 5 篇人工确认”。

## 业务结构

每个状态文件包含 format_version、contract_status=draft、kind、status、papers、counts。
papers 只保留在本状态确有实体或关系的论文分区。每个分区包含：

- input：原 PaperInput，含原始标题、还原摘要、authorships、来源与样本集编号。这里只是追溯上下文，不意味着全文元数据都已确认。
- origin：输入、原始抽取结果和词表的指纹及各版本。
- entities / relations：本状态的候选，保留 candidate_id、内容、状态和证据。
- endpoint_context：关系需要、但不在本状态实体集合中的端点；仅供定位，保留它自己的真实状态。
- diagnostics：来源缺失或未解析信息。

每条记录包在 `{"item": ..., "review": ...}` 中。review 为该候选最新一次操作的序号、动作、操作人、理由和 UTC 时间；
从未操作时为 null。完整前后历史仍在工作存档中，不在业务文件中复制整段历史。
confirmed 必须有明确的 confirm 记录，其关系两端必须同在 confirmed 实体集合，endpoint_context 必须为空。
pending/rejected 的关系可能引用其他状态的实体，端点上下文在其他状态主记录中必须能一致找到。
计数不包含 endpoint_context，避免把同一对象重复统计为业务记录。

## Python 接口与校验层次

```python
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.export import build_exports, validate_exports
from src.knowledge_builder.export_io import write_exports, load_exports

papers = load_openalex_sample("examples/week1_baseline.json")
results = [extract_candidates(paper) for paper in papers]
bundle = build_exports(papers, results)  # 这里没传审核会话，所以全部待审。
validate_exports(bundle, papers)
write_exports("data/knowledge_builder/exports/python-example", bundle, papers)
restored = load_exports("data/knowledge_builder/exports/python-example", papers)
```

有审核会话时，用第三个参数传 `{openalex_id: session}`。导出前重新重放历史并核对当前快照。
validate_exports 使用真实 PaperInput 校验证据切片、元数据路径、状态隔离、端点、候选 ID、来源与计数。
load_exports 还核对清单、每个文件校验值和 schema 版本。校验值不是签名，不证明操作人身份真实。
独立 JSON Schema 工具可检查结构，但无法只凭结构判断原文证据或学术结论，不能替代业务校验。

导出先在同级临时目录完整生成，最后重命名为目标目录；失败时清理本次已知临时文件，不递归删用户目录。
这是单机批量交付文件，不是多用户写入服务或数据库事务。

## 当前验证与未完成项

本阶段新增 14 项 unittest，全套 83 项通过；真实 20 篇及含程序测试审核的分组导出均通过校验。
额外使用当前环境已有 jsonschema 检查生成的 Schema 和示例，未把该库加入运行或测试依赖。
原有存档格式保持兼容；只把重复的 JSON 模型解析抽到 serialization.py 共用。

仍未完成正式评估集封存/划分、少量人工标注校准、5 篇真人确认演示、正式准确率报告，以及 C/D 接口冻结与 Neo4j 入库。
项目的主题/方法/年份组合筛选与图谱查询主要由 C/D 接入，本阶段未改其代码。
