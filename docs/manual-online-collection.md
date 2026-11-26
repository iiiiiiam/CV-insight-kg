# 手动在线采集与整合后台处理

更新：2026-11-25。本次补充保存在本地待检查版本，尚未推送。

## 演示方式

在“论文导入”页选择会议年份、本次数量及可选关键词，点击“采集并入库”。默认使用 CVPR 2025、20 篇；可选择 10、20、30 或 50 篇。采集从 OpenAlex 实时请求，排除当前已入库论文，获取摘要、作者、来源、主题和关键词等字段。

当前演示库原有 CVPR 2024、ICCV 2023、ECCV 2024，CVPR 2025 适合展示新增年份。已验证 OpenAlex CVPR 2025 查询可用，官方目录：https://openaccess.thecvf.com/CVPR2025 。

页面显示采集、入库及后台接收进度。完成后可查看本批论文，再返回论文导入页。连续点击会继续选取尚未入库的论文；关键词用于 OpenAlex 的论文检索。每次最多扫描 5 页，达到上限或符合条件论文不足时显示实际采集数量。

来源失败时明确显示失败，保留已获取内容与分页进度；重试沿用同一任务。正式入库失败只重试失败记录。未获得新论文时完成为“无新增”，保留当前知识结果。

## 后台链路

网页提交请求后，已有 A worker 完成网络请求和正式入库。成功批次仍写入原有版本账本，支持去重、撤回、重试、质量核对和报告。

整合启动入口默认使用 A_B_TRANSPORT=local，worker 直接调用 B 已有 BatchRegistry 的接收与撤回逻辑，沿用输入校验、原子存储和版本规则，并保存处理回执。A 和 B 使用同一配置中的 B_BATCH_REGISTRY；无需为内部调用额外登录或等待另一个 HTTP 接收服务。

独立部署仍可使用 A_B_TRANSPORT=http，沿用原有 B 服务地址与会话配置。源补充与 C 图谱发布各有自己的状态，A 入库完成不替代发布验收。Papers with Code 读取和 C 发布逻辑没有改动。

原定时采集代码保留为后续能力，当前页面改为手动在线采集，启动入口不再自动启动采集调度进程。

## 接口

| 接口 | 用途 |
| --- | --- |
| POST /api/admin/online-collections | 按会议、年份、数量和可选关键词创建采集入库任务 |
| GET /api/admin/online-collections/{id} | 获取网络采集进度、入库数量和后台任务状态 |
| POST /api/admin/jobs/{id}/retry | 立即重试同一任务 |

沿用现有管理员会话和 CSRF。创建参数为 request_key、venue、year、count、keyword；同一 request_key 重发幂等，参数变化返回 409。GET 返回 selected_count、imported_count、new_count、existing_count、progress、error、next_retry_at、background_task 等。已形成的批次沿用正式批次接口撤回。

## 本地验证

- 真实联网连续采集 CVPR 2025 两批，每批新增 20 篇，第二批跳过前一批 20 篇；A 和整合知识模块均为 40 篇。
- 使用数据库副本完成真实浏览器点击，420→440，补充库数量保持不变；进度、查看本批、返回、刷新恢复及 390px 布局通过。
- 全程使用实时来源，无补充库或本地样本回退。

```bash
python -m pytest -q tests/test_online_collection.py
python -m scripts.verify_manual_online --database server/.local/a-demo.db --browser-executable /path/to/chrome --output reports/manual-online-check
```

浏览器脚本使用临时服务和数据库副本，完成后关闭自身服务。原演示库不被验证脚本修改。
