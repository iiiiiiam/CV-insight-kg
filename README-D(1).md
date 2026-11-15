# CV Insight KG · D 前端与集成网关

D 提供 Vue 3 前端、FastAPI 网关和管理员会话，将 A 的原始论文、B 的知识审核、C 的图谱查询与批次发布接入统一界面。

本文是 **D 整合环境的运行与操作说明**。命令默认在 Windows PowerShell 中执行；除注明外，工作目录均为仓库根目录。安装、启动和验收由使用者自行执行。

## 1. 职责与当前范围

| 部分 | 负责内容 | D 的接入方式 |
| --- | --- | --- |
| A | 原始论文、基准清单、导入任务、导入批次和元数据关系 | 后端通过 HTTP 调用 A，保留 A 的业务规则 |
| B | 候选抽取、证据、人工审核、存档和业务导出 | 复用 `src/knowledge_builder/`，读取固定样本及审核存档 |
| C | Neo4j 存储、检索、节点详情、1—2 跳、批次导入与发布 | 后端通过 HTTP 调用 C，复用其 B 转换器和详情组件 |
| D | 页面、交互、展示适配、登录权限、统一管理入口 | `frontend/` 与 `server/` |

```text
浏览器
  └─ Vue 前端（开发时 5173；构建后也可由 D 的 8001 提供）
      └─ D 网关（8001）：会话、权限、请求转发和展示适配
          ├─ A 服务（8000）→ A 数据库
          ├─ B Python 模块 → 固定样本、词表和审核存档
          └─ C 服务（8002）→ Neo4j Bolt（7687）
```

主要接入代码已提供，但不能据此宣布完整项目或新增 C 链路已全部验收。真实 B 人工确认结果从审核到入库、发布、研究查询的全过程，仍需在实际环境中验证。

### 1.1 三种数据状态

| 状态 | 含义 | 是否进入正式研究图谱 |
| --- | --- | --- |
| A 已导入 | 原始论文已保存，可以查来源和导入批次 | 不会仅因导入而进入 |
| B 已确认 | 候选实体或关系经人工核对，决定保存到 B 存档 | 还需要生成、导入并发布图谱批次 |
| C 已发布 | 某一版确认结果已发布为图谱快照 | D 只接受 `reviewed_export` 来源的发布批次 |

**默认研究页查询 C，不查询 A。** A 原始论文保留独立入口。C 不可用或尚无正式发布时，不回退到 A，也不使用开发夹具补足。

## 2. 环境与端口

### 2.1 环境要求

- Python 3.10 或更高版本；已有且可用的 `.venv` 可以继续使用。
- Node.js 22.18 或更高版本。
- Neo4j **5.26 Community**，数据库名 `neo4j`。
- ZIP 部署 Neo4j 时，需要兼容 Java，建议 JDK 21。
- Docker 是可选方式；已有 ZIP 数据库时无需再启动 Docker 数据库。

| 用途 | 依赖清单 |
| --- | --- |
| 整合运行的 Python 依赖 | `server/requirements.txt`，包含根目录及 C 的依赖清单 |
| Python 开发测试 | `server/requirements-dev.txt` |
| 前端运行、构建和测试 | `frontend/package.json` |

### 2.2 端口用途

| 端口 | 服务 | 用途 |
| --- | --- | --- |
| 5173 | Vue 开发服务器 | 日常前端页面，将 `/api` 代理到 D |
| 8001 | D 网关 | 登录、权限、A/C 代理、B 操作；有构建产物时也提供页面 |
| 8000 | A 服务 | 原始论文、导入管理和任务接口 |
| 8002 | C 服务 | 图谱查询、详情、批次导入和发布 |
| 7687 | Neo4j Bolt | C 的 Python 驱动连接数据库，不是网页地址 |
| 7474 | Neo4j Browser / HTTP | 登录数据库、手动执行 Cypher |


同一轮操作统一使用 `127.0.0.1`，避免与 `localhost` 混用产生不同的浏览器会话。第一周各自在本机部署；`127.0.0.1` 指当前电脑。

## 3. 首次安装与配置

### 3.1 安装依赖

进入仓库根目录：

```powershell
cd D:\codex_data\insight\CV-insight-kg
```

只有没有虚拟环境时才需要创建：

```powershell
python -m venv .venv
```

安装运行依赖，初始化本地配置：

```powershell
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
.\.venv\Scripts\python.exe -m server.init_local
.\.venv\Scripts\python.exe -m server.init_c
```

安装前端依赖：

```powershell
cd frontend
npm install
cd ..
```

`server.init_local` 在不存在时生成 `server/.env`，已有文件不会覆盖；`server.init_c` 补齐缺失或空的 C 地址及服务令牌，保留已有非空配置。

### 3.2 D 配置：`server/.env`

| 配置项 | 含义 |
| --- | --- |
| `ADMIN_USERNAME` | D 管理员账号，初始为 `admin` |
| `ADMIN_PASSWORD` | D 登录密码，初始化时随机生成，在本地文件中查看 |
| `SESSION_SECRET` | D 会话签名密钥 |
| `SESSION_TTL_SECONDS` | 会话有效期，默认 3600 秒 |
| `COOKIE_SECURE` | 本地 HTTP 使用 `false` |
| `ALLOWED_ORIGINS` | 允许的前端来源；改端口时同步调整 |
| `A_API_BASE_URL` | 默认 `http://127.0.0.1:8000` |
| `A_ADMIN_TOKEN` | D 与 A 包装启动入口复用的服务令牌 |
| `C_API_BASE_URL` | 默认 `http://127.0.0.1:8002` |
| `C_ADMIN_TOKEN` | D 调用 C 管理接口的服务令牌 |
| `B_REVIEWS_DIR`（可选） | B 审核目录，相对路径按仓库根目录解析 |
| `B_VOCABULARY_PATH`（可选） | 与审核存档匹配的 B 词表版本 |

真实密码和令牌只保留在本地配置，不写进 README 或提交到仓库。修改配置后重启相关服务。

### 3.3 Neo4j 配置：根目录 `graph.env`

新建根目录 `graph.env`，或参考 `graph.env.example`；已有文件直接编辑，不覆盖实际配置。

```dotenv
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=替换为本机数据库实际密码
NEO4J_DATABASE=neo4j
```

`graph.env` 与 `server/.env` 是不同文件，均已被 Git 忽略。数据库密码、D 登录密码、D/C 服务令牌是三种不同凭据。

整合入口 `server.run_c` 自动读取 `graph.env`，并将 D 的 `C_ADMIN_TOKEN` 用于 C 管理鉴权，无需另行生成一套 `GRAPH_ADMIN_TOKEN`。若手动启动独立 C 服务，必须保证其 `GRAPH_ADMIN_TOKEN` 与 D 的 `C_ADMIN_TOKEN` 一致。

配置加载不覆盖已有进程环境变量；若当前终端以前设置过相关变量，应确保它们与配置文件一致。

### 3.4 B 的样本与存档

B 默认读取 `examples/week1_baseline.json` 的固定 20 篇样本及引用文件，使用当前默认词表；审核目录遵循 B 的规则，通常为 `data/knowledge_builder/reviews/`。

- 存在旧 `data/b_reviews/` 时沿用 B 的检测规则；新旧目录同时有记录会报错，不混读。
- 未指定 `B_REVIEWS_DIR` 时，兼容已有的 `KNOWLEDGE_WORKBENCH_DATA/reviews`。
- 旧版存档需要匹配词表，例如 `examples/knowledge_builder/vocabulary_v0.1.json`，不能将旧确认套到新版抽取。
- 每次请求重读并校验样本、词表、存档。审核后点击“重新读取存档”即可；改变路径配置需要重启 D。
- A 后续新导入的论文，不会自动全部进入 B 当前的固定样本审核流程。

## 4. 启动数据库与应用

### 4.1 ZIP 方式启动 Neo4j

解压 Neo4j 5.26 Community 并准备兼容 Java。以下目录为示例，替换为实际解压路径：

```powershell
cd D:\tools\neo4j-community-5.26.x
java -version
.\bin\neo4j console
```

保持数据库终端运行，另开终端操作项目。已配置 Windows 服务时可使用服务方式，不要再同时启动同一实例的 console。

打开 <http://127.0.0.1:7474>，连接 `bolt://127.0.0.1:7687`，使用本机账号密码登录。全新且尚未设定初始密码的实例通常以 `neo4j/neo4j` 首次登录，再按提示更改；已有实例使用原来的实际密码。将最终密码同步到 `graph.env`。

在 Browser 中选择 `neo4j` 数据库，执行：

```cypher
RETURN 1 AS ok;
```

返回 `ok = 1` 表示数据库账号和查询可用，不代表已导入或发布业务数据。

### 4.2 Docker 方式（与 ZIP 二选一）

已有 ZIP 数据库时跳过本节。安装并启动 Docker Desktop 后，在仓库根目录使用已填写的 `graph.env`：

```powershell
docker compose --env-file graph.env -f compose.graph.yaml up -d
docker compose --env-file graph.env -f compose.graph.yaml ps
```

项目镜像为 `neo4j:5.26-community`，绑定本机 7474、7687；健康状态应最终为 `healthy`。数据保存在命名卷中。已有数据卷的密码不会因修改配置文件而自动改变。

### 4.3 分别启动 A、C、D 和前端

每个命令使用单独终端。A、C、D 从仓库根目录执行，前端命令在 `frontend` 中执行。

```powershell
# A：8000
.\.venv\Scripts\python.exe -m server.run_a
```

```powershell
# C：8002；先确保 Neo4j 正常运行
.\.venv\Scripts\python.exe -m server.run_c
```

```powershell
# D：8001
.\.venv\Scripts\python.exe -m server.run
```

```powershell
# 前端：5173
cd frontend
npm run dev
```

打开 <http://127.0.0.1:5173>。Windows 也可使用 `start-a-for-d.cmd`、`start-c.cmd`、`start-d.cmd`、`start-frontend.cmd`；这些入口不安装依赖。

注意：

- A 包装入口以既有受保护模式运行，默认数据库为 `server/.local/a-demo.db`；没有成功固定样本任务时导入基准样本。可用 `D_A_DATABASE_URL` 指定其他数据库。
- A 原来的 `python run.py` 保留原行为，不要与上述入口同时占用 8000；两种启动的数据库配置不一定相同。
- `server.run_c` 在启动时执行 C 已有的 Schema 初始化，不自动导入或发布样本。
- README-C 的独立启动示例使用 8001；D 整合环境使用 8002，以本文入口为准。
- D 使用单进程内存会话，保持默认单 worker，重启后需重新登录。
- 仅展示 A 原始论文与 B 审核时，可以先启动 A、D、前端；默认 C 研究页此时可能提示不可用。

### 4.4 构建后由 8001 提供前端

```powershell
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m server.run
```

已有 D 进程时先在其终端停止，再启动。D 检测到 `frontend/dist/index.html` 后提供构建页面，访问 <http://127.0.0.1:8001>，无需启动 5173。

开发源入口是 `frontend/index.html`，构建入口才是 `frontend/dist/index.html`。修改源码后，5173 可更新开发页面；8001 的构建页面需要重新构建并刷新。

## 5. 页面与菜单

20 个三级菜单入口对应多个复用页面，不等于 20 个独立完成的业务页面。

| 入口 | 当前功能与边界 |
| --- | --- |
| 原始论文（A，工作台切换入口） | 列表、标题/摘要关键词、年份、导入批次、详情和来源；图仅含 Paper、Venue、PUBLISHED_IN |
| NAV01 组合检索、NAV02 论文列表 | 同一 C 工作台；标题关键词、主题/方法精确名称或 ID、年份、发布批次；最多展示前 100 篇 |
| NAV03 论文详情 | 详情抽屉和独立地址；A 详情可附加 B 当前已确认内容，C 详情为固定发布快照 |
| NAV04 节点检索与定位、NAV05 1—2 跳探索 | 复用工作台；节点查询、起点定位、手动切换跳数；缩放、布局、类型显隐、节点详情及键盘列表 |
| NAV06 当前论文集导出、NAV07 导出进度与下载 | 占位；研究结果集导出任务未实现，与 B JSON/ZIP 下载不同 |
| NAV08 年度趋势与对比、NAV09 年份下钻与联动 | 占位；统计、图表和下钻未实现 |
| NAV10 作者证据画像、NAV11 机构证据画像 | 节点和有证据邻居骨架，不是完整合作统计，也不推断永久任职 |
| NAV12 基准清单 | A 的数据集、来源、数量及可用校验信息 |
| NAV13 创建固定样本导入 | 请求 A 导入基准，成功后进入任务详情 |
| NAV14 任务进度与批次论文、NAV15 错误与原批次重试 | 同一任务页；阶段、计数、日志、错误、论文及允许的重试；NAV15 暂无独立错误筛选，通过刷新读取状态 |
| NAV16 候选与证据查看 | B 原始/审核结果、三状态、实体/关系、原文定位、历史及诊断 |
| NAV17 审核与改名 | 在查看页上增加确认、驳回、实体显示名修改、撤回；证据只读 |
| NAV18 生成导入与校验 | B 确认结果预览、导入 C、按批次号查看校验；无完整历史批次列表 |
| NAV19 发布确认与状态 | 核对目标和当前发布版本，手动发布通过校验的正式批次 |
| NAV20 会话与权限验证 | 账号、到期时间、退出及受保护请求验证，不修改研究数据 |
| 管理员登录与侧栏状态 | 登录、返回原管理页面、退出；显示未登录/已登录/鉴权连接状态 |

研究页类型计数针对当前返回子图，不是全库统计。C 图查询每次最多请求 100 条路径，详情邻居由 C 限制并提供截断提示；不补造节点、关系或缺失内容。


## 6. 使用者自行查看的指标

以下为查看方法，不表示本次整理时已执行或全部通过。

| 查看位置 | 预期与解释 |
| --- | --- |
| Neo4j Browser：`RETURN 1 AS ok;` | 返回 1，账号和数据库查询可用 |
| A：`http://127.0.0.1:8000/api/papers?page_size=1` | HTTP 200，基准初始化后可读论文 |
| D：`http://127.0.0.1:8001/api/health` | D 存活，不代表 A/C 可用 |
| C：`http://127.0.0.1:8002/api/health` | HTTP 200、`status=ok`、`storage=neo4j`，真实数据库探活 |
| D：`http://127.0.0.1:8001/api/graph/health` | HTTP 200，代理健康检查通过；不证明已有正式发布或全部管理凭据有效 |
| A 原始论文页 | 可查论文、详情、来源；2 类实体与 1 类关系是元数据图正常范围 |
| B 审核页 | 候选证据对应，决定保存后刷新仍在，导出按状态隔离 |
| C 正式批次 | 来源 `reviewed_export`，校验通过且 `status=published` |
| D 正式研究页 | 正式批次可查，列表/详情/图谱批次一致；失败显示未知，成功无匹配才显示 0 |
| 管理权限 | 匿名管理请求 401；登录允许；退出后旧会话拒绝；写操作检查 CSRF |

## 7. 常见问题

| 现象 / 错误 | 原因及处理 |
| --- | --- |
| `KeyError: 'NEO4J_PASSWORD'` | CLI 未读文件或当前终端缺变量；按第 8 节设置，或使用下方显式加载命令 |
| `ModuleNotFoundError: neo4j` | 缺 Python 驱动，由使用者安装 `server/requirements.txt`；驱动不等于数据库软件 |
| Bolt 无法连接 / 数据库不可用 | 确认 ZIP console 或服务运行，7687、账号密码及库名正确 |
| C 启动要求密码/令牌 | 核对 `graph.env`、`server/.env`，完成初始化并使用 `server.run_c` |
| `503 C_SERVICE_UNAVAILABLE` | D 无法连接 C，查看 8002 和 `C_API_BASE_URL` |
| `503 C_ADMIN_NOT_CONFIGURED` | D 未配 C 管理令牌，运行 `server.init_c` 后重启 D/C |
| `503 C_SERVICE_CREDENTIALS_INVALID` | D/C 服务令牌不匹配，不表示 D 登录过期 |
| C 的 `503 GRAPH_UNAVAILABLE` | C 已收到请求，但数据库查询不可用，查看数据库与 C 日志 |
| `404 PUBLISHED_BATCH_NOT_FOUND` | 尚无可读取发布，需完成审核、导入、校验、发布 |
| `409 REVIEWED_DATA_REQUIRED` | 发布来源为开发夹具等非正式数据，不能进入 D 正式研究页 |
| 研究页“数量未知”或“—” | 请求失败，不代表论文清空；查看具体错误，也可切换 A 原始论文 |
| `/api/admin/session` 返回 401 | 未登录或会话过期的反馈，不阻止公开查询 |
| 8001 首页 404，但接口可用 | 无构建产物或启动时未加载；开发访问 5173，或构建后重启 D |
| `B_TO_C_VALIDATION_FAILED` | 核对各确认分区论文实体、端点、名称和证据，不伪造确认补齐 |
| `KNOWLEDGE_SNAPSHOT_CHANGED` / `GRAPH_PREVIEW_CHANGED` | B 数据变化，重新读存档并生成预览 |
| B 版本、指纹或目录冲突 | 使用匹配词表及正确目录；不将坏存档当空数据，也不自动清空 |
| B 已确认但图谱没更新 | 还需生成新批次、导入、校验、发布及读取最新发布 |
| 相同批次号内容不同 | 批次不可变，使用新号 |
| 发布版本冲突 | 重新读取当前版本核对，不删除数据库绕过 |
| 不同菜单页面相同 | 部分入口复用，组合检索/列表及任务/错误页有展示重合，详见第 5 节 |

CMD 与 PowerShell 环境变量语法不同。CMD 对应设置方式：

```cmd
set "NEO4J_URI=bolt://127.0.0.1:7687"
set "NEO4J_USER=neo4j"
set "NEO4J_DATABASE=neo4j"
set /p "NEO4J_PASSWORD=请输入本机Neo4j数据库密码："
```

也可在 CMD / PowerShell 中显式读取根目录文件后调用 CLI，例如初始化：

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('graph.env'); from src.graph_query.cli import main; main()" init
```

更多规则见 [B 文档](docs/knowledge_builder/README.md)、[C 模型与写入](docs/graph/model-and-write.md)、[C 接口说明](docs/graph/contracts.md)。模块文档中的历史“D 待接入”等状态不代表当前 D 代码状态；D 的整合启动端口和操作流程以本文为准。
