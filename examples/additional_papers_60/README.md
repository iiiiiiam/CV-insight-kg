# 新增 60 篇论文样本池

CVPR 2024、ICCV 2023、ECCV 2024 各 20 篇，均有摘要、作者、稳定 OpenAlex ID 和来源；与原来的 20 篇按 ID、DOI、规范化标题去重。已检查数据质量和输入格式，尚未用于候选提取、词表调整或人工标注。

先打开 **论文清单.csv** 查看全部论文。`papers.json` 是 60 篇统一输入，三个会议的同名 JSON 文件各含 20 篇；`sources.json` 记录 DOI、摘要与作者来源，`raw/` 保留原始来源证据，`manifest.json` 保存范围与 SHA256。`validation.json` 是实际校验结果。


## 读取方式

将整个 `additional_papers_60/` 文件夹放到项目的 `examples/` 下。从仓库根目录执行：

```bash
python examples/additional_papers_60/load_for_b.py
```

应输出共 60 篇、三个会议各 20 篇、有摘要 60 篇。代码中读取：

```python
from examples.additional_papers_60.load_for_b import load_papers
papers = load_papers()  # 返回 PaperInput 对象列表
```

输入格式已与项目现有的 `PaperInput` 结构核对。原有 `load_openalex_sample` 用于 OpenAlex 原始样本清单；这份样本包含不同来源，请使用随附的读取函数统一加载。

## 来源区别

CVPR/ICCV 使用已采集的 OpenAlex 正式会议来源及原始摘要、作者机构信息。ECCV 以 ECVA 官方目录、DOI 与标题核对会议归属，从官方论文页取得摘要和作者；通过 DOI 匹配 OpenAlex 论文 ID。ECCV 的机构和作者 ID 信息暂缺，相应字段保持为空。原始记录与补充信息分别保留，并注明来源。

论文围绕 object detection 及相关分支，包括二维、三维、遥感和伪装目标检测；不代表会议全部主题或随机总体。筛选按数据完整性、题名范围和固定哈希顺序进行，不按提取效果挑选。
