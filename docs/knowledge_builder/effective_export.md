# B → C 当前有效知识导出 v1

### B 页面展示补充

后续试用已在 B 的单篇关联图中投影子方向：前端专用 ResearchDirection 显示类型、棕橙色六边形、连线“属于研究方向”，点击只读查看分类依据；其他不入图。显示节点不进入后端 entities/relations，不改变本协议实体类别、关系种类和计数，C 不需要因为本次前端投影新增图节点。下段描述的“未在单篇图展示”属于前一阶段，正式图谱契约未升级这一边界仍保持。

后续已在 B 的 `KnowledgeEvidence.vue` 增加独立“研究子方向”区域：显示 1—3 个方向，其他显示暂未归类说明；可展开查看归类依据及“当前论文 → 属于研究方向 → 方向名称”的含义。原有“研究主题”只展示 kind=topic，不再混入子方向。仅修改 B 证据组件及其 TypeScript 数据类型，44 项前端测试和构建通过；未进行浏览器视觉验收。

概念上可将“研究子方向”视为实体，论文与其关系建议称“属于研究方向”（分类关联），而非把关系命名为“方向”。**本轮只实现 B 的结构化分类与页面展示，不把该概念塞进现有八类实体/七类关系，也不在单篇图中伪造节点或连线。** 如果团队决定新增正式 Direction 实体和关系，仍需共同升级图模型、导入和查询契约；不是只改 B 一个枚举即可完成。

## 当前子方向规则：组合识别、默认一个（2026-11-13）

下方 tasks-only 段落为第一步试验记录，现已由 `cv-combined-directions/2` 替代。具体实现仍在 B 的 `research_directions.py`，不修改 A、C 或前端。

当前从标题中的明确任务表达，以及 OpenAlex 关键词、首选主题、目录 tasks 与冻结摘要中相互支持的线索归类。标题命中可以独立支持归类；否则需要“关键词＋任务/主题/摘要”，或“任务＋摘要”“具体首选主题＋摘要”。摘要单独提及不足以分类；多次重复同一字段也不会增加权重。来源一致不等于独立验证，仍可能把背景内容当作研究方向。

默认只选择排名第一项。只有第一项和附加项都在标题中明确出现，附加项还有其他字段支持，且排名权重接近时，才允许增加第二、第三项，硬上限 3。排名使用固定规则权重，不是模型置信度，不输出伪装成概率的分数。不要求每篇一定只有一个，也不会把所有来源标签简单合并。

新增记录沿用 `kind=research_direction`、稳定 `source_id` 和 `parent_name`；`classification_method=combined_rules`，`mapping_version=cv-combined-directions/2`，`selection=primary` 或 `additional`。`primary` 只表示规则优先展示项，不表示已验证为论文的唯一主贡献。`source=b_rules` 表明这是 B 组合归类，`mapped_from` 的每个元素记录 channel（title/abstract/keyword/task/primary_topic）、原始文字 name、命中 quote 与字符位置、source_url、source_digest、source_path。标题和摘要的位置相对于对应输入字符串；关键词等的位置相对于其 name，不相对于摘要。

没有合适结果时只返回一条 `name=其他`、`source_id=cv-direction:other`、`selection=fallback`、`classification_method=unclassified_fallback`，原因是 `insufficient_supported_direction`，`mapped_from=[]`。这是“暂未得到足够分类依据”，不是来源提供了“其他”，也不能与具体方向同时返回。输入指纹只供追溯，不是假造的来源分类证据。此次不输出未选择的弱候选，不要求任何人工审核。

通用归类表适度补充了视觉语言、视觉模型效率、视觉安全等方向，避免强塞到检测或生成；仍允许确实不好归类的论文保留“其他”。当前 150 篇为 136 篇单方向、1 篇双方向、13 篇其他；开发实验 40 篇为 36 篇单方向、4 篇其他。这是规则分布而非准确率，也不是产品必须维持的比例或阈值。

阅读结果、完整有效导出共用本次选择；C 的离线读取与存档仍兼容，实体及关系数量不因此增加。已有整合服务启用自动同步时，新内容版本可能触发正常同步发布；本次离线验证没有启动服务、覆盖旧导出或写 Neo4j。B 前端现已独立显示子方向，历史 tasks-only 段落里的混合展示描述不再代表当前页面。

## 一级研究子方向：基于 tasks 的最小接入（2026-11-13）

产品约定：以“计算机视觉”为统一主方向，只整理一层子方向，如目标检测、图像分割、图像分类、三维视觉等；不照搬 OpenAlex 的多级学科体系。`subfield` 仍是来源所属学科，不等于产品的子方向。

已验证身份的论文目录记录中，`tasks` 经 B 的小规模显式归类规则整理为 `kind="research_direction"`，与原有 `kind="topic"` 一起放在现有 `source_classifications` 数组中。例如：

```json
{
  "kind": "research_direction",
  "name": "图像分割",
  "source_id": "cv-direction:image-segmentation",
  "parent_name": "计算机视觉",
  "basis": "source_classification",
  "classification_method": "task_mapping",
  "mapping_version": "cv-task-directions/1",
  "source": "paperswithcode",
  "mapped_from": [
    {"name": "Instance Segmentation", "source_path": ["tasks", 0]}
  ]
}
```

示例省略的 `source_url`、`source_digest`、`source_path` 在实际输出中保留；来源校验后才进行映射。`source_id` 是 B 的稳定分类键，不是 OpenAlex ID 或可点击的网页链接。消费端应按 `kind` 区分来源主题和产品子方向，展示标签可用 `name`；不要要求所有分类 ID 都是 URL。

同篇同方向的多个任务合并，原始任务名和位置保留在 `mapped_from`，一篇可以有多个方向。未配置的任务、泛泛的 Retrieval 或非视觉任务不强行归类；没有匹配时不编造“其他”或默认方向。本版先使用 tasks，暂未实现 OpenAlex 主题/关键词对产品子方向的兜底归类，也不新增人工审核步骤。

源目录任务可以支持来源分类，但不一定出现在冻结摘要中，所以这些记录不生成伪造的原文依据、不加入八类实体和七类关系，不影响其计数。现有 C 的离线读取器能够保留新分类记录；是否将其建成图节点、筛选条件或专门页面，由后续接入决定，本次没有修改 C。

前端代码未修改。现有 B 页面会遍历 `source_classifications` 的名称，因此会在原有“研究主题”区域同时显示这些中文子方向，但尚没有专门分组或子方向筛选；不能称为完成了独立子方向界面。正式图谱的实际展示和数据库发布本次未验证。

规则位于 `src/knowledge_builder/research_directions.py`；该文件纳入有效导出的规则指纹，规则调整会产生新内容版本。使用现有 `preview_topics` 脚本可以离线查看“计算机视觉 → 子方向 [来源 tasks]”，无须 Neo4j。

## 研究主题所属分类：兼容补充（2026-11-13）

B 在 `papers[].source_classifications[]` 的现有主题记录内，增加可选的 `hierarchy`，同样出现在 B 阅读结果的 `source_enrichment.source_classifications` 中。实体、关系、顶层结构及 `knowledge-effective/1.0` 不变。

```json
{
  "kind": "topic",
  "name": "具体研究主题（来源原名）",
  "hierarchy": {
    "subfield": {
      "source_id": "https://openalex.org/subfields/1707",
      "name": "Computer Vision and Pattern Recognition",
      "source_path": ["topics", 0, "subfield"]
    }
  }
}
```

上例为字段示意，实际数据仍保留原有 `source_id`、`source_url`、`source_digest`、`basis` 等字段。`hierarchy` 按来源实际提供的有效内容包含 `subfield`、`field`、`domain`；缺失时不编造，也不要求旧数据补齐。父分类只保存 `source_id`、`name` 和其在原始来源中的 `source_path`，沿用所属主题的来源地址和摘要指纹。

语义从宽到细是 `domain → field → subfield → topic`。**subfield 是主题的上一级，不是主题下面的新子方向**；本次支持“按所属分类理解研究主题”，没有新增第九类实体，也没有创建分类之间的正式图谱关系。这些是 OpenAlex 来源分类，不假装是摘要原句或人工确认结果。

C 当前读取器的离线校验、投影兼容测试已覆盖新增字段：可随论文分区存档保留，不增加图节点或边。是否展示分类层级、增加筛选或形成正式层级关系，由相关模块后续决定；B 本次不修改 C 或前端，不声称页面已经展示层级。新增分类内容会正常影响有效结果的内容版本，不能期待仍与旧文件版本相同。

本地查看：激活 `insight-prototype` 后，在项目根目录运行 `python -m scripts.knowledge_builder.preview_topics`。使用已有语料离线统计并打印“所属分类 → 研究主题”，不修改反馈、原始输入或旧导出文件，也不需要 Neo4j。

协议：`knowledge-effective/1.0`。中期实现最初位于 `knowledge-enrich`；本次分类补充位于基于 `graph-front-week2` 的 `knowledge-topics`。下方 2026-11-08 的附件数量、版本和当时待联调状态是历史记录；当前整合分支已有 C 的接入代码，不据此宣称本机 Neo4j 已验证。B 本次仍不操作 Neo4j。

## 本次随附数据的实际状态（2026-11-08）

本次提供的 `effective.json` 是 **150 篇论文的自动结果基线**，包含 1848 个实体、2185 条关系，合计 4033 条记录：全部为 `automatic`，`human_confirmed` 和 `human_corrected` 均为 0，`rule_adjusted=true` 的条目也为 0。

这份文件没有人工确认、公共人工修正或反馈补词生效的结果。文档下述“管理员改名、移除、补词、撤回”介绍的是程序已经支持并通过自动化测试的能力，**不表示用户已实际发起反馈或管理员已对这 150 篇作过审核**。C 可先测试自动结果导入；修改/撤回的联动需在后续联调中另行验证，不把测试脚本的操作算成真实审核记录。

本次文件版本：`6c97a76de785646616f2e13845a3c93fdc2ba26d280d56ea14b00e20013b9629`。未来数据或公共处理变化后，以对应新文件中的统计与版本为准。

## 1. 导出的是什么

导出 B 当前知识阅读页使用的完整公共结果：自动抽取、有效旧审核修正，以及当前生效的反馈改名、移除、补词。新增自动关系正常输出，不要求逐条人工确认。

它复用 `KnowledgeFeedback._material`，不是另做一套“导出专用识别”。每篇的 `origin.public_revision` 与同一数据快照下的阅读接口一致。个人浏览器里的隐藏、改名、补充、阅读位置不会进入文件。

**旧 `confirmed.json` 的含义与接口保留**，仍仅服务于旧人工确认流程，不能代表新阅读页。C 原来的 `adapt_confirmed` 不接收新格式；请新增对应适配，不伪造 confirm/reviewer 来让旧适配器通过。

## 2. 获取方式

### 管理员页面

打开 `/admin/knowledge-feedback` 并登录，点击 **“导出当前有效知识”**。下载名为 `effective-<版本前12位>.json`，无反馈记录时也可导出。它是只读操作，不创建审核记录，不改变数据。

### HTTP 接口

```text
GET /api/admin/knowledge/effective-export
GET /api/admin/knowledge/effective-export?expected_revision=<64位版本>
```

沿用管理员会话。未登录返回 401；输入/存档不可用返回 503；导出期间反馈或规则变化、指定版本已过期返回 409；成功返回 JSON 附件及 `X-Knowledge-Revision`，`Cache-Control: no-store`。GET 不需要写操作 CSRF，不接受浏览器指定审核人。

接口不接受选择旧 confirmed 格式的开关，不会自动把状态升级为人工确认。

### 本机脚本，无需启动网页或 Neo4j

在仓库根目录：

```powershell
conda activate insight-prototype
python -m scripts.knowledge_builder.export_effective
```

默认输出到 `data/knowledge_builder/exports/effective.json`。读取 `server/.env` 中相同的 B 配置，已有进程环境变量优先；不要求生成管理员账号。输入文件、反馈存档和来源缓存只读，完成校验后原子替换导出文件；失败不覆盖旧文件。

可指定独立输入/存档或输出，不影响运行中页面配置：

```powershell
python -m scripts.knowledge_builder.export_effective --corpus data/knowledge_builder/source_corpus/corpus.json --output data/knowledge_builder/exports/effective.json
```

其他参数：`--reviews-dir`、`--vocabulary`、`--expected-revision`。不指定 corpus 且 B_SOURCE_CORPUS 未配置时，读取默认旧 20 篇自动结果；不隐式下载论文或补采来源。

## 3. 根字段

| 字段 | 含义 |
| --- | --- |
| `format_version` | 固定 `knowledge-effective/1.0` |
| `kind` | 固定 `effective_knowledge`，不叫 confirmed |
| `mode` | 固定 `full_snapshot`，不是增量变更 |
| `publication_policy` | `automatic_results_and_effective_public_corrections` |
| `revision` | 64 位内容 SHA256，可用于 C 的来源版本和幂等判断 |
| `generated_at` | UTC 生成时间，不参与版本计算 |
| `rule_fingerprint` | 本阶段代码/规则组合指纹 |
| `base_vocabulary_fingerprint` | 当前基础词表指纹 |
| `counts` | 论文、实体、关系数，以及全部实体/关系合计的处理状态统计 |
| `papers` | 按论文分区的当前完整结果 |

版本算法：除去根 `revision` 和 `generated_at`，对其余根内容使用 B 的 canonical JSON（UTF-8、键排序、无多余分隔空白、ensure_ascii=False）做 SHA256。每次只改变下载时间不会换版本。

新增待处理反馈、用户撤回未处理反馈不改变有效知识版本。公共改名、移除或补词生效会改变版本；管理员撤回处理且其他内容不变时，可以恢复到原有效版本。同版本再次导入可由 C 幂等处理。

## 4. 每篇分区

| 字段 | 含义 |
| --- | --- |
| `input` | 完整 PaperInput：OpenAlex ID、标题、摘要、年份、会议、作者机构、来源 URL、dataset_id |
| `origin.input_fingerprint` | 输入指纹，与证据中的 input_fingerprint 一致 |
| `origin.public_revision` | 此篇阅读页结果版本 |
| `origin.schema_version` / `extraction_rule_version` | 原框架和基础规则版本 |
| `origin.vocabulary_version` / `vocabulary_fingerprint` | 本篇实际用到的词表版本；来源补充不同，允许各篇不同 |
| `entities` / `relations` | 当前可见条目，含 candidate_id、content、evidence、provenance |
| `source_classifications` | 来源主题分类，语义不同于原文“提及主题”，不要伪造文字引用或无条件变为 mentions_topic |

实体的 `content` 延续 `key, kind, name, source_id`。关系的 `content` 延续 `source, kind, target`，两个端点引用本篇实体的 `content.key`；八类实体、七类关系不变。candidate_id 是论文内的条目身份；跨论文相同 content.key 表示同一来源/规范身份。

每条 `evidence` 延续 paper_id、dataset_id、source_url、input_fingerprint、field、quote、start、end、path。标题/摘要按 Python Unicode 字符位置定位；元数据按相对 input 的 path 定位，quote 为该值的 canonical JSON。前端 JS 若切片应继续按 Unicode code point 处理。

**名称修正目前可能只作用于某篇论文。** 相同实体 key 在不同分区可能有不同显示名，C 不应在合并时用“最后一篇覆盖所有名称”。可以按论文保留显示覆盖，或检查冲突后与 B 对齐；不要悄悄改变纠错作用范围。

## 5. 自动生成、人工确认和规则更新分开

每个条目携带：

```json
{
  "generation": "automatic",
  "review_state": "automatic",
  "rule_adjusted": false
}
```

- `generation`：本版条目均源自自动抽取，人工可对其修正。
- `review_state=automatic`：未逐条人工确认，**允许按当前产品约定展示**，不是必须继续排队审核。
- `review_state=human_confirmed`：存在有效旧人工确认，且确认内容与当前条目完全对应。新增证据不能未经核对就继承为整项人工确认。
- `review_state=human_corrected`：当前条目存在生效的公共改名，或有效旧人工内容/证据修正；不冒充完整人工确认。
- `rule_adjusted=true`：管理员补词/别名后，相比未加该反馈规则的自动结果，当前条目或依据发生变化。**这些新条目仍可以是 automatic**；管理员批准规则不等于逐条确认所有命中。

实体被修正，不自动把所有相关关系标成人工处理。管理员保留原结果、关闭反馈也不等于确认全部知识。撤回处理后的条目按剩余有效规则重新计算状态。

## 6. 移除与撤回：C 必须按完整快照发布

移除对象后，该对象及引用它的连线都不输出；移除单条关系不会移除端点。撤回后重新生成快照，相应内容恢复。文件不包含失效历史或删除清单。

C 应按该完整快照创建新来源批次并切换发布批次，而不是把文件追加到上一版上。否则被移除的条目仍会留在正式图谱。替换范围是本导出代表的 B 数据集/发布批次，不代表删除 C 的所有历史数据或其他来源；旧批次是否保留由 C 的批次策略决定。

读取示例：

```python
import json
from pathlib import Path
from src.knowledge_builder.effective_export import validate_effective_export

document = json.loads(Path("effective.json").read_text(encoding="utf-8"))
validate_effective_export(document)
source_version = document["revision"]
for part in document["papers"]:
    paper_id = part["input"]["openalex_id"]
    # 按 C 的新适配器转换本篇 entities / relations；保留证据和 provenance。
```

B 已检查输入/证据、版本、重复 ID、关系端点与类型。C 的 BatchInput、Neo4j 写入和发布仍需适配并验证，不能把 B 导出通过等同于 C 联调通过。

## 7. 隐私与复现边界

不导出反馈原文、撤回历史、浏览器 owner token/摘要、管理员处理理由、账号凭据、本地路径或个人视图。记录中的论文作者和机构属于论文本身的公开元数据。

data、reports、server/.env 沿用忽略规则，不随 Git 自动上传。团队需要按来源准备命令生成输入，或由管理员另行提供导出文件；管理员浏览器中的个人视图不会混入文件。原有 20 篇模式与增强 150 篇模式都支持此协议。

关键验证：

```powershell
python -m unittest tests.knowledge_builder.test_effective_export tests.knowledge_builder.test_feedback_api
python -m unittest discover -s tests/knowledge_builder -p 'test_*.py'
```
