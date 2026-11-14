# 读取 A 的论文样本

## 当前完成范围

B 的第一个功能块是读取 A 的固定 OpenAlex 样本，得到可供抽取使用的论文。
不修改样本，不访问网络或数据库，不创建采集任务，也不生成候选或已确认知识。
此输入结构是 B 本地开发草案，尚未作为 A/C/D 的正式集成契约。

## 从根目录运行

复用 Conda 环境 `insight` 和团队已有测试方式：

```powershell
conda activate insight
python -m unittest discover -s tests -p test_input_adapter.py -v
python -m unittest discover -s tests -v
python -c "from src.knowledge_builder.input_adapter import load_openalex_sample; papers = load_openalex_sample('examples/week1_baseline.json'); print(len(papers)); print(papers[0].title); print(papers[0].abstract)"
```

全套测试会导入 A 的数据库模块；若希望与本地数据库隔离，可先在当前终端设置
`$env:DATABASE_URL = 'sqlite://'`，测试完成后按需恢复原设置。
单独读取 B 样本只使用 Python 标准库，不需要启动 A 服务。

## 文件与调用关系

- `src/knowledge_builder/models.py`：集中定义 `PaperInput`。
- `src/knowledge_builder/input_adapter.py`：
  - `adapt_openalex_work` 转换一篇记录。
  - `load_openalex_sample` 读取清单和相邻的 JSONL，校验后返回论文列表。
- `tests/knowledge_builder/test_input_adapter.py`：验证转换、坏数据拒绝、真实样本与 A 摘要还原结果一致。

读取器检查文件 SHA256、数量、唯一论文 ID、清单中的标题/年份/DOI 和会议来源。
这是检查与 A 的固定清单一致，并不独立证明上游数据正确。
清单或论文内容不符时抛出 `ValueError`，不返回部分结果；文件不存在等访问错误原样抛出。

## 输入字段（B 草案）

| 字段 | 内容 |
| --- | --- |
| `openalex_id` | 原始 OpenAlex ID，用于与 A 对齐 |
| `title` | 原始标题，不删标点，方便后续证据定位 |
| `abstract` | 按词位置还原的文本；缺失时为 `None` |
| `year` | 原记录的发表年份 |
| `venue` | 清单中的会议名称 |
| `authorships` | 原始作者、机构及关联结构的独立副本 |
| `source_url` | 原记录的 OpenAlex 地址 |
| `dataset_id` | 清单中的样本集编号，不是数据库导入批次号 |

摘要还原采用 A 相同的按位置拼词方式，以测试保证现有 20 篇结果一致。
B 对负数、重复、非整数或不连续的位置直接报错，避免默默生成不可靠的证据文本。
该小函数仅用标准库，避免为了读取样本而引入 A 的数据库与采集依赖。
证据位置以后应针对这里还原得到的文本计算，不视为 PDF 原文字符位置。

作者与机构保留上游原始关联，不代表已完成人工确认或消歧。
读取结果中的作者结构可编辑，但已深拷贝，不会连带修改传入的原始记录。
目前不生成新 ID、批次号、获取时间或审核状态。

## 下一功能块

候选模型、词表提及抽取与证据校验已经完成，使用说明见 [candidates.md](candidates.md)。
人工审核、纠正及已确认结果分离也已完成，见 [review.md](review.md)；
本地保存与恢复见 [storage.md](storage.md)。
带版本业务导出草案见 [export.md](export.md)；后续推进评估与质量准备。
之后接 API 或任务时，在输入适配处转换为相同的论文输入，抽取逻辑不依赖页面或数据库。
当前固定样本是 A 的原型样本，不能直接宣称是正式封存评估集。
