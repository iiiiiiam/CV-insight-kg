# D 端本轮原型

## 0. 当前启动与 503 排查

D 的默认研究页现在读取 C（8002）的已发布图谱；A 的原始 20 篇论文仍通过 `/research/raw-papers` 查看。研究页请求失败时数量显示“—”，只有成功查询且确实无匹配结果时才显示 0。匿名访问 `/api/admin/session` 返回 401 是未登录状态，不会阻止公开论文查询。

若日志出现 `C_SERVICE_UNAVAILABLE`，先检查 C 的 8002 是否启动。D 的 8001 正常启动并不代表 C 或 Neo4j 已就绪。还可能遇到 Neo4j 不可用、服务令牌未配置/不匹配等 503；应查看响应中的具体错误代码。服务正常但没有发布批次时，C 返回 `PUBLISHED_BATCH_NOT_FOUND`（404），这与连接失败不同。

整合后的运行依赖入口为 `server/requirements.txt`，已包含 `requirements-graph.txt`；开发测试使用 `server/requirements-dev.txt`。本次不代装依赖。已有环境缺少 `neo4j` 时，由使用者执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
.\.venv\Scripts\python.exe -m server.init_c
```

`server.init_c` 只补齐缺失/空的 C 网关配置，不覆盖已有非空账号和配置；服务令牌写入被忽略的 `server/.env`，不会输出到终端。D 和 `server.run_c` 复用这一令牌。若 D 已启动，初始化后只需重启 D；不需要终止所有进程。

将 `graph.env.example` 复制为根目录 `graph.env`（已有文件不要覆盖），按实际 Neo4j 配置填写 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE`。该本地文件已被 Git 忽略。`server.run_c` 自动读取它，管理令牌使用 D 的 `C_ADMIN_TOKEN`。先启动可用的 Neo4j，再额外打开一个终端执行：

```powershell
.\.venv\Scripts\python.exe -m server.run_c
```

C 监听 `127.0.0.1:8002`。保留 A（8000）、D（8001）、前端（5173）三个现有终端；也可双击 `start-c.cmd`。不要同时使用 README-C 中占用 8001 的独立演示启动命令，也不要导入/允许发布开发夹具来填充正式研究页。

检查 D 的 `/api/graph/health` 后，在 D 管理页完成“B 人工审核 → 生成批次预览 → 导入 → 校验 → 手动发布”。每个有确认知识的论文分区需要确认对应论文实体，关系端点也必须已确认。导入不等于发布；没有发布时研究页保持提示，不回退到 A 冒充图谱。已打开研究页固定原批次，点击“读取最新发布”才切换。

## 1. 交付范围

在原仓库新增 Vue 3 前端和 FastAPI D 网关；A 的 `app/`、B 的 `src/knowledge_builder/`、样本及既有文档保持不变。

| 功能 | 当前实际实现 | 对应需求 |
| --- | --- | --- |
| 研究工作台 | A 真实论文列表；标题/摘要关键词、年份、导入批次筛选；详情、作者、稳定 ID、来源、批次 | FR01、FR02 的现有 A 数据部分 |
| 元数据关系图 | 转发 A 的 `paper_metadata` 图；论文—`PUBLISHED_IN`→会议；选中联动、高亮、点击详情、缩放与节点类型显隐 | FR03、FR06 的元数据交互部分 |
| B 候选与审核 | 原始/审核结果分开；管理员可确认、驳回、改实体显示名和撤回，记录登录账号与理由；证据只读 | FR09、FR12 |
| B 业务下载与已确认展示 | 管理端下载三状态 JSON 和完整 ZIP；论文详情匿名展示已确认实体、关系及证据，不显示待审、驳回和私有审核历史 | FR09 的结果交付、FR02 的知识详情部分 |
| 管理员会话 | 服务端验密、登录、查询会话、退出、会话撤销、Cookie、CSRF、权限验证 | FR12 |
| 数据管理 | 基准清单、创建真实导入、任务/批次论文/错误、A 允许的原批次重试；D 网关保护管理接口 | FR08、FR12 的集成部分 |
| 菜单与组件 | 全部 20 个三级菜单入口；未实现项有明确占位；加载、空态、失败重试、抽屉与图谱组件 | 第 1 周 M0、NFR10 |

**C 接入代码已增加，完整端到端验收尚未完成。** 默认研究页通过 D 代理 C，接入已发布批次的论文检索、主题/方法筛选、1—2 跳、节点详情与只读证据；作者/机构仅有证据邻居骨架。管理页支持从 B 已确认结果手动预览、导入、校验和发布。A 原始论文入口保留，两个来源不自动混用。仍未实现 D 页面证据编辑及复杂身份/类别/方向纠正。B 原始抽取保持 `pending`，审核决定单独保存；没有存档时不自动确认。提及不代表使用或验证。关联洞察扩展留待基础任务完成后进行。此版本不能作为整个团队第一周全部功能已验收的证明。

## 2. 依赖与配置

- Python 3.11 或更高版本；Node.js 22.18 或更高版本。
- Python 运行依赖：`server/requirements.txt`，复用 A 原始依赖清单并增加 D 依赖。
- Python 测试依赖：`server/requirements-dev.txt`。
- 前端依赖：`frontend/package.json`。以下由使用者自行安装，本次未代装依赖。

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server/requirements-dev.txt
.\.venv\Scripts\python.exe -m server.init_local
```

`server.init_local` 从 `server/.env.example` 生成本地 `server/.env`，已有配置不会覆盖。默认账号为 `admin`，随机密码在该文件的 `ADMIN_PASSWORD` 中；`SESSION_SECRET` 与 `A_ADMIN_TOKEN` 同时随机生成。该文件已被 Git 忽略，不需要更改 A 根目录的 `.env`。

B 数据默认复用 `data/knowledge_builder/reviews/`，并沿用 B 对旧 `data/b_reviews/` 目录的检测规则。新旧目录同时有记录时明确报错，不混读。可在 `server/.env` 选填 `B_REVIEWS_DIR` 指定审核目录、`B_VOCABULARY_PATH` 指定词表，路径相对于仓库根目录或使用绝对路径。若未显式设置审核目录且环境中已有 `KNOWLEDGE_WORKBENCH_DATA`，则读取该目录的 `reviews/`，与 B 原型一致。

旧版词表存档请配 `B_VOCABULARY_PATH=examples/knowledge_builder/vocabulary_v0.1.json`，同时选择对应审核目录。新版默认词表为 `cv-terms/0.2`；不会迁移或套用旧版确认。修改配置后仅需重启 D 网关。样本、词表和存档会在每次请求中重读，B 审核后点击页面“重新读取存档”即可查看，无需重启 D。

安装前端依赖：

```powershell
cd frontend
npm install
```

## 3. 启动

先按第 0 节完成 C / Neo4j 配置并启动 C（8002），再从仓库根目录分别打开以下三个终端：

```powershell
# 终端一：A 原代码的受保护启动入口，127.0.0.1:8000
.\.venv\Scripts\python.exe -m server.run_a
```

```powershell
# 终端二：D 网关，127.0.0.1:8001
.\.venv\Scripts\python.exe -m server.run
```

```powershell
# 终端三：Vue 开发服务器，127.0.0.1:5173
cd frontend
npm run dev
```

Windows 下也可分别双击 `start-a-for-d.cmd`、`start-d.cmd`、`start-frontend.cmd`。这些入口只启动程序，不安装依赖。

打开 <http://127.0.0.1:5173>。开发服务器把 `/api` 代理到 D；原始论文及导入请求由 D 调用 A，研究查询和图谱批次请求由 D 调用 C，审核复用 B 模块。浏览器使用同源 HttpOnly Cookie 会话，不需要把 A 管理令牌放在前端。

`server.run_a` 使用忽略提交的 `server/.local/a-demo.db`；首次启动自动导入 A 的固定 20 篇样本。它设置 A 已有的 `LOCAL_DEMO=0` 和令牌配置，不改 A 源代码。A 原来的 `python run.py` 继续保留原行为；D 联调使用上述包装入口，两者不要同时占用 8000 端口。

需要构建后运行时，在 `frontend` 执行 `npm run build`，再启动或重启 D 网关；它会直接提供 `frontend/dist`，此时访问 <http://127.0.0.1:8001>，无需前端开发服务器。

会话存放在 D 的单进程内存中，重启后需重新登录；请使用默认单 worker。HTTP localhost 配置下 `COOKIE_SECURE=false`，同一轮操作使用同一主机名。修改端口时同步修改 `server/.env` 的 `ALLOWED_ORIGINS`、`A_API_BASE_URL` 和 Vite 代理。

## 4. 验收步骤

1. 匿名打开“原始论文（A）”，检查原始论文、标题/摘要关键词、年份和导入批次。默认“已发布图谱（C）”只显示 B 已确认并手动发布的批次；未发布时提示，无服务时显示错误和未知数量。C 的关键词只查询标题，主题/方法按精确名称或 ID 筛选。
2. A 原始论文图仅为论文与会议；C 已发布图谱使用实际确认关系，检查节点定位、1—2 跳、详情与逐条证据，并核对列表/详情/图谱的 batch_id 相同。作者/机构页检查有证据邻居，不视为完整合作统计。
3. 匿名进入数据管理应跳转登录；直接请求 `/api/admin/datasets` 应返回 401。错误密码被拒绝，正确密码可登录。
4. 在“会话与权限验证”测试权限，再进入“创建固定样本导入”，导入同一数据集；任务与批次增加，论文去重后总数仍为 20。每篇论文可属于多个导入批次。
5. 在“候选与证据查看”检查原始/审核结果和三状态。进入“审核与改名”，核对证据、填写理由后操作；改名后仍待审，需要另行确认。关系两端未确认时应拒绝确认关系；撤回实体会让相关已确认关系退回待审。保存后 D 与 B 工具应能读取同一进度，原始抽取不改变。
6. 退出后管理接口返回 401；旧会话 Cookie 重放也应失败。停止 A 后研究页显示连接错误，不回退到合成论文。
7. 管理页下载区域提供已确认/待审核/已驳回 JSON 及完整 ZIP，范围为固定样本全部论文，不受当前论文和页面筛选影响。ZIP 内为 B 原格式的五个文件；没有已确认记录时 confirmed.json 为空，不补造结果。
8. 匿名打开论文详情，应只出现已确认实体、关系及证据，没有审核人、理由或私有历史。撤回后刷新详情，对应实体及联动关系应消失。不在 B 固定样本中的论文显示未覆盖提示；坏存档显示不可用，不把异常当成无确认内容。

固定样本只含 CVPR 2024；用其他年份检索为空是正常结果。列表及会议详情本轮最多展示前 100 篇。B 页面始终对应固定快照，不把它冒充为 A 后续新增论文的抽取结果。

概览、详情、审核提交和下载通过 `snapshot_revision` 核对同一版数据；存档变化时返回 409，不覆盖新决定。保存还复用 B 文件锁与磁盘 revision 检查，沿用已有自定义存档文件名。损坏、版本不符或重复存档明确报错，不清空、不回退；A 与登录仍可用。D 新提交使用服务端会话账号，浏览器不能指定 reviewer 或编辑证据。既有 B 历史仍可能包含自由填写的姓名；单管理员账号也不能区分其背后不同操作者。

## 5. 检查命令与验证状态

以下既有测试记录主要针对先前 A/B 适配，不代表新增 C 接入已完整验收。当前 C 接入仍需完成专项回归和真实 D → C → Neo4j 联调。

仓库根目录：

```powershell
# 不需要第三方包的检查
python -B -m unittest server.tests.test_snapshot_stdlib server.tests.test_knowledge_workflow_stdlib -v

# 安装依赖后运行 A/B 原有回归与 D 后端测试；隔离数据库
$env:DATABASE_URL = 'sqlite://'
.\.venv\Scripts\python.exe -m pytest tests server/tests -q
```

在 `frontend` 目录：

```powershell
npm test
npm run build
```

本轮已通过 D 标准库测试 20 项、前端 Node 测试 16 项，以及 Vue 类型检查和 Vite 构建。标准库测试覆盖审核保存、端点约束、撤回联动、旧窗口及文件锁冲突、失败不落盘、原始候选不变、公开内容过滤、三状态导出与 ZIP 的 B 校验。上轮 B 核心回归 49 项通过，本轮未修改 B 核心。

浏览器检查拦截 HTTP 请求后调用真实 D 应用层及 B 业务代码，使用独立程序测试目录完成审核保存、JSON/ZIP 下载、匿名详情与证据、冲突拒绝及撤回联动。它验证前端和业务层串联，不代替 FastAPI 会话/CSRF 集成验收。

已补充 FastAPI 测试，覆盖匿名/CSRF 拒绝、禁止伪造审核人和证据、公开数据过滤、下载及完整审核流程。当前 `.venv` 指向的 Python 解释器不可启动，已安装扩展为 cp310，与可用的 Python 3.12 不兼容，因此 HTTP 集成测试和 A 全量回归尚未运行；本轮未安装依赖。所有程序审核记录只在隔离测试目录，不计作真人确认，也没有修改真实业务存档。

## 6. 本轮 B 更新适配涉及文件

修改：`server/application/knowledge.py`、`server/api/main.py`、`server/api/schemas.py`、`frontend/src/services/knowledge.ts`、`frontend/src/views/CandidateView.vue`、`frontend/src/components/DetailDrawer.vue`、`frontend/src/navigation.ts`、`frontend/src/router.ts`、`frontend/tests/knowledge.test.ts`、`README-D.md`、`docs/d_integration_contract.md`。新增：`frontend/src/components/ReviewActions.vue`、`KnowledgeDownloads.vue`、`ConfirmedKnowledge.vue`，以及 `server/tests/test_knowledge_workflow_stdlib.py`、`server/tests/test_knowledge_review_api.py`。上轮只读适配的改动仍保留。A/B 原代码、样本和真实存档未改。

接口与组件契约见 [D 端接入契约](docs/d_integration_contract.md)。
