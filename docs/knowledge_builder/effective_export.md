# B → C 当前有效知识导出 v1

协议：`knowledge-effective/1.0`。实现分支：`knowledge-enrich`。本文件定义 B 的中期交接格式，C 的导入/发布适配仍需 C 自行接入；B 不操作 Neo4j。

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
