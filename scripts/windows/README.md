# Windows 便携版打包与试用教程

适用：Windows 10/11 x64。目前产物是解压后运行的便携版，不是安装程序；基本运行已在两台 Windows 电脑验证，全部功能尚未验收。

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

普通功能修改后重新构建即可；前端改变先 build，新增依赖/资源/服务要相应修改打包清单和入口。数据结构改变时需另考虑迁移，不用新包直接覆盖旧用户数据。建议提交代码后再构建，便于对应版本。

`.cache`、`dist`、运行库及用户数据不上传 Git。源码运行入口 `launch.py` 仍供已经配置好本机开发环境的人使用；上述便携包构建不要求先走这条旧入口。
