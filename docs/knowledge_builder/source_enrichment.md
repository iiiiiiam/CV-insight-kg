# 来源增强、原文命名规则与网页接入

后续一级研究子方向的独立抽样对比与推荐方案见 [研究子方向实验](research_directions_experiment.md)。该文是方案调查，不表示本页现有识别流程已经改用组合分类。

开发分支：`knowledge-enrich`，基于 `graph-front` 的 `d4a62ae`。先完成原 20 篇加 A 新增 80 篇的网页接入，再增加明确命名/数据集列举规则，在原 100 篇回归后追加未补采过的 50 篇。旧样本、53 词条、历史存档与 C 正式图谱保留原流程。

## 先看当前网页

在项目根目录，使用已有环境准备输入（首次需联网，已有缓存可加 `--offline`）：

```powershell
conda activate insight-prototype
python -m scripts.knowledge_builder.prepare_source_corpus --pool-limit 130
```

该命令只读 A 的远程跟踪分支 Git 文件，按稳定 ID 排序抽取 130 篇，和原 20 篇组成 150 篇；其中前 80 篇保留之前的名单，后 50 篇用于新论文验证。省略 pool-limit 时仍默认 100 篇；本机后续重跑请显式使用 130，避免无意缩回旧范围。它不写 A 的数据库。生成的数据和来源缓存位于被忽略的 data，只在整批校验通过后替换 corpus.json，不发布半份数据。

本机已在 `server/.env` 启用以下单项配置；其他机器需要准备数据后自行配置：

```dotenv
B_SOURCE_CORPUS=data/knowledge_builder/source_corpus/corpus.json
```

根目录终端运行 `python -m server.run`；另一个终端进入 `frontend` 后运行 `npm.cmd run dev`。打开 http://127.0.0.1:5173/research/knowledge ，下拉框显示准备好的论文总数（本轮 150 篇）；默认查看研究主题、知识条目、图和原文依据。常见词匹配、命名/列举规则的结果放在默认收起的“信息来源与识别说明”；同步范围放在“内容更新说明”，不常驻展示成员分工和内部接口。只体验这些不需要 Neo4j。服务已启动时需重启后台使代码/配置生效；前端开发服务会自动更新组件。

不启用这项配置时仍用旧 20 篇。启用但数据损坏/缺失会明确报错，不悄悄换成旧数据。页面读取和反馈处理仅使用本地来源记录，不在用户点击时联网。新增 130 篇未进入 A 原有论文列表或 C 正式图谱；原审核/confirmed 导出也不包含本轮来源增强及反馈变化。B→C 请使用新增的 [当前有效知识导出 v1](effective_export.md)，它已包含这些生效结果，C 仍需接入适配和发布。

## 当前识别顺序和维护位置

1. 作者、机构、会议等继续读取 A 的结构化字段。OpenAlex 主题分类单独显示，不能冒充原文中出现的词。
2. 来源明确标注的方法、任务、数据集，仍须在当前标题/摘要中定位，才能建立“提及”关系。目录中的所有方法不一定真是方法：FID/PSNR 等常见指标会排除。
3. 外部评测基准先匹配已知数据集规范项与别名；未知名称还必须在原文同一句的附近出现 dataset/data set/corpus 等明确提示，才作为数据集线索。仅列在 benchmark 字段中不够；不能据此断言论文实际使用或验证了它。
4. 来源缺失或标注不全时，用适量的通用 CV 词表匹配原文。新词表为 `src/knowledge_builder/vocabulary_cv.json`，含规范名、类别、别名及公开参考地址；不是逐篇手填结果。CLIP/ViT 的短别名要求相应大小写，减少普通英文词误判。
5. `text_signals.py` 识别“we introduce/present/propose ... named/called ...”等明确命名表达，以及“on A and B datasets”等明确列举。多词方法优先利用括号缩写，避免只截第一个词；明确称为 task 的名称按任务处理。原文规则只生成本篇线索，不写全局词表，也不要求人工逐项确认。

所有新增名称仍须命中原文，证据保留准确字符位置。网页明确说明“提到不等于采用”；否定句和对比对象仍可能被提取，当前没有完整的语义推断。泛词 Embedding 不再直接当方法，Inpainting 统一为任务。

目录接口实际为 `paperswithcode.co`，来源标识保留为 paperswithcode 以兼容缓存；它不是 `paperswithcode.com` 同域接口，不将其返回内容视为原作者或权威官方标注。只作为可追溯的辅助线索，原文规则和通用词表不依赖它在线。

`curated_vocabulary.py` 负责合并，已有规范项及用户反馈规则优先；不覆盖原 key 或冲突别名。`source_enrichment.py` 负责上述判断、原文定位和合并结果。第一周的 `vocabulary.json` 与参考来源文件不改，旧审核存档可以继续按旧版本读取。新词表只随增强阅读路径启用。

词表中的参考 URL 证明“这是什么名称”，标题/摘要的字符切片证明“这篇论文提到过它”，两者作用不同。网页的来源分类与知识列表也分开呈现。规则更新会改变公共版本，已有个人调整可能暂停应用；原浏览器记录仍保留，不自动清空反馈或伪造审核。

不能保证每篇都含主题、方法、任务、数据集各一项；正文才有的内容仍可能漏掉。当前没有读取 PDF 正文、调用大模型或对所有结果进行人工准确率评估。

## 最初的小样本对照命令

在仓库根目录，沿用已有环境：

```powershell
conda activate insight-prototype
python -m scripts.knowledge_builder.experiment_sources --pool-limit 100 --sources-per-group 10
```

脚本读取原有 20 篇，并只读 `origin/data-pipeline` 中带校验清单的 CVPR 大池；不切到 A 分支，不向数据库导入，不将大 JSONL 加入本分支。新增池先排除原有 20 篇及本实验不接受的记录类型，再按论文 ID 的 SHA256 排序取 N 条，避免按识别效果挑选。

分别对两组前 10 篇尝试 OpenAlex 补字段和 Papers with Code 目录匹配。这是联网读取，会缓存公开返回内容；不需要安装新依赖或部署 Neo4j，不调用自己的大模型。

结果位于 `data/knowledge_builder/source_experiment/latest/summary.json`；各篇详情在相邻 `papers/` 中。缓存位于 `data/knowledge_builder/source_cache/`，都沿用 data 的 Git 忽略规则。命令会重新写试验输出，不写真实业务存档。

已缓存时离线复现：

```powershell
python -m scripts.knowledge_builder.experiment_sources --pool-limit 100 --sources-per-group 10 --offline
```

只把现有规则对照扩展到整个 A 大池，仍仅复用已查询的小样本来源：

```powershell
python -m scripts.knowledge_builder.experiment_sources --pool-limit 2724 --sources-per-group 10 --offline --output data/knowledge_builder/source_experiment/full-pool
```

注意：这不等于对 2724 条逐一联网补全。`--sources-per-group` 控制每组实际试源数量，上限 50；缺少缓存时 offline 会记为来源未取得，绝不悄悄联网。`--refresh` 用于明确重新请求已有缓存，不能和 offline 同时使用。`--skip-pwc` 可以单独看 OpenAlex 路线。

## A 的唯一现有文件改动

`scripts/fetch_openalex_batch.py` 新增可选开关：

```powershell
# 示例用途：写到一个新位置；本次试验没有执行整批重新下载。
python -m scripts.fetch_openalex_batch CVPR 2024 data/source_trials/cvpr_2024_enriched.jsonl --with-annotations
```

开启后在原 9 字段之外请求 `primary_topic,topics,keywords`，并在新清单记录请求字段；不开启时字段选择和原调用保持不变。不会修改已下载的冻结样本、校验值、A 数据库结构或导入逻辑。按已有 OpenAlex 配置使用 `OPENALEX_API_KEY`（若有），不新增强制凭据要求；是否可匿名访问以实际接口为准。

试验脚本对已有 ID 做单篇补采，是为了先验证流程，避免重新下载全批。稳定后可以消费 A 带字段的新批次，而不是长期维护两套重复采集流程。

## B 怎样使用来源，同时保留现有框架

- 不改 `PaperInput`、旧抽取器或八类实体/七类关系。新模块在试验入口调用现有抽取与校验。
- 来源提供的主题保存在 `source_classifications`：有来源 URL、ID、分数和字段路径。名称没出现在标题/摘要里时不生成旧的字面“提及”关系。
- 关键词本身无类型：先匹配已知规范项，少量任务后缀规则可补任务。未知关键词保留原因，不随意当作方法/数据集。
- 目录的任务、方法、具名摘要实体只有在冻结标题/摘要中能重新定位时，才进入本篇的临时词表与旧抽取流程。不直接信任外部摘要的字符位置。
- 新结果保留旧结果及其依据，避免更长的新别名反而吞掉已有条目。已有名称尽量复用原 key，不通过规范名相似就盲目合并。
- 外部论文匹配须规范化标题精确一致、至少一个完整作者名一致，且发表年份差不超过 2 年，以容纳预印本和会议年份差。条件不满足或有多个匹配就跳过，不按搜索第一条猜测身份。这仍属于试验匹配策略，不等同于 DOI 身份证明。

每篇试验文件包括基础结果、增强结果、自动新增对象、临时词表、来源依据及未采用原因。该对照命令本身不更新网页；网页接入使用前面的 prepare_source_corpus 和 B_SOURCE_CORPUS。两种输出都不是旧 `confirmed.json`，不能直接交给 C 导入。

## 验证命令

```powershell
python -m unittest tests.knowledge_builder.test_source_enrichment -v
python -m unittest tests.test_ingest -q
python -m unittest discover -s tests/knowledge_builder -q
```

单元测试只用本地构造数据和模拟请求，不访问外网，不给真实论文手填提取答案；联网试验的原始结果和统计单独保存在 data。

首轮历史结果见本机 `reports/week_two/006_来源增强试验第一阶段.md`，100 篇网页体验与词表维护见 007，新增原文规则及 50 篇验证见 `008_原文补漏规则与新增50篇验证.md`。这些报告和 data 沿用忽略规则，不随 Git 自动共享。团队接入需要代码及可复现的数据准备步骤；C 的新协议仍需另行联调。
