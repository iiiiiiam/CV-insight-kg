# 自动质量盘点与评估准备

版本：`b-assessment/0.1-draft`。现有 20 篇都已用于开发，不作为独立测试集。
[开发评估清单](../../examples/knowledge_builder/evaluation_manifest.json) 列出论文、来源、输入指纹；development 为 20，test 为空。
这是诚实的准备状态，不是已经封存的正式评估集。

## 运行

```powershell
python -m scripts.knowledge_builder.prepare_validation
```

输出到 data/knowledge_builder/validation 下的新目录：

| 文件 | 内容 |
| --- | --- |
| quality.json / quality.md | 全部论文的自动盘点和易读版本 |
| evaluation_manifest.json | 开发样本清单、5 篇校准子集、独立测试集缺口 |
| annotations.json | 前 5 篇的原文和空白独立答案模板，不复制程序预测 |
| evaluation.json | 标注未完成时状态为 awaiting_annotations，分数为 null |
| demo_packet.md | 同 5 篇的原文、程序候选和证据，便于后续检查 |
| manifest.json | 本包文件 SHA256 |

可加 --output 指定新目录、--vocabulary 选版本、--reviews-dir 选存档位置、--manifest 选输入清单。
已有输出目录不覆盖，源码和真实样本不改。

## 当前自动盘点

cv-terms/0.2 下：20 篇，285 实体候选、341 关系候选；18 篇找到方法、19 篇找到任务、13 篇找到数据集、4 篇找到主题。
有 17 条来源诊断，9 个作者候选未解析来源 ID；摘要无缺失。
“某类别有候选”只是命中情况，不是召回率。没有命中也不证明论文没有该类别。

## 独立答案与评分

模板初始 annotation_status=unannotated，annotator、completed_at、gold_entities 均为 null。
真实标注后才能改为 completed，填写标注人、带时区时间和完整 gold_entities 列表。
空列表 [] 表示确实核对后认为没有目标提及，和未标注 null 不同。

本版只评 topic/method/task/dataset 在标题和摘要中的精确提及，不评分作者、机构、关系语义或消歧。
每条参考答案含 kind、canonical_name、field、start、end、quote；位置和原文必须通过实际输入校验。
规范名与预测名忽略大小写匹配，字符范围必须完全一致。不要把预测直接复制成答案，否则不能发现漏项。
校准时应先按相同规则各自读原文，再比较分歧；目前尚未完成真人校准。

填完后另生成一个新包：

```powershell
python -m scripts.knowledge_builder.prepare_validation --annotations data/knowledge_builder/validation/某次输出/annotations.json
```

只有所选案例全部完成才计算开发集分数；部分未完成时不偷偷只算完成部分。
precision 是“程序找出的内容中多少与参考相符”，recall 是“参考内容中多少被找到”，f1 是综合值。
分母为零时相关指标为 null。即使得到开发分数，也不等于独立测试结果或项目总体准确率达标。

下一步仍需未参与开发的新测试论文、正式协议和少量真人标注；这些不由程序代填。
