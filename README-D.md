# D 端本轮原型

## 1. 交付范围

在原仓库新增 Vue 3 前端和 FastAPI D 网关；A 的 `app/`、B 的 `src/knowledge_builder/`、样本及既有文档保持不变。

| 功能 | 当前实际实现 | 对应需求 |
| --- | --- | --- |
| 研究工作台 | A 真实论文列表；标题/摘要关键词、年份、导入批次筛选；详情、作者、稳定 ID、来源、批次 | FR01、FR02 的现有 A 数据部分 |
| 元数据关系图 | 转发 A 的 `paper_metadata` 图；论文—`PUBLISHED_IN`→会议；选中联动、高亮、点击详情、缩放与节点类型显隐 | FR03、FR06 的元数据交互部分 |
| B 候选查看 | 直接调用 B 已交付代码，读取校验后的固定 20 篇快照；实体/关系候选、诊断、版本、输入指纹、原文证据及高亮 | FR09 的候选与证据部分 |
| 管理员会话 | 服务端验密、登录、查询会话、退出、会话撤销、Cookie、CSRF、权限验证 | FR12 |
| 数据管理 | 基准清单、创建真实导入、任务/批次论文/错误、A 允许的原批次重试；D 网关保护管理接口 | FR08、FR12 的集成部分 |
| 菜单与组件 | 全部 20 个三级菜单入口；未实现项有明确占位；加载、空态、失败重试、抽屉与图谱组件 | 第 1 周 M0、NFR10 |

**C 正式图谱待接入。** 当前未实现 Neo4j 查询、2 跳扩展、确认后的主题/方法筛选、人工审核写入或批次发布。B 的全部候选仍为 `pending`，提及不代表论文使用或验证了某方法。关联洞察扩展留待基础任务完成后进行。此版本不能作为整个团队第一周全部功能已验收的证明。

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

安装前端依赖：

```powershell
cd frontend
npm install
```

## 3. 启动

从仓库根目录分别打开三个终端：

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

打开 <http://127.0.0.1:5173>。开发服务器把 `/api` 代理到 D，再由 D 调用 A。浏览器使用同源 HttpOnly Cookie 会话，不需要把 A 管理令牌放在前端。

`server.run_a` 使用忽略提交的 `server/.local/a-demo.db`；首次启动自动导入 A 的固定 20 篇样本。它设置 A 已有的 `LOCAL_DEMO=0` 和令牌配置，不改 A 源代码。A 原来的 `python run.py` 继续保留原行为；D 联调使用上述包装入口，两者不要同时占用 8000 端口。

需要构建后运行时，在 `frontend` 执行 `npm run build`，再启动或重启 D 网关；它会直接提供 `frontend/dist`，此时访问 <http://127.0.0.1:8001>，无需前端开发服务器。

会话存放在 D 的单进程内存中，重启后需重新登录；请使用默认单 worker。HTTP localhost 配置下 `COOKIE_SECURE=false`，同一轮操作使用同一主机名。修改端口时同步修改 `server/.env` 的 `ALLOWED_ORIGINS`、`A_API_BASE_URL` 和 Vite 代理。

## 4. 验收步骤

1. 匿名打开研究工作台，应看到真实论文；搜索标题/摘要关键词、指定年份或批次，检查结果及空态。
2. 点击不同论文，右侧对应论文节点高亮；关系仅为论文与会议。点击节点或论文详情按钮，查看元数据、稳定标识与来源链接。
3. 匿名进入数据管理应跳转登录；直接请求 `/api/admin/datasets` 应返回 401。错误密码被拒绝，正确密码可登录。
4. 在“会话与权限验证”测试权限，再进入“创建固定样本导入”，导入同一数据集；任务与批次增加，论文去重后总数仍为 20。每篇论文可属于多个导入批次。
5. 在“候选与证据查看”选择论文和候选，核对 B 原文证据、字段路径和指纹。全部候选应显示待审核，确认数为 0。
6. 退出后管理接口返回 401；旧会话 Cookie 重放也应失败。停止 A 后研究页显示连接错误，不回退到合成论文。

固定样本只含 CVPR 2024；用其他年份检索为空是正常结果。列表及会议详情本轮最多展示前 100 篇。B 页面始终对应固定快照，不把它冒充为 A 后续新增论文的抽取结果。

## 5. 检查命令与验证状态

仓库根目录：

```powershell
# 不需要第三方包的检查
python -B -m unittest server.tests.test_snapshot_stdlib tests.test_b_extraction -v

# 安装依赖后运行 A/B 原有回归与 D 后端测试；隔离数据库
$env:DATABASE_URL = 'sqlite://'
.\.venv\Scripts\python.exe -m pytest tests server/tests -q
```

在 `frontend` 目录：

```powershell
npm test
npm run build
```

本次已通过：上述标准库检查 16 项、前端 Node 测试 8 项，以及新增 Python 和 TypeScript 脚本语法检查。未安装依赖，因此完整 FastAPI/鉴权集成测试、A 全量回归、Vue 类型检查/构建及浏览器运行验收尚未执行，不声明其通过。

接口与组件契约见 [D 端接入契约](docs/d_integration_contract.md)。