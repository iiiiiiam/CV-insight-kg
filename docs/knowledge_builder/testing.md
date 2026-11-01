# 测试与检查命令

全部从仓库根目录运行，沿用 unittest，不需要切换 pytest 或重新安装本模块。
本页记录如何验证；功能进度见 [README](README.md)，页面运行见[原型说明](../../prototypes/knowledge_builder/README.md)。

## 环境与数据库隔离

```powershell
conda activate insight
```

全套及输入对照测试会导入 A 的模块。下面的 PowerShell 写法临时切换到内存数据库，结束后恢复原值：

```powershell
$knowledgePreviousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'sqlite://'
    python -m unittest discover -s tests -v
}
finally {
    if ($null -eq $knowledgePreviousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:DATABASE_URL = $knowledgePreviousDatabaseUrl
    }
}
```

也可以在独立终端设置 `$env:DATABASE_URL = 'sqlite://'`，执行下面任一命令后关闭该终端。
不要在忘记恢复配置的同一终端里，继续按默认持久数据库的方式运行 A 服务。

## 按范围运行

| 范围 | 命令 |
| --- | --- |
| 团队全套 | `python -m unittest discover -s tests -v` |
| 知识构建模块全部测试 | `python -m unittest discover -s tests/knowledge_builder -v` |
| 输入适配 | `python -m unittest discover -s tests/knowledge_builder -p test_input_adapter.py -v` |
| 抽取规则 | `python -m unittest discover -s tests/knowledge_builder -p test_extraction.py -v` |
| 存档与恢复 | `python -m unittest discover -s tests/knowledge_builder -p test_review_storage.py -v` |
| 工作台协调层和页面 | `python -m unittest discover -s tests/knowledge_builder -p 'test_workbench*.py' -v` |
| 仅页面交互 | `python -m unittest discover -s tests/knowledge_builder -p test_workbench_ui.py -v` |

页面测试使用 Streamlit AppTest，检查实际页面、表单和保存恢复，数据只写临时目录。
未安装可选 Streamlit 依赖时，5 项页面测试会跳过，不能据此声称页面验证通过。
其他机器需要验证页面时，使用 `requirements-prototype.txt` 安装可选依赖；不要替换团队基础依赖文件。

## 代码与格式检查

本机已有 Ruff 时运行；这些是检查命令，不自动改代码：

```powershell
python -m ruff check --isolated --no-cache --select E4,E7,E9,F,I src/knowledge_builder scripts/knowledge_builder prototypes/knowledge_builder tests/knowledge_builder
python -m ruff format --check src/knowledge_builder scripts/knowledge_builder prototypes/knowledge_builder tests/knowledge_builder
git diff --check
```

## 不跑测试，也能快速看效果

```powershell
python -m scripts.knowledge_builder.preview
python -m scripts.knowledge_builder.prepare_validation
python -m scripts.knowledge_builder.export
```

preview 只显示候选；另外两个命令会在被忽略的 data/knowledge_builder 下生成新输出目录。
正常导出、结构检查或程序测试通过，均不等于真人确认、正式标注或准确率达标。

## 已执行记录

2026-10-31，insight 环境中执行团队全套 112 项，全部通过，包含工作台协调层 8 项与页面 5 项。
Ruff 检查、格式检查通过；原型首页及 /_stcore/health 的 HTTP 检查返回 200。
此处是历史验证快照，不自动代表后续修改的结果，也不是实际浏览器截图验收。
