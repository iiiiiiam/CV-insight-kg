# Windows deployment work

## 当前启停方式（2026-11-24）

这是已有本机环境的统一启动工具，尚非完整安装包。在项目根目录，使用已安装项目依赖的 Python 执行：

```powershell
# 将路径替换为自己的项目 Python，不要求激活终端环境
& 'PATH\TO\python.exe' scripts/windows/launch.py --check
& 'PATH\TO\python.exe' scripts/windows/launch.py
```

第一条只检查配置、运行库及端口；通过后执行第二条，输入现有 Neo4j 密码（不回显）。工具按 Neo4j → C → A → D/B 启动，等待图谱同步后自动打开网页。保留控制终端；用完按一次 **Ctrl+C**，等待四项服务退出、回到 PowerShell 提示符后再关闭窗口。重启仍执行第二条命令，不需要重新构建或重复初始化账号。前端源码更新后须先执行 `npm --prefix frontend run build`。

需先有 `server/.env`、已构建前端、`data/windows-preview` 及 Java/Neo4j 运行库；不能只克隆代码就直接运行。沿用现有本地数据，日志在 `.cache/windows-launcher/`。密码、运行库和用户数据不随 Git 提交。实际配置范围及前置条件见下文。

已在开发者 Windows 上实测源码统一启动、停止和新终端恢复；另有下述便携候选的第二台基本验证。完整数据一致性、全部功能和安装包验证尚未完成。

## Implementation notes

### 便携候选构建与验证

便携主程序交互：控制台输出同步到 `user-data/logs/launcher-*.log`；启动/运行错误清理后等待回车，防止双击闪退看不到原因；系统文件锁阻止同一用户重复启动便携主程序，退出后锁自动释放。`--check` 及内部服务不进入交互等待。当前 17 个相关测试通过，204312 的新增交互已在开发机和第二台实测。

后续实测：204312 候选在开发机英文路径下，首次双击窗口保持、重复启动拒绝及回车关闭提示、原实例 Ctrl+C 正常停止均通过；主日志退出码、Neo4j `Stopped.` 与端口释放已核对。用户随后将 204312 干净候选复制到第二台，确认图谱及知识页、双击窗口保持、重复启动拦截和原实例 Ctrl+C 停止通过，端口检查无输出。第二台结果依据用户反馈，不等于全部异常退出场景覆盖。

中文路径按当前安排暂缓，继续要求英文、无空格、可写目录。用户仍应 Ctrl+C 正常停止，不直接关窗；意外关窗后的完整清理仍是待完善项。

`build_portable.py` 用独立 Python 3.11 环境及 PyInstaller 6.22.3 构建文件夹模式程序。开发环境依赖见 `requirements-build.txt`。在仓库根目录运行：

```powershell
& 'PATH\TO\build-python.exe' scripts/windows/build_portable.py --java-zip 'PATH\TO\original-java.zip' --neo4j-zip 'PATH\TO\original-neo4j.zip'
```

仅构建，不启动服务。输出为 `dist/windows/时间戳/ResearchInsight/`，不覆盖历史输出。必须完整复制文件夹，不能只拿 exe。Java/Neo4j 从原始 ZIP 提取，Neo4j 的 data、logs、run 等不复制；不会读取本机数据库、反馈、账号或 `.env` 来制包。

候选版运行时将写入自己的 `user-data/` 和 `runtime/neo4j/data/`，因此应解压到可写目录；不要放 Program Files。首次启动生成随机管理员账号密码及服务/数据库凭据，管理员登录信息仅在本地 `user-data/管理员登录信息.txt` 保存。Neo4j 初始密码通过其管理命令配置（该初始化命令需短暂通过进程参数传入密码，但不会打印命令或输出）。不关闭数据库认证。

本版 B 使用 Git 中的 20 篇基线，A 从基线和 60 篇补充样本初始化，不复制开发机的 150 篇增强语料或人工处理状态。后续完整数据方案须与团队确认。包内有构建版本、是否包含未提交改动、依赖及运行库哈希记录。

首次实际运行需验证冻结后的服务启动、后台任务和路径。`server/process_command.py` 保持源码模式的 `python -m` 行为，冻结模式仅派发允许的服务；原本机入口仍可使用。已经运行过的便携目录包含个人数据，不能直接再次分发，应发送未运行过的新构建副本。

本轮检查：4 个启动模拟测试与 10 个打包约束测试通过。2026-11-24 构建的 195755 完整候选无需手工补资源，在开发机启动、停止和重启正常（20 篇论文、10 个共享实体、54 条总览连接，知识页可跳转）。用户反馈第二台 Windows 11 家庭版 x64（已有系统 Python 3.13、无 Java）运行后自动打开网页、论文数量及跳转正常；PowerShell 受控启动保持运行正常，Ctrl+C 后返回提示符、五个端口无监听。没有据此证明完全无 Python 系统、所有后台任务或全部功能均通过。

第二台此前双击窗口消失，期间混有重复启动、关闭窗口操作，曾残留 Neo4j，已确认归属后请求退出并确认端口释放。PowerShell 受控运行未复现异常；后续 204312 的正常双击和重复启动交互已在两台验证；意外关窗清理仍待完善，此前窗口消失原因未完全确定。现在可双击运行并保留控制窗口，用一次 Ctrl+C 正常退出；PowerShell 启动供排错使用。

Neo4j 5.26.33 中文路径解析存在兼容问题，当前验证限定于英文、无空格、可写路径。中文路径兼容、安装/卸载、完整数据与全功能验收仍待完成。便携模式直接调用包内 Java，不经过 PowerShell 拼接 Neo4j 参数；同时处理冻结环境的外部 DLL 搜索路径。

Developer preview: one console supervises the existing local Neo4j, C, A and
D/B services. This is not yet a distributable runtime or installer.

Run from the repository root using the Python environment that already runs
the application:

```powershell
& 'PATH\TO\python.exe' scripts/windows/launch.py --check
& 'PATH\TO\python.exe' scripts/windows/launch.py
```

`--check` starts nothing. The normal command prompts for the existing Neo4j
password, waits for services and graph synchronization, then opens the browser.
Keep the terminal open; **Ctrl+C** stops the services it created in reverse order.
If graceful shutdown times out, it attempts to stop only that owned process tree.
Do not close the terminal window as a substitute for this shutdown operation.

Neo4j uses a dedicated hidden console and `console_stop.py` sends Ctrl+C to that
console. It must not use Ctrl+Break (the JVM emits a thread dump). The helper
does not send a broadcast to the user's console. Windows signal behavior is
documented at https://learn.microsoft.com/en-us/windows/console/generateconsolectrlevent.
Neo4j gets up to 60 seconds to finish before the last-resort owned-tree stop.

Prerequisites:

- Configured application Python dependencies and existing `server/.env` tokens.
- Built `frontend/dist` matching current source (`npm --prefix frontend run build`).
- Existing `data/windows-preview` from the manual local setup.
- One extracted Java and Neo4j distribution under `.cache/windows-runtime/java/*`
  and `.cache/windows-runtime/neo4j/*`, or explicit `--java-home` and `--neo4j-home`.
- Free ports 7474, 7687, 8000, 8001 and 8002.

Data/configuration follow the existing preview setup. `B_SOURCE_CORPUS` and
`B_VOCABULARY_PATH` retain environment/server configuration, with their resolved
paths printed for review. The supervisor never clears data, disables database
authentication or generates new administrator credentials. It uses the existing
automatic graph synchronization, which may publish current B knowledge to C;
normal startup is not read-only.

Logs are per-run under ignored `.cache/windows-launcher/`. Treat application logs
as local diagnostic data; review before sharing. No downloads, package installation
or frontend builds run automatically. Python/Java/Neo4j binaries, passwords and
personal data must not be committed with this tool.

Current verification: 14 focused mocked/resource tests, developer-machine source
and portable lifecycle checks, and user-reported second-machine portable startup,
graph/navigation and controlled shutdown checks. Installer/uninstaller behavior,
Unicode paths, robust double-click UX and full feature coverage remain pending.
