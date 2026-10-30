# 知识构建模块

从真实论文中整理实体、关系和原文证据，支持按需审核、本地恢复、分状态导出与开发质量检查。
当前模块属于本地原型，正式评估和团队接口尚未冻结。

## 目录职责

```text
src/knowledge_builder/          可复用业务逻辑，不依赖页面
scripts/knowledge_builder/      命令入口
tests/knowledge_builder/        模块测试，沿用团队 unittest
docs/knowledge_builder/         使用说明与本地规范
examples/knowledge_builder/     旧词表及开发评估清单
data/knowledge_builder/         运行结果，被 Git 忽略
reports/                       阶段学习报告，被 Git 忽略
```

## 从仓库根目录运行

复用已有 insight 环境：

```powershell
conda activate insight
python -m scripts.knowledge_builder.preview
python -m scripts.knowledge_builder.prepare_validation
python -m scripts.knowledge_builder.export
```

第一条看候选；第二条生成质量报告、五篇验证材料和空白答案；第三条导出分开的已确认、待审和驳回文件。
需要时再使用审核入口，不要求现在逐条审核：

```powershell
python -m scripts.knowledge_builder.review --paper-index 1 --reviewer "你的姓名"
```

全部命令均支持 --help。查看旧词表结果加：

```powershell
python -m scripts.knowledge_builder.preview --vocabulary examples/knowledge_builder/vocabulary_v0.1.json
```

团队全套测试仍是：

```powershell
python -m unittest discover -s tests -v
```

测试会导入 A 的数据库模块；建议在单独终端先设置 `$env:DATABASE_URL = 'sqlite://'`，结束后关闭该终端或恢复原值。

## 使用说明

- [输入](input.md)：如何读 A 的固定样本。
- [候选抽取](candidates.md)、[词表](vocabulary.md)：找到什么、依据在哪里、版本如何选择。
- [审核](review.md)、[存档](storage.md)：人工决定、撤回、保存和恢复。
- [业务导出](export.md)：三种状态、机器结构说明与校验清单。
- [质量与评估准备](validation.md)：自动检查、独立答案和有限范围评分。
- [规范草案](schema.md)：实体类别、关系方向与证据约定。

## 重构兼容说明

旧 scripts.*_b_* 命令名已经替换为上面的功能命令；不保留同名空壳代码文件，避免两套入口长期并存。
Python 核心调用方式 `from src.knowledge_builder...` 不变。
既有存档、候选编号、业务文件版本及证据保持兼容；已经写入数据的格式标识不随文件重命名，以免旧 ID 和存档失效。
本机已有的运行目录已按功能整理到 data/knowledge_builder 下，文件内容不改。
其他机器若仍有旧审核目录，默认路径会识别它；新旧目录同时有记录时要求显式选择 --reviews-dir 或 --archive，避免混读。
旧阶段产物中若有旧命令文字，可按本页的新入口重新生成验证材料，不改写已生成文件的校验值。
