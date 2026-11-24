# 真实数据排查与 C 图谱可读性改进

## 结论与生效前提

150 篇原始 effective 文件和本机 8002 图谱 API 的关系数量一致。主题、方法并未丢失，Yi Liu 也有真实署名关系。运行中的统计 API 却返回 basis.relations=confirmed_only、主题/方法零覆盖、指定 Yi Liu 画像零篇；它与当前 C 目录已支持 effective 的查询代码不一致。证据支持“当前服务仍运行旧查询实现”，不能据此认定 B 未提取或 Neo4j 丢了边；仅凭 HTTP 不能进一步区分旧进程未重启还是从另一个目录启动。

本轮未强行停止用户的 8002 进程，也未读取数据库密码。需要在原先持有 Neo4j 环境变量的终端停止旧 C 服务，进入本次修改目录并重新启动。**不需要重新导入、重新发布或清空数据。**

```powershell
cd C:\Users\YXT\Documents\Codex\2026-10-31\c-github-https-github-com-iiiiiiam-10\work\CV-insight-kg
.\.venv\Scripts\python.exe -m uvicorn src.graph_query.api:app --host 127.0.0.1 --port 8002
```

保留该终端已有的 NEO4J_URI/USER/PASSWORD/DATABASE，不覆盖其值。访问 `/api/health`，新版应有 `implementation_revision=c-effective-graph-v2`。若无此字段，仍不是本次代码。页面新增对 effective 批次返回 confirmed_only 的明确警告，避免把旧服务返回的零当作源数据事实。

## 原始文件与实际已发布图的核对

批次：`effective-6c97a76de785646616f2e13845a3c93fdc2ba26d280d56ea14b00e20013b9629`。

Docker 管道在当前执行环境仍拒绝访问；本轮通过现有公共图谱 API 枚举全部 150 篇论文的一跳边，再逐作者枚举 affiliated_with，按真实边 ID 去重。所有请求均为 GET，没有截断；得到全部 2185 条实际图边，不是用原文件推算数据库数。

| 关系 | B 文件 | 本机已发布图 |
| --- | ---: | ---: |
| has_author | 789 | 789 |
| affiliated_with | 792 | 792 |
| published_in | 150 | 150 |
| mentions_topic | 17 | 17 |
| mentions_method | 238 | 238 |
| mentions_task | 124 | 124 |
| mentions_dataset | 75 | 75 |

原始与图中年份均为 2024：150 篇。正确查询口径下，主题覆盖 17 篇，方法覆盖 115 篇；238 是方法关系数，不是论文数。统计回归按去重论文数验证，不拿关系总数冒充覆盖论文数。

指定作者 `author:https://openalex.org/A5100701079` 有一条 has_author，来自 `paper:https://openalex.org/W4402754006`（DETRs Beat YOLOs on Real-time Object Detection）。原文件和实际图 API 均能查到。新版画像测试验证 total=1，page_size=1 的第一页返回此论文，第二页为空，未按名称合并。

另一个同名 ID `author:https://openalex.org/A5115883506` 关联 `paper:https://openalex.org/W4402623740`。两个来源 ID 不能凭同名合并，也不能仅凭 ID 不同断定一定是不同自然人；本项目按来源身份展示，保留追溯线索。

本轮增加 `/api/research/diagnostics?batch_id=...`，在同一只读事务内按真实 kind/status 聚合关系数量。重启后可用它复核正式批次。当前旧进程还没有该新路由。

## C 共享图谱组件

新增 `src/graph_query/graph-view.js`，两个 C 独立页统一使用 `mountGraph(root,{seed,batch,load,onSelect})`。不依赖 D 或第三方 CDN，不推断引用关系、论文相似度或学术距离。

- 默认可视图谱与 1 跳，选择 2 跳后明确点击“加载 / 展开”；每次请求 limit=60（路径单位），画布另外限制最多 60 节点。
- 力导向布局使用节点排斥、边弹簧与居中力，替换固定圆环；种子优先保留，关键高连接节点优先展示。布局是显示辅助，不代表论文语义相似度。
- 默认只标注种子、选中节点及少量关键节点；悬停显示完整名称并突出关联边；选中节点后显示完整名称、真实关系类型、状态和详情。
- 论文、作者、机构、主题、方法、任务、数据集、会议分别着色并有图例；复选框筛选类型。
- 图谱/列表切换、拖动节点、拖动画布、滚轮及按钮缩放、适应画布、重新布局、点击/键盘选择和详情下钻。
- 边有方向，显示真实 kind；不伪造 citation/similarity。截断分别说明“服务端路径上限”和“画布节点上限”；单节点无边和筛选后无节点有提示。

D 未来可直接复用该模块：`load` 返回现有 C graph 响应，`onSelect(id,batch)` 接统一详情区域。组件只负责显示；批次与鉴权仍由 D 网关处理。销毁调用返回值的 destroy()。节点 kind/type、id/name，边 source/target/kind/type/status/review_state，均沿用 C 返回值。

## 验证记录与边界

- 当前 Docker 已发布批次：通过 8002 真实图谱 API 完成全部 2185 条边、150 篇年份、指定 Yi Liu 署名核对，见 live-audit-before.json。该服务统计仍旧，尚未替用户重启。
- 新代码：在独立 Neo4j Harness 5.26.0 中加载完全相同的 150 篇 revision，46 项 Python 测试通过，耗时 97.45 秒；其中 10 项真实 Neo4j。新增了主题/方法覆盖、七类边计数、Yi Liu 论文及分页的明确断言。保留旧 confirmed、幂等、撤回等测试。
- 图谱：Node 执行 7 项布局/筛选/上限/空图检查通过，三份图谱相关模块通过 JavaScript 语法检查；CI 加入组件检查。
- 浏览器：尝试连接验收标签并打开隔离预览，但控制浏览器无法访问该执行环境中的 18002 监听端口，连接超时；因此**浏览器人工点击验收未通过/未完成**，没有伪造截图。临时预览已停止。不能把布局数据测试当成真实拖动、缩放或视觉可读性验收。
- 没有 Git 操作，没有 B/D 源码修改，没有删除或重置 Docker 数据、切换现有发布指针。

## 重启后的人工验收步骤

1. 检查 health 实现标识；打开 `/research/analytics`，填写上述已发布批次并读取统计：150 篇、2024 年、主题覆盖17篇、方法覆盖115篇；分组按论文去重。
2. 搜索 Yi Liu，选择 A5100701079：应显示 1 篇，点论文标题进入真实详情；两个同名 ID 保持分开。
3. 点“关联图谱”，默认应直接显示可视图和 1 跳，而不是文字列表。选择 2 跳并加载，检查截断提示；点“列表视图”应显示同一筛选范围的节点。
4. 悬停完整名称与关联边、选中节点详情；拖动节点和背景、缩放、适应画布、重新布局；逐一关闭类型图例，确认边端点一起过滤。全部关闭时应有空图提示。
5. 从 `/research` 任一论文进入图谱，确认使用同样组件。选会议或机构节点展开 2 跳，检查高节点量时最多60节点且明确截断，标签不会全部铺满。
6. 无关系的真实节点或由筛选产生的无关联范围，显示孤立节点提示，不生成连线。筛选无论文时仍保留原空列表提示。
7. 确认自动关系仍为 automatic/effective，原始证据、作者 ID 和批次均未改变。

## B 侧反馈

本次零统计与零画像不需要 B 补造关系：17/238/署名边都已存在。请保留 source_classifications 与 mentions_topic 的区分，当前原文主题覆盖较少是样本提及口径，来源分类可以另行展示而不能填进此统计。150 篇同为2024是当前来源范围；若课程需要跨年趋势，应由 A/B 扩展真实年份范围，不在 C 合成数据。Yi Liu 的两个来源身份如需合并，应由 B 根据来源和证据审核决定，C 不凭姓名判断。

## 本轮文件

新增 graph-view.js、graph-view.test.mjs、preview_effective_isolated.py、本说明和三份审计/验收 JSON。修改 C detail.html、analytics.html、api.py、test_effective.py 和 C 专用 CI；没有修改 D 的统一导航和页面。
