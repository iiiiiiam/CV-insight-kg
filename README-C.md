# C · 第一周图谱查询原型

独立目录 `src/graph_query/`，不修改 A/B/D 的实现或现有接口。研究读取真实 Neo4j，不使用内存或 SQL 代替图查询。Python 3.10+，Neo4j 5.26 LTS，开发测试另需 pytest/httpx。

## 启动（Windows PowerShell）

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-graph-dev.txt
$env:NEO4J_PASSWORD = Read-Host '设置本地 Neo4j 密码（至少 8 位）'
$env:GRAPH_ADMIN_TOKEN = [guid]::NewGuid().ToString('N')
docker compose -f compose.graph.yaml up -d
.\.venv\Scripts\python.exe -m src.graph_query.cli init
.\.venv\Scripts\python.exe -m src.graph_query.cli import sample_data/graph/week1.json
.\.venv\Scripts\python.exe -m src.graph_query.cli check demo-c-week1
.\.venv\Scripts\python.exe -m src.graph_query.cli publish demo-c-week1 --allow-developer-fixture
.\.venv\Scripts\python.exe -m uvicorn src.graph_query.api:app --host 127.0.0.1 --port 8001
```

等待 Neo4j 启动后执行 init；如连接未就绪，稍后重试。不使用 Docker 时，在已有 Neo4j 5.26 实例配置 `NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE`。配置示例在 `graph.env.example`，程序读取进程环境变量，不自动加载文件。

- 演示页面：<http://127.0.0.1:8001/research>
- 可试用 API：<http://127.0.0.1:8001/docs>
- API JSON：<http://127.0.0.1:8001/openapi.json>
- 组合筛选：`/api/research/papers?topic=Object%20Detection&method=YOLO&year=2024`，夹具预期 2 篇。

首次发布 expected_active 为空。已有已发布批次时，CLI 必须加 `--expected-active 旧批次号`；这是防止覆盖队友发布的校验，不能跳过。不要删除数据卷来绕过冲突。

重复运行 import 应返回 `replay: true`，数量不变。相同批次号不同内容返回冲突；改用新批次号。未发布批次无法通过研究端 batch_id 读取。跨页面使用首次查询返回的 batch_id，可继续读取曾发布版本，避免发布切换造成混合数据。

## 样本与真实性边界

`sample_data/graph/week1.json` 是从 A 分支 `58bbbf0` 的真实 OpenAlex 样本截取的 5 篇论文（保留标题、摘要、作者、来源），附带少量可核对的标题/摘要提及。每条关系标为 developer-fixture，**不是 B 的真人审核结果**；默认不能发布，只有显式允许夹具才能演示。机构没有经过确认，未虚构补齐。八类实体与七类关系均在模型/约束中支持，夹具不强制凑齐八类。

B 分支当前 confirmed 导出为空，不能伪造“5 篇真人已确认”。完成真实审核后，先用 B 的 `load_exports/validate_exports` 验证完整导出包，再转换：

```powershell
.\.venv\Scripts\python.exe -m src.graph_query.b_adapter path/to/confirmed.json path/to/new-batch.json --batch-id reviewed-week1 --source-batch-id A-source-batch
.\.venv\Scripts\python.exe -m src.graph_query.cli import path/to/new-batch.json
.\.venv\Scripts\python.exe -m src.graph_query.cli publish reviewed-week1 --expected-active demo-c-week1
```

转换器核对已确认状态、确认事件、原始输入指纹、证据偏移/元数据路径、同批端点；不替 B 完成人工判断。B 格式仍是 draft，适配器只接受明确的这一版本，不悄悄兼容未知字段。元数据关系、抽取候选、确认知识必须区分。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/graph/test_contract.py -q
# 请只指向可丢弃的专用测试数据库；测试会导入测试批次并切换发布指针。
$env:GRAPH_TEST_URI = 'bolt://127.0.0.1:17687'
$env:GRAPH_TEST_PASSWORD = 'your-test-database-password'
.\.venv\Scripts\python.exe -m pytest tests/graph -q
```

没有 GRAPH_TEST_URI 时，真实数据库集成测试明确显示 skipped，不计为通过。不能拿单元测试替代真实图验收。

若安装包下载不可用，可用官方 Neo4j Harness 5.26 启动同样的实际存储和 Bolt 引擎（仅测试，**无认证**，只监听 127.0.0.1:17687）。需要 Java 21 与 Maven：

```powershell
cd tests/graph/harness
mvn compile dependency:copy-dependencies -DoutputDirectory=target/dependency
java -cp "target/classes;target/dependency/*" GraphHarness
# Linux/macOS classpath 用冒号替代分号。
```

## 对接与范围

- [图模型与 A/B 接入](docs/graph/model-and-write.md)
- [C API 与全项目边界契约 v1](docs/graph/contracts.md)
- [验收记录与后续事项](docs/graph/verification.md)

管理员路由使用环境中的服务 Bearer token，默认关闭；应由 D 验证管理员会话后通过服务器代理调用，不能把 token 放入前端。该模块不取代 D 的登录/退出服务。当前同源演示不配置跨域；D 可用开发代理接入。作者/机构接口本周只交付带证据邻居的画像骨架，完整合作网络与聚合统计属于后续周次。

所有改动在 `feature/graph-week1` 开发；通过 PR 请组员评审，保持 main 不变，不强推。
