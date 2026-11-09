# C 接入 knowledge-effective/1.0

## 本轮范围与结果

只修改 C；没有执行 Git 命令、改动 B/D、读取浏览器凭据或操作 Docker 数据卷。B 参考目录为同级 `CV-insight-kg-knowledge-enrich`，核对了 effective_export、反馈 provenance 计算、管理员路由、AuthService 和 SessionMiddleware。

新增 effective 独立验证/投影、原子完整快照导入、受保护 API、文件/HTTP 可替换来源、CLI 和真实 Neo4j 回归。旧 BatchInput/adapt_confirmed 和旧接口保留。

实际输入 revision：`6c97a76de785646616f2e13845a3c93fdc2ba26d280d56ea14b00e20013b9629`。

实际隔离测试批次：`effective-6c97a76de785646616f2e13845a3c93fdc2ba26d280d56ea14b00e20013b9629`。

- 150 篇论文；1848 个按论文计数的实体条目；2185 条关系。
- 稳定身份合并后 1314 个 CVEntity 节点，2185 条 CV_LINK；实体上下文共 1848 条，没有少导入。
- 全部 4033 条源条目是 automatic；human_confirmed=0、human_corrected=0；原文件 rule_adjusted=true 为 0。不生成 reviewer 或确认事件。
- 重复导入和只改变 generated_at 均复用同一批次；新 revision 生成新批次；删除测试减少一条关系；恢复原内容复用原版本并可重新发布。旧批次、其他批次完整保留。

这是临时隔离引擎的验证，测试结束实例停止，**并未导入或切换用户现有 Docker 的正式发布版本**。实际结果摘要见 effective-results.json；完整测试运行结果以本轮交付说明为准。

## 模型和版本

批次号由 `effective-` + 完整 revision 确定。相同内容在 generated_at 不同的情况下幂等；如果管理员撤回后内容恢复原版本，按 B 算法 revision 可以恢复原值，C 不人为制造新版本。

共用稳定 `content.key` 作为实体 id，`candidate_id` 作为论文内条目身份，绝不互换。关系存储身份由论文 key + candidate_id 派生，每条保留 candidate_id、paper_id、generation、review_state、rule_adjusted 和完整 evidence。边 status=effective 表示当前公共有效，不等于 human_confirmed。

共享实体的 name 是按来源论文 ID 排序后第一份的确定性代表名，不用最后一篇覆盖；`contexts` 保存每篇的完整 content/candidate_id/evidence/provenance/origin。论文详情和以论文为起点的子图按该篇覆盖 name/label；跨论文实体详情和作者画像需通过 contexts 展示可能存在的局部名称，不得将代表名解读成统一纠错。

论文节点的 `effective_partition` 完整保留 input、origin、entities、relations、source_classifications。原文与证据不进行 trim 或 Unicode 正规化，start/end 按 Python Unicode code point 保存，JS 切片应使用 `Array.from(text).slice(start,end).join('')`。分类单独保存，不造 mentions_topic，也不纳入提及主题统计。

来源 vocab 允许逐篇不同，批次 vocabulary_version=per-paper，详情 contexts.origin 保留实际版本。批次保留完整源文档作校验依据，但管理响应不回传巨大原始文档。source_entity_count 是源条目数，entity_count 是实际身份节点数；paper_count、relation_count、source_revision、review_state_counts_json 明确返回。

导入一个事务内完成；发布和幂等重放前重新验证保存的源文档并逐节点/逐边比较投影属性（包含实际端点、证据、版本与状态），发布时也核对实际数量。异常整批回滚，发布失败保留旧指针。所有历史和其他来源节点保留；当前仍沿用 C 原有单一 active 发布指针，不自动把别的来源拼接进新快照。研究查询可显式固定曾发布批次。

## 运行与发布

仓库根目录已有 .venv。配置 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD、NEO4J_DATABASE 到当前进程，密码不写进代码或文档。导入默认只生成 ready 批次：

```powershell
.\.venv\Scripts\python.exe -m src.graph_query.effective_cli ..\effective.json
```

先检查批次：

```powershell
.\.venv\Scripts\python.exe -m src.graph_query.cli check effective-6c97a76de785646616f2e13845a3c93fdc2ba26d280d56ea14b00e20013b9629
```

由用户核对完毕后显式发布，--expected-active 必须是数据库当前 active 批次；空库可省略：

```powershell
.\.venv\Scripts\python.exe -m src.graph_query.effective_cli ..\effective.json --publish --expected-active demo-c-week1
```

发布切换不会删除 demo-c-week1 或任何数据卷。不得为绕过 CAS 冲突而清库。

## C → D API

新增受 C 现有管理员服务 Bearer 保护的 `POST /api/admin/graph/effective`，body 是完整 knowledge-effective/1.0 文档。200 返回批次属性及 replay；401 缺少凭据；422 INVALID_EFFECTIVE_SNAPSHOT 表示格式、哈希、计数、端点或证据失败；409 QUALITY_CHECK_FAILED 表示保存投影损坏。导入不自动发布，后续沿用 GET /api/admin/batches/{id} 与 POST /api/admin/batches/{id}/publish 的 CAS。

研究端原 papers/entities/detail/graph/author-profiles/statistics 路径不变，必须传返回的 batch_id 固定快照。现在它们同时支持旧 confirmed 与新 effective 批次。统计 `basis.relations=public_effective` 表示自动结果也计入；返回 review_state_counts，不能写“全部人工审核”。分布新增 papers_with_effective_relation、papers_without_effective_relation；effective 批次旧 confirmed 计数字段为 null，旧批次兼容原值。D 应消费新字段并显示真实状态。

证据字段：effective 的 evidence 保留 B 原始 paper_id/dataset_id/source_url/input_fingerprint/field/quote/start/end/path，没有虚构 reviewer/reviewed_at。旧证据结构保持兼容。前端不要假设每条有效关系都有人工审核人。逐条实体状态从 contexts 或 effective_partition.entities 读取；边直接读取 generation/review_state/rule_adjusted。详情组件和 C 统计页已调整为有效知识措辞。

## B 自动获取：已实现来源层，尚未真实远程联调

FileEffectiveSource.load 与 HttpEffectiveSource.load 使用相同验证和 expected_revision 约定。HTTP 来源只调用 B 已有 GET /api/admin/knowledge/effective-export，检查状态码、X-Knowledge-Revision、内容版本，并禁止跟随重定向。不从 GitHub 获取数据，也没有定时任务。

B 当前通过 POST /api/admin/sessions 登录；SessionMiddleware 的签名 Cookie 名为 cvkg_session，其中 sid 对应 AuthService 单进程内存会话；过期、退出或进程重启会失效。GET require_admin，不需写 CSRF；它不是 Bearer/机器 token 接口。C 没有获取或存储任何管理员 Cookie、密码或签名密钥。

可由可信服务器代码注入已有认证的同步 HTTP 客户端（例如 httpx.Client），设置 B 的受信 base_url，使用 HTTPS 或本机回环地址，再调用 HttpEffectiveSource(client).load()。客户端会话的合法建立、生命周期与授权由调用方负责；本轮只用 MockTransport 测试此契约，未登录运行中的 B 服务。不能据此声称无人值守获取已打通。

建议 B/D 补充仅允许读取有效导出的服务身份：可撤销、可轮换、最小权限凭据或明确的服务登录/授权约定及安全传递方式，不复用全权限人类账号长期登录。无需为本轮编造轻量版本接口；现有完整 GET 已可返回当前版本，后续可选 ETag/轻量元数据优化。

## 浏览器演示与未完成事项

向目标实例导入、检查并由用户发布后，启动 C API 独立端口（避免占用 B/D 端口）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.graph_query.api:app --host 127.0.0.1 --port 8002
```

打开 `/research/analytics`，输入上面的完整批次号，查看 150 篇年份/主题/方法分布；搜索作者，选择稳定 ID，查看论文分页、机构证据与统计；点击论文详情与两跳子图。原 `/research` 页面支持列表和可视图谱；详情应显示 automatic 而非人工确认。来源分类在论文 effective_partition 中单独提供，待 D 决定展示位置。

本轮真实数据库检索/详情/子图/画像/统计接口已经测试；新增 UI 脚本做语法检查。浏览器逐项点击验收、B 真实管理员 HTTP 获取、B 实际操作后导出再同步的跨服务验收，以及 D 统一界面整合仍待完成。删除/恢复和公共局部改名是隔离测试构造的回归用例，不算对 150 篇做了真实人工审核。

## 文件清单

- 新增 src/graph_query/effective.py、effective_store.py、effective_source.py、effective_cli.py。
- 修改 repository.py、analytics.py、api.py、paper-detail.js、analytics.html，保留原功能与 confirmed 路径。
- 新增 tests/graph/test_effective.py、scripts/verify_effective_isolated.py、sample_data/graph/effective-minimal.json（真实样本单篇截取，用于普通 CI）。150 篇原始文件保持只读，不复制到版本管理路径。
- 新增 docs/graph/effective-handoff.md、effective-results.json、openapi.effective.json；README-C.md 增加入口。

普通 CI 自动发现新测试并用已有独立 Neo4j service 运行单篇 fixture。运行150篇验证请设置 EFFECTIVE_TEST_FILE 指向用户文件；也可在已准备好 Java21/Harness 依赖时运行 scripts/verify_effective_isolated.py --java JAVA_EXE --file ../effective.json。该脚本使用独立端口并在结束后停止自己的测试进程，不使用 Docker 管道。

最终实际测试：46 passed（36 项非数据库测试、10 项真实 Neo4j 测试），85.57 秒；1 条已有 Starlette/httpx 弃用提示。隔离 Neo4j Harness 5.26.0 端口17691，结束后已停止；没有对现有 Docker 实例执行导入或发布。
