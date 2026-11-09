# CV-insight-kg · 第一周开发基础

包含 20 篇真实论文样本、论文读取接口、导入管理和批次追溯。首次启动自动导入样本。

## 启动

安装 Python 3.10 或以上版本，用 VS Code 打开克隆下来的仓库文件夹，在该文件夹的终端执行。仓库可以放在任意目录、使用任意文件夹名。

**Windows PowerShell：**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run.py
```

**macOS / Linux / WSL：**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python run.py
```

浏览器打开 **http://localhost:8000/**，就能看到 20 篇真实论文。点击标题查看摘要、来源和批次；再次启动不会重复导入样本。

## 看哪里

- `/`：论文列表、关键词/年份筛选和详情，供组员查看真实数据。
- `/admin`：固定样本导入、重复导入、批次明细和 CSV 导出。
- `/docs`：可直接试用的 API 文档。

进入导入管理后，可直接导入样本、查看批次和导出 CSV。

## 接着开发

```text
run.py       本地启动入口
app/         后端、管理页、数据预览页、采集和导入逻辑
examples/    20 篇真实样本及固定基准清单
tests/       自动测试
scripts/     初始化、采集和验收工具
docs/        A 的验收说明、接口快照及验证记录
```

B 可导出论文 CSV 做标注；C 在现有模型和接口上继续做正式图谱；D 可以接列表、详情接口继续做页面。`openalex_id` 用于跨机器对齐，`papers.id` 是各自数据库的内部 ID。当前示例关系接口只有论文与会议的元数据关系，正式 Neo4j 查询由 C 后续接入。

运行测试：`python -m unittest discover -s tests -v`。演示 A 的导入验收：服务启动后运行 `python scripts/verify_week1.py`。详细步骤见 [第 1 周 A 交付验收](docs/第1周A交付验收.md)。
