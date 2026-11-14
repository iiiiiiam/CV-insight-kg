# 词表版本与开发参考

当前默认词表为 `cv-terms/0.2`，共 53 个词条；原 `cv-terms/0.1` 的 8 条保存在
[examples/knowledge_builder/vocabulary_v0.1.json](../../examples/knowledge_builder/vocabulary_v0.1.json)。
新版本增加真实样本中明确出现的方法、任务、数据集和主题，不改既有类型与提及关系含义。

45 个新增词条的每个别名都在 [vocabulary_sources.json](vocabulary_sources.json) 中记录真实论文 ID、
字段、字符位置、原文和输入指纹。这些是开发参考，不是人工金标准或独立评估结果。
例如 YOLO-World 与 YOLO 分开；不把 CAT 这样的常见短词直接作为方法别名，Class-Aware Teacher 只按完整名称匹配。

当前 20 篇结果：实体候选 285、关系候选 341，均为逐篇计数之和，默认仍待审。
方法候选从 7 增为 28、数据集从 4 增为 21；数量增加不是准确率提高的证明。
较长任务名优先匹配，例如 3D Object Detection 不在同一位置再重复抽通用 Object Detection，也不自动推断任务层级。

三个入口均支持指定词表：

```powershell
python -m scripts.knowledge_builder.preview --vocabulary examples/knowledge_builder/vocabulary_v0.1.json
python -m scripts.knowledge_builder.export --vocabulary examples/knowledge_builder/vocabulary_v0.1.json
python -m scripts.knowledge_builder.review --paper-index 1 --reviewer "你的姓名" --vocabulary examples/knowledge_builder/vocabulary_v0.1.json
```

旧版可重现 238 个实体和 294 条关系。旧审核存档须配旧词表；新版抽取指纹不同，不自动继承旧确认。
新版本可另用 --archive 或 --reviews-dir 指定独立存档位置，不手改指纹强行恢复。
默认更新会让旧存档明确报版本/抽取不匹配，这比静默套用旧确认更可靠。

新增 3 项测试：每个新别名有真实可定位参考，具体方法和数据集可识别且不乱用模糊缩写，旧版仍可重现。
这些改进使用了全部开发样本，不能再将同一批论文随机分半后声称有从未参与开发的独立测试集。
