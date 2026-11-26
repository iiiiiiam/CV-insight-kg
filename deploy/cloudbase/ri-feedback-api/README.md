# CloudBase 反馈接口与手动交付工具

截至 2026-11-26，已用一条真实反馈验证：提交 → 团队处理并回复 → 提交者查询到回复。当前为封闭试接。2026-11-27 新增独立 Windows 手动工具：本地加密草稿、原请求重试、手动查回复、团队查看和回复。尚未接入主软件界面或安装包。

## 2026-11-27 交付入口

使用方式见 [手动工具说明](CLIENT.md)。这是可独立运行的控制台工具，无需安装依赖；不会启动主软件、后台同步或轮询。

```powershell
python deploy/cloudbase/ri-feedback-api/client.py --data-dir .cache/cloudbase/my-feedback
```

生成两个可交付 ZIP（仅本地操作）：

```powershell
python deploy/cloudbase/ri-feedback-api/build.py
```

默认输出 `.cache/cloudbase/delivery/ri-feedback-api-upload.zip` 与 `ri-feedback-client.zip`，分别是云端运行包和独立手动工具包。固定文件白名单，排除本地存档及凭证。云端代码本次未变化，现有环境无需重新部署或重新建表。

新环境可使用 [schema.sql](schema.sql) 在一个事务中建表并配置权限；现有环境不要重复执行。脚本根据已验证结构整理，本次未在第二个真实环境复建验证。

客户端离线功能检查 4 项通过；用户在正常 Windows PowerShell 运行 `--windows-protection` 后，5 项全部通过，已确认真实 DPAPI 加解密。复用云函数 14 项离线检查通过。开发阶段未调用云端；随后用户用工具完成一次最小真实验证：本地草稿退出重开仍存在，发送反馈、团队查询并回复、提交者查到 `resolved / state_revision=1` 和中文回复，共 4 次云函数请求、1 条新记录。此为简单功能验证，不是第二轮独立测试。

## 本阶段结果

- 本地 14 项离线测试通过，数据库请求全部模拟，不消耗云端额度。
- 云端使用 Node.js 20.19；本地测试使用 Node.js 24.15.0，不能替代云端验证。
- 实际完成一次健康检查、一次提交、一次团队更新、一次提交者查询，共 4 次云函数请求；数据库新增 1 条记录。
- 真实记录从 `open / state_revision=0` 更新为 `resolved / state_revision=1`，提交者查到了团队填写的 `processing_note`。
- 未测试压力、自动重试、完整同步；没有后台轮询。

## 服务与费用边界

本次使用腾讯云 CloudBase 上海区 PostgreSQL 体验环境，控制台显示免费试用 6 个月、到期日 2027-05-26，资源点 3000，自动续费未开启。免费有期限和用量限制，不等于永久免费；实际剩余额度以控制台为准。后续优先离线测试，云端只做必要的少量人工验证。

环境 ID 和网关域名是地址标识，不是密钥。API Key、试用访问凭证、团队处理凭证和每条反馈的查询凭证均不得提交到 Git、写入教程示例值或截图分享。

## 1. 本地开发和打包

本目录无第三方依赖，无需 `npm install`。在仓库根目录执行：

```powershell
node --test deploy/cloudbase/ri-feedback-api/index.test.js
```

上传 ZIP 的根目录只能放以下运行文件，不能多套一层目录：

```text
index.js
package.json
scf_bootstrap
```

`scf_bootstrap` 使用 LF 换行和 Linux 可执行权限，内容为 `exec node index.js`。测试文件、文档和任何环境变量文件不放入运行包。当前检查点的上传包在仓库忽略目录 `.cache/cloudbase/ri-feedback-api-upload.zip`，不是版本化交付物。

## 2. 控制台部署

1. 创建 HTTP 云函数，命名 `ri-feedback-api`，运行环境 Node.js 20.19，监听端口 9000，内存 256 MB，执行超时 3 秒。
2. 「函数代码 → 上传代码」选择 ZIP，选择「部署且不安装依赖」，确认部署。
3. 刷新页面，确认 `index.js` 包含 `createHandler`。如在线编辑器仍显示旧 Hello World 且提示未部署改动，不要直接部署旧编辑器内容。
4. HTTP 网关配置 `/feedback` → 云函数 `ri-feedback-api`，版本 `$DEFAULT`；关闭路径透传。因此 `/feedback/requests` 在函数内收到 `/requests`。

本次试接的网关身份认证关闭，由代码验证试用、管理和单条反馈凭证。此设置不代表可以公开分发管理凭证或将此接口直接作为正式生产服务。

## 3. 数据库前置条件

已创建 `public.ri_feedback_requests`，主要字段如下。完整复建脚本见 schema.sql；脚本尚待新环境验证，当前试接环境无需执行。

| 字段 | 用途 |
| --- | --- |
| `id` | 云端反馈 UUID |
| `installation_id, local_feedback_id` | 唯一组合，防止重复提交 |
| `receipt_token_hash` | 查询凭证的 SHA-256 摘要，不保存原始凭证 |
| `payload` | 反馈 JSON 对象 |
| `status, processing_note` | 处理状态和团队回复 |
| `state_revision` | 更新版本，拒绝过期更新 |
| `created_at, updated_at` | 创建和更新时间 |

已开启 RLS；撤销 PUBLIC、anon、authenticated 的表权限，仅授予 service_role SELECT、INSERT、UPDATE。服务端 API Key 使用高权限访问，必须留在云端。控制台 SQL 预检查曾提示角色兼容问题；本次实际查询确认 anon、authenticated、service_role 存在后才继续执行，不应在其他环境无条件忽略警告。

## 4. 配置凭证

「函数配置 → 编辑」保留服务端 API Key 注入，并添加：

| 变量 | 内容 |
| --- | --- |
| `CLOUDBASE_APIKEY` | 控制台服务端 API Key，经 API Key 设置注入 |
| `CLOUDBASE_ENV_ID` | 对应环境 ID |
| `RI_FEEDBACK_PILOT_TOKEN` | 64 位小写十六进制随机字符串，用于封闭试接 |
| `RI_FEEDBACK_ADMIN_TOKEN` | 另一个独立随机字符串，用于团队处理 |

后两项可在本机生成，不消耗云端额度：

```powershell
python -c "import secrets; print('RI_FEEDBACK_PILOT_TOKEN=' + secrets.token_hex(32)); print('RI_FEEDBACK_ADMIN_TOKEN=' + secrets.token_hex(32))"
```

将生成值分别粘贴到控制台并自行妥善保存，不能复用 API Key。保存配置后访问 `/feedback/health`，应看到三个 `configured` 都为 `true`。这只检查配置存在，不连接数据库。

## 5. 最少请求验证完整流程

以下命令在同一个 PowerShell 窗口依次运行。只替换网关地址；`Read-Host` 引号内是提示文字，不要把密钥写进命令。等待提示出现后再粘贴凭证，输入不会显示。整个过程不写本地文件。

```powershell
$riBase = "https://你的网关域名/feedback"
$riPilot = Read-Host "请输入试用凭证" -AsSecureString
$riReceipt = python -c "import secrets; print(secrets.token_hex(32))"
$riBody = @{
    installation_id = [guid]::NewGuid().ToString()
    local_feedback_id = [guid]::NewGuid().ToString()
    receipt_token = $riReceipt
    payload = @{ message = "Cloud feedback connection test" }
} | ConvertTo-Json -Depth 3 -Compress
$riHeaders = @{
    "x-ri-pilot-token" = [System.Net.NetworkCredential]::new("", $riPilot).Password
}
$riResult = Invoke-RestMethod -Method Post -Uri "$riBase/requests" `
    -Headers $riHeaders -ContentType "application/json" -Body $riBody -TimeoutSec 20
$riResult | ConvertTo-Json -Depth 4
```

应返回 `open`、版本 0、`duplicate: false`。不要反复运行整段：它会生成新编号并新增记录。原请求如需重试，应保留原编号、内容和查询凭证。

团队处理同一条记录：

```powershell
$riAdmin = Read-Host "请输入团队处理凭证" -AsSecureString
$riAdminHeaders = @{
    Authorization = "Bearer " + [System.Net.NetworkCredential]::new("", $riAdmin).Password
}
$riUpdateBody = @{
    status = "resolved"
    processing_note = "Reviewed: cloud feedback and reply test completed."
    expected_revision = 0
} | ConvertTo-Json -Compress
$riUpdated = Invoke-RestMethod -Method Patch `
    -Uri "$riBase/admin/requests/$($riResult.feedback.id)" `
    -Headers $riAdminHeaders -ContentType "application/json" -Body $riUpdateBody -TimeoutSec 20
$riUpdated | ConvertTo-Json -Depth 4
```

应返回 `resolved` 和版本 1。不要重复提交版本 0 的更新，过期版本会返回冲突。

提交者查询回复：

```powershell
$riOwnerHeaders = @{
    "x-ri-pilot-token" = [System.Net.NetworkCredential]::new("", $riPilot).Password
    Authorization = "Bearer $riReceipt"
}
$riReply = Invoke-RestMethod -Method Get `
    -Uri "$riBase/requests/$($riResult.feedback.id)" -Headers $riOwnerHeaders -TimeoutSec 20
$riReply | ConvertTo-Json -Depth 4
```

应看到相同的 `resolved`、版本 1 和团队回复。输出没有原始凭证；不要输出 Headers、`$riBody` 或凭证变量。测试窗口关闭后这些变量不再可用；本阶段尚无持久化客户端保存查询凭证。

## 接口和后续工作

| 接口 | 凭证与行为 |
| --- | --- |
| `GET /health` | 无凭证，只检查配置，不查询数据库 |
| `POST /requests` | 试用凭证；提交内容带单条查询凭证，服务端只存摘要 |
| `GET /requests/:id` | 试用凭证 + Bearer 单条查询凭证，只返回该条处理结果 |
| `GET /admin/requests` | Bearer 团队凭证，最多列出最近 20 条 |
| `PATCH /admin/requests/:id` | Bearer 团队凭证 + expected_revision，更新状态和回复 |

请求体限制 4096 字节，反馈 payload 限制 2048 字节。不接受 URL 查询参数，不将原始数据库错误返回给客户端。团队更新只保存最新回复，没有完整历史。健康检查不证明数据库可访问。

独立手动工具已提供持久化安装编号、原请求和查询凭证、手动重试及团队入口，并补齐迁移脚本和可重复打包。下一阶段才接入主软件的反馈提交与手动查询；本地加密及手动工具真实链路已验证，新环境迁移仍待复建验证。正式分发前仍需完善独立用户认证、限流和滥用控制。不得把服务端 API Key 或团队凭证放进安装包。完整同步和自动修改本地知识图谱不属于本检查点。

本次代码位于独立目录，尚未同步到 data-pipeline、graph-front 等分支；后续集成需先核对这些分支的最新接口。
