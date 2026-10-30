# 内存人工审核核心

版本：`b-review/0.1-draft`，B 本地原型，不是正式团队接口。
前置能力见 [候选抽取](candidates.md)。本阶段保留抽取结果，另行记录人工决定。

## 运行

从仓库根目录使用已有 insight 环境：

```powershell
python -m scripts.knowledge_builder.review --paper-index 1 --reviewer "你的姓名"
```

paper-index 从 1 开始，当前有效范围 1—20；它不是数据库 paper_id。
该入口不会自动确认候选。当前默认自动保存到被忽略的 data/knowledge_builder/reviews/ 并恢复已有进度，
详见 [storage.md](storage.md)。加 `--memory-only` 可使用原来的不落盘临时模式。

| 命令 | 作用 |
| --- | --- |
| list | 显示编号、类型或关系、当前状态 |
| show N | 查看候选 N 的完整证据 |
| confirm N | 确认候选，需填写理由；关系要求两端实体已经确认 |
| reject N | 驳回候选，需填写理由；不自动驳回相邻关系 |
| name N | 纠正实体显示名称，需填写理由；纠正后仍待审核 |
| reopen N | 已决定候选退回待审；若是实体，相关已确认关系也退回待审 |
| summary | 分别统计 pending、confirmed、rejected |
| history | 查看操作人、UTC 时间、理由、前后状态及改名内容 |
| quit | 退出；默认保留自动存档，memory-only 模式的决定会丢失 |

先 list，再 show，读完证据再决定。编号来自本次候选顺序，不是长期稳定 ID。

## Python 核心接口

```python
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.review import ReviewSession

paper = load_openalex_sample("examples/week1_baseline.json")[0]
result = extract_candidates(paper)
session = ReviewSession(paper, result)
pending = session.select("pending")
```

读完一个候选及其证据后，可以调用：

```python
candidate_id = pending.entities[0].candidate_id
# 仅在你确实阅读并认可该候选时执行，并填写自己的判断理由。
session.confirm(candidate_id, reviewer="你的姓名", reason="填写实际核对理由")
confirmed = session.select("confirmed")
events = session.history
```

主要接口是 confirm、reject、correct、reopen、get、select、check_input。
所有操作要求 reviewer 和非空 reason。调用者提供的 reviewer 只是记录值，没有身份认证功能。
会话建立时绑定论文和原抽取结果的副本；外部输入更新时应 check_input 检查并新建审核，不能沿用旧决定。
核心仍使用内存对象；独立 review_storage 模块负责保存和恢复，不把文件路径绑进审核操作。

## 状态与纠正范围

抽取候选仍只允许 pending。审核状态单独存在 ReviewItem 中，避免改坏原始结果。
ReviewItem 的 content 是 Entity 或 Relation，evidence 是不可修改的元组，status 为 pending/confirmed/rejected。
session.original 返回原抽取结果副本；session.history 返回审核事件的元组。

- confirm、reject、correct 只作用于 pending；已决定对象要先 reopen。
- correct 支持实体显示名称及实体/关系证据，不改变实体 key、类别、来源 ID 或关系两端和类型。
- 纠正证据必须通过原有校验；不能删掉仍被关联关系引用的实体证据，可先收窄关系证据。
- 纠正后仍 pending，需另行 confirm。名字改变不代表来源原文也改变。
- 实体 reopen 时，只把相关已确认关系退回待审，不自动确认/驳回其他对象；每次联动有 reopen_dependency 事件。
- 失败操作不改变状态、不追加事件。已确认关系的端点始终必须已确认。

## 本轮验证与边界

新增 13 项 unittest 审核测试，覆盖状态、端点约束、纠正、证据、操作历史、撤回联动、
输入变化、外部修改隔离，以及真实论文上的程序流程。
测试里的自动确认只是检验函数，不能充当真实人工确认或项目演示标注。
终端入口完成了读取、列出、统计、退出的只读冒烟验证。

后续已实现版本化文件保存、恢复、历史重放校验及[业务 JSON 导出草案](export.md)。
尚未实现团队正式契约冻结、UI、API 写回、身份合并、分类/方向纠正。
审核是原型检查/演示与质量校验能力，不是要求所有网站用户或 B 负责人逐条检查所有候选。
