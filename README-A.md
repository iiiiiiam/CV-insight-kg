# A · 论文数据管理

使用 Python 3.12 和 Node.js 22.18 或以上版本，在仓库目录安装依赖，然后启动：

```bash
python -m pip install -r requirements-dev.txt
python -m server.run_local --demo
```

启动时构建界面并运行 A、采集任务和网页服务。浏览器打开终端给出的 `/preview` 地址。首次创建独立演示库，同时准备200篇真实补充论文，点击后才加入正式库；已有数据和配置保留。完整 CVPR 数据可在首次创建时通过 `--cvpr-jsonl <文件路径>` 指定。关闭终端中的启动进程会同时停止它创建的子进程。

- 数据概览：去重论文、每日新增、来源、摘要完整率和最新 20 篇论文主页。
- 论文导入：从补充论文库选择范围和数量，导入下一批新论文。
- 导入记录：来源与会议筛选、进度、新增/重复/过滤/失败、论文核对、失败重试和数据导出。

验证：

```bash
python -m unittest discover -s tests -p 'test_reserve.py' -v
```

数据范围、交接及演示说明见 [A 数据管理说明](docs/data-management-overview.md)。
