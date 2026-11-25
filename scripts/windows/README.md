# Windows 便携版打包与试用教程

适用：Windows 10/11 x64。支持便携版和安装版候选构建；便携版基本运行已在两台 Windows 电脑验证，安装版及小控制窗口已在开发机验证基本流程，全部功能尚未验收。

只想试用现成包，直接看第五节。想在自己电脑构建，从第一节开始。所有命令使用 PowerShell，报错时先停下，不继续执行后续步骤。

## 一、准备文件和环境

在包含这些脚本的代码分支上操作（当前为 `deploy/windows-installer`）。构建电脑需要：

- Python **3.11 x64**，不要直接用 3.13；已验证构建版本为 3.11.18。
- Node.js **22.18.0 或以上**及 npm，用于构建前端。
- Java **21 x64 ZIP** 和 Neo4j Community **5.26.33 Windows ZIP** 原始压缩包；不需要在系统安装 Java 或启动 Neo4j。
- 网络和足够磁盘空间，用于安装构建依赖和生成运行包。

建议把仓库放在纯英文、无空格目录。将两个原始 ZIP 放到项目 `.cache/windows-runtime/`，不用解压。示例使用已经验证的文件名；若下载文件名或位置不同，修改第四节参数。

不需要复制其他人的 `server/.env`、数据库或账号。脚本会将运行环境和公开样本装入包，首次运行再生成本机配置。

## 二、创建独立打包环境

先进入自己的仓库根目录，再修改 Python 路径：

```powershell
Set-Location 'D:\Projects\Research-Insight-Team'
$python311 = 'C:\Python311\python.exe'  # 改为自己的 Python 3.11 路径
& $python311 --version
```

确认输出为 3.11.x，再执行：

```powershell
$buildPython = Join-Path (Get-Location) '.cache\windows-build-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $python311 -m venv '.cache\windows-build-env'
    if ($LASTEXITCODE -ne 0) { throw '创建打包环境失败' }
}
& $buildPython -m pip install -r scripts/windows/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw '安装打包依赖失败' }
```

这只给独立环境安装依赖，不修改系统 Python。已经建好环境时可以复用；新终端需要重新设置 `$buildPython`。

## 三、构建网页

在仓库根目录执行：

```powershell
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
```

已有匹配依赖时可跳过 `npm ci`；前端源码更新后仍需重新 build。成功应出现 `built in ...`，生成 `frontend/dist`。

## 四、生成便携包

仍在仓库根目录执行（ZIP 路径按自己的文件调整）：

```powershell
$buildPython = Join-Path (Get-Location) '.cache\windows-build-env\Scripts\python.exe'
& $buildPython scripts/windows/build_portable.py --java-zip '.cache\windows-runtime\OpenJDK21U-jdk_x64_windows_hotspot_21.0.13.1_2.zip' --neo4j-zip '.cache\windows-runtime\neo4j-community-5.26.33-windows.zip'
if ($LASTEXITCODE -ne 0) { throw '便携版构建失败' }
```

成功标志是 `Candidate ready ...`。输出目录：

```text
dist/windows/时间戳/ResearchInsight/
```

构建不会启动服务，也不复制开发者的 `.env`、用户账号、反馈或已有数据库。目录内附构建版本、实际 Python 依赖及运行库哈希记录；有未提交修改时构建清单会注明。

## 五、复制、启动和停止

1. 保留原始输出目录不运行，另复制一份测试。分发时压缩整个未运行的 `ResearchInsight` 文件夹，不能只发 exe。
2. 在目标 Windows x64 电脑完整解压到**纯英文、无空格、可写目录**，例如 `D:\RI-test\ResearchInsight`。不放 Program Files；当前中文路径兼容未完成。
3. 双击 `ResearchInsight.exe`。目标电脑不用另装 Python、Java、Neo4j 或 Node。
4. 首次运行会生成独立凭据、初始化示例数据库，通常比后续启动慢。看到 `Ready` 后浏览器自动打开，地址为 `http://127.0.0.1:8001`。
5. **保留控制窗口。** 重复双击会提示已有实例，按回车关闭第二个提示窗口即可。
6. 用完在原控制窗口按一次 **Ctrl+C**，等四项服务停止后再关闭窗口。再次使用仍运行同一个 exe，不重新解压。

管理员登录信息保存在 `user-data/管理员登录信息.txt`。运行数据在 `user-data/` 和 `runtime/neo4j/data/`，请保留；已运行过的目录含本机凭据及数据，不再直接发给别人。

需要排错时，从 PowerShell 启动（替换实际路径）：

```powershell
& 'D:\RI-test\ResearchInsight\ResearchInsight.exe'
```

## 六、最简单的验证与排错

按顺序确认：自动打开网页 → 显示图谱 → 打开论文知识与证据 → 重复启动被拦截 → Ctrl+C 正常停止 → 再次启动数据仍在。

当前初始 B 图谱为 **20 篇论文**，基线可见 10 个共享实体、54 条总览连接；A 初始化另包含 60 篇补充样本。此包不复制开发机的 150 篇增强语料，也不含独立安装间的云反馈同步。

- `PYZ-00.toc is non existent`：首次创建打包中间文件的正常提示。
- `Warnings written to ...`：警告文件可能包含其他平台或可选依赖，不代表都需要安装；最终以实际运行和需要的功能为准。
- 端口占用：先正常停止已有项目实例，不重复启动，不批量结束电脑上所有 Java/Python。
- 启动失败：窗口会等待回车，先看报错。主日志在 `user-data/logs/launcher-*.log`，服务日志在对应时间戳子目录；初始化日志为 `user-data/neo4j-setup.log`。分享日志前检查内容，不发送凭据文件。

停止后可检查五个目标端口（无输出表示无监听）：

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(7474,7687,8000,8001,8002) } | Select-Object LocalPort,OwningProcess
```

目前已验证两台 Windows 的基础访问、双击、重复启动提示和正常停止；不等于所有功能通过。**直接关闭或强杀控制窗口后的完整清理尚未保证**，请使用 Ctrl+C。

## 七、代码更新后如何复用

安装版准备的新参数与验证方法见下方第八节。

普通功能修改后重新构建即可；前端改变先 build，新增依赖/资源/服务要相应修改打包清单和入口。数据结构改变时需另考虑迁移，不用新包直接覆盖旧用户数据。建议提交代码后再构建，便于对应版本。

`.cache`、`dist`、运行库及用户数据不上传 Git。源码运行入口 `launch.py` 仍供已经配置好本机开发环境的人使用；上述便携包构建不要求先走这条旧入口。

## 八、安装版准备：独立数据目录（待实机验证）

新构建的 exe 增加可选参数 `--data-dir`，供后续安装快捷方式使用。省略参数仍是原来的便携模式。

```powershell
& 'D:\RI-install-test\ResearchInsight\ResearchInsight.exe' --data-dir 'D:\RI-install-data'
```

请用新构建的干净程序副本和新的空数据目录测试，两个路径暂时都使用纯英文、无空格路径。首次启动后，独立目录包含凭据、管理员登录信息、`application/`、`logs/` 和 `neo4j/`（配置、数据库和日志）。每次重启必须传入同一目录；省略参数不会自动找到它。

验证顺序：首次启动及知识页 → Ctrl+C 停止及端口检查 → 用同一命令重启 → 检查需保留的数据。旧便携数据不自动迁移；安装器及小控制窗口见第九节，管理员登录及反馈验收仍待安排。

实现依据：[Neo4j 官方文件位置说明](https://neo4j.com/docs/operations-manual/current/configuration/file-locations/)，使用 `NEO4J_CONF` 及目录设置。外部配置首次生成后保留，升级 Neo4j 时另行检查兼容性。

## 九、构建安装版（候选，尚待编译与实机验证）

在打包电脑安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)。目标用户电脑不需要安装它。构建环境及 Java/Neo4j ZIP 沿用前文，首次仍需安装前端依赖。

以后普通源码更新，可在项目根目录重复执行同一条命令（修改 ISCC 的实际位置）：

```powershell
& '.cache\windows-build-env\Scripts\python.exe' scripts/windows/build_release.py --java-zip '.cache\windows-runtime\OpenJDK21U-jdk_x64_windows_hotspot_21.0.13.1_2.zip' --neo4j-zip '.cache\windows-runtime\neo4j-community-5.26.33-windows.zip' --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

脚本依次构建前端、干净便携候选、安装包，失败即停止，不启动服务。安装包输出到 `dist/windows-installers/时间戳/`，便携输出仍在 `dist/windows/时间戳/`。目前 095900 及更早包不含停止入口，不能拿来制作此安装包，需重新构建。

也可单独封装支持停止入口的干净候选：

```powershell
& '.cache\windows-build-env\Scripts\python.exe' scripts/windows/build_installer.py --portable-dir 'dist\windows\替换时间戳\ResearchInsight' --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

安装向导按当前用户安装，可选择程序目录、独立数据目录；两者不能互相包含，暂限本地盘纯英文、无空格路径。标准向导暂用英文，数据页及入口说明为中文。

最新构建的安装快捷方式打开小控制窗口，显示启动中、运行中、正在退出等状态，提供“打开页面”“查看日志”“退出软件”。点“退出软件”或右上角 × 后，等待后台服务停止，窗口自动关闭；网页前端无改动。开始菜单“停止 Research Insight”保留作备用。此前 103221 安装包仍是终端入口。114531 新安装包在开发机覆盖安装后，已验证页面访问、按钮退出、重启、右上角 ×、启动过程中退出及端口释放；重复启动交互、异常提示和第二台 GUI 安装版仍待实测。

卸载前正常退出，卸载保留数据，不提供自动彻底清除。关闭浏览器标签页不会停止软件；强制结束控制窗口进程后的清理仍未保证。原始 `ResearchInsight.exe` 保留作为命令行诊断入口，安装用户请使用快捷方式，避免遗漏数据目录参数。

安装测试需覆盖：首次安装及启动 → 停止入口及端口释放 → 重启 → 卸载保留数据 → 重装时选回同一数据目录。升级前停止并备份数据，数据库或依赖升级仍须单独评估迁移。新 Python 依赖、资源文件或服务加入时，维护依赖与打包清单后再用同一流程；不能保证任意代码更新都无需适配。

小控制窗口使用 Python 自带的 Tk，打包电脑的 Python 需包含可用的 tkinter/Tcl/Tk；打包后用户无须另装。构建时会额外生成 `ResearchInsightControl/` 子目录，请完整保留。命令行入口与控制窗口分开打包，以保留现有服务的停止机制。
