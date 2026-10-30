# B：审核进度保存与恢复

本地存档格式：`b-review-file/0.1-draft`。这是 B 的开发存档，不是 C/D 的正式知识导出接口。
默认词表后续更新为 cv-terms/0.2；旧存档可加 --vocabulary examples/b_vocabulary_v0.1.json 恢复，详见 [词表兼容说明](b_vocabulary.md)。
配套核心见 [b_review.md](b_review.md)。没有要求每位用户或 B 负责人现在逐条审核全部候选。

## 运行

从仓库根目录、已有 insight 环境运行：

```powershell
python -m scripts.review_b_candidates --paper-index 1 --reviewer "你的姓名"
```

现在默认在 `data/b_reviews/` 按论文 ID 的 SHA256 命名保存 JSON；已有文件会先校验并恢复。
新文件的初始候选全部 pending。只有真实输入的操作才改变审核决定，不预置确认。
每次成功修改后自动保存，再次运行同一命令即可继续。data/ 已被 Git 忽略。
仅想临时试用，不创建或恢复文件时：

```powershell
python -m scripts.review_b_candidates --paper-index 1 --reviewer "你的姓名" --memory-only
```

也可通过 `--archive data/b_reviews/my-review.json` 指定存档。不要将不同论文或不同抽取版本写到同一个存档。
确认、驳回等命令与上一阶段相同；保存失败时当前操作不生效，已有存档不被部分覆盖。

## Python 接口

```python
from src.knowledge_builder.review_storage import save_review, load_review

# session 是与 paper、result 对应的 ReviewSession。
revision = save_review("data/b_reviews/example.json", session)
stored = load_review("data/b_reviews/example.json", paper, result)
session = stored.session

# 后续通过原有核心方法作真实决定，再使用读取时的版本指纹更新。
revision = save_review("data/b_reviews/example.json", session,
                       expected_revision=stored.revision)
```

首次写入不覆盖已有文件；更新必须携带上一次保存或加载得到的 revision。
revision 是磁盘文件内容指纹，用来发现“我读取后文件又被改了”的情况。
review_to_dict / restore_review 则只转换 Python 数据，可供未来其他存储适配器复用，不绑定文件路径。

## 存了什么，怎样检查

外层是 payload 和 sha256。payload 包含格式版本、审核规则版本、论文 ID、输入指纹、
完整初始抽取结果的指纹、当前各候选快照、事件历史。
初始抽取指纹也覆盖词表版本、词表内容指纹和规则版本；不能只凭论文 ID 相同恢复。

恢复时先验证校验值及版本，再验证与当前 paper/result 一致，随后通过 ReviewSession.replay
重放 confirm/reject/correct/reopen，比较每条事件的序号、操作前后内容、撤回联动及原时间。
最后检查重放得到的当前状态与文件当前状态完全一致。未知版本、损坏、证据不符、
缺少联动事件等都报错，不自动删档或重建一个“看似成功”的审核。
校验值不是数字签名，也不证明文件记录的操作人身份真实。

## 写入方式与边界

同目录临时文件完整写入、flush/fsync 后，再用 os.replace 替换正式文件。
同 API 的写入者使用独占创建的 .lock 文件互斥，更新前还比较 revision，防止旧进度覆盖新进度。
这不是多人协作数据库。进程异常中止可能留锁；先确认没有程序正在写，再人工处理遗留锁，不自动抢锁。
正常失败会清理本次临时文件及自己创建的锁；别人的锁不删除。

存档阶段没有做旧版本迁移、多个标注者合并、API/UI 对接或准确率评估。
后续已新增独立的[业务 JSON 导出草案](b_export.md)，不把存档本身当作知识文件。
新增 14 项存档测试，全套现为 69 项通过；CLI 跨进程保存恢复测试只在临时目录自动模拟，
不能当真实人工审核记录或 5 篇人工确认演示。
