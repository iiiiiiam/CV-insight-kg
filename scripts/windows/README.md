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

已在开发者 Windows 上实测：统一启动、图谱及知识页跳转、正常停止、从新终端启动并再次正常停止；Neo4j 日志出现 `Stopped.`，五个目标端口释放。四个模拟测试通过。尚未完成第二台设备、完整数据一致性、全部功能或安装包验证。

## Implementation notes

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

Current verification: syntax, four mocked supervisor tests, and a user-operated
Windows start/stop/restart cycle with graph/navigation checks. Second-machine runtime, fresh data seeding,
password provisioning, packaging and installer/uninstaller behavior are later work.
