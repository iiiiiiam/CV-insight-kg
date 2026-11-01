# 知识构建模块

本模块目前能完成：读入真实论文 → 找出对象和关系 → 保留原文证据 → 按需核对和修改 → 保存恢复 → 导出与自动检查。
提供命令行和本地 Streamlit 原型，复用同一套核心代码。本文是当前功能和命令的总入口，不是历史操作日志。

## 当前实现与分阶段进度

| 阶段 | 已实现 | 说明 |
| --- | --- | --- |
| 1. 输入适配 | 读取并校验 A 的固定样本、还原摘要、保留作者机构和来源 | 不修改样本、不依赖 A 服务启动 |
| 2. 模型与抽取 | 8 类实体、7 类关系、原文位置证据、小词表提及抽取 | 关系表达“提及”，不自动认定提出或使用 |
| 3. 核对与修正 | 确认、驳回、显示名/证据有限纠正、撤回及操作历史 | 按需使用，不要求所有用户逐条审核 |
| 4. 进度存档 | 自动保存、恢复、版本与输入校验、旧进度覆盖检查 | 只有保存成功才更新当前决定 |
| 5. 业务导出 | 已确认、待审、驳回分文件；结构说明、校验清单与 ZIP | 当前仍是团队集成草案 |
| 6. 词表补充 | 默认 53 个词条，新增别名有真实开发参考，保留原 8 词条版本 | 新旧版本不自动继承审核决定 |
| 7. 质量与评估准备 | 逐篇命中/缺失统计、开发清单、五篇验证材料、空白答案及有限评分 | 20 篇都用于开发，独立测试集仍空 |
| 8. 工程整理 | 核心、命令、测试、文档、示例按功能分目录 | 核心导入方式和旧数据格式保持兼容 |
| 9. 本地原型 | 概览、论文筛选、候选/证据、核对保存、导出与检查 | 不代替正式主前端、Neo4j 或登录系统 |

默认 `cv-terms/0.2` 在现有 20 篇真实论文上产生 **285 个实体候选、341 条关系候选**，按篇计数，不是全局不同对象数。
这些数字是程序候选统计，不是准确率；是否已确认以本地实际记录为准。
真人五篇确认、独立标注校准、正式测试封存和 C/D 联调仍需实际完成，详见[第一周盘点](week_one.md)。

## 启动与常用命令

下列命令都从 **Research-Insight-Team 仓库根目录**运行，复用现有环境：

```powershell
conda activate insight
```

### 看页面

```powershell
python -m scripts.knowledge_builder.workbench
```

打开 http://127.0.0.1:8501 。端口占用时改用 `--port 8502`，打开 http://127.0.0.1:8502 。
本原型无需启动 `python run.py`；后者仍是 A 的入口。页面试用顺序、环境说明见[原型说明](../../prototypes/knowledge_builder/README.md)。

### 不使用页面也能运行

| 目的 | 命令 | 输出 |
| --- | --- | --- |
| 看当前抽取效果 | `python -m scripts.knowledge_builder.preview` | 终端统计与第一篇证据，不写审核决定 |
| 准备检查材料 | `python -m scripts.knowledge_builder.prepare_validation` | 质量报告、开发清单、五篇材料、空白答案 |
| 导出业务文件 | `python -m scripts.knowledge_builder.export` | 三种状态 JSON、Schema 和文件清单 |
| 核对第一篇论文 | `python -m scripts.knowledge_builder.review --paper-index 1 --reviewer "你的姓名"` | 交互操作，默认自动保存和恢复 |

仅想临时试核对、退出不保存时，在 review 命令后加 `--memory-only`。
导出和检查材料默认生成新时间目录；用 `--output` 指定目录时必须选择尚不存在的目录，避免覆盖旧结果。
全部入口均支持 `--help`，例如：

```powershell
python -m scripts.knowledge_builder.export --help
```

## 样本集、导入批次与输出目录

- 论文跨机器对齐使用 `openalex_id`。
- `dataset_id=week1-cvpr2024-detection-v1` 标识这组论文样本，**不是一次数据库导入的批次号**。
- A 的 `Job` / `PaperBatch` 管理导入批次；本模块直接读取固定原始文件，不创建这些任务或批次。
- 每次导出生成的新目录只是一次运行产物，不等于 A 新建了导入批次。

| 位置 | 保存内容 | Git 行为 |
| --- | --- | --- |
| `data/knowledge_builder/reviews/` | 审核决定和完整操作历史 | 忽略 |
| `data/knowledge_builder/exports/` | 分状态业务文件包 | 忽略 |
| `data/knowledge_builder/validation/` | 质量报告、验证材料和答案模板 | 忽略 |
| `reports/` | 本机阶段学习报告 | 忽略，克隆仓库不会自动获得 |

## 关键测试与检查

沿用团队的 unittest。全套会导入 A 的数据库模块，建议新开一个专用终端：

```powershell
conda activate insight
$env:DATABASE_URL = 'sqlite://'
python -m unittest discover -s tests -v
```

这是测试用的内存数据库设置；完成后关闭该终端，或按[测试说明](testing.md)恢复原环境变量，再启动 A 的持久数据库页面。
更多模块测试、页面测试和 Ruff 命令见 [testing.md](testing.md)。
2026-10-31 本机在安装可选 Streamlit 依赖的环境中执行全套 **112 项，全部通过**，其中页面交互测试 5 项。
这是该轮验证记录，不表示后续任意修改都自动通过。

## 目录与详细说明

```text
src/knowledge_builder/          可复用核心和应用协调层
scripts/knowledge_builder/      功能命令
tests/knowledge_builder/        模块与可选页面测试
docs/knowledge_builder/         当前说明、规范和测试入口
examples/knowledge_builder/     旧词表及开发评估清单
prototypes/knowledge_builder/   可选 Streamlit 原型
```

- [输入](input.md)、[候选抽取](candidates.md)、[词表](vocabulary.md)：输入、提及抽取及真实开发参考。
- [审核](review.md)、[存档](storage.md)：决定、纠正、撤回、恢复和冲突检查。
- [业务导出](export.md)、[质量与评估准备](validation.md)：交付文件及评估范围。
- [规范草案](schema.md)、[第一周盘点](week_one.md)、[测试说明](testing.md)：约定、边界和验收命令。

## 旧版本兼容

当前只维护按功能命名的命令，旧 scripts.*_b_* 名称已替换。核心仍从 `src.knowledge_builder` 导入。
复现旧版 238/294 候选可使用：

```powershell
python -m scripts.knowledge_builder.preview --vocabulary examples/knowledge_builder/vocabulary_v0.1.json
```

review、export、prepare_validation 也支持同一参数。旧存档须配对应词表，不手改指纹强行套用决定。
既有存档编号和格式标识保留；旧审核目录仍可识别，新旧位置同时有记录时需显式选择。
具体参数和限制见各功能文档，历史产物中的旧命令以本页当前入口为准。
