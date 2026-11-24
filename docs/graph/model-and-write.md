# 图模型、索引、统一写入及批次契约 · c-graph/1.0

## 命名空间与索引

使用 `CVEntity / CV_LINK / CVBatch / CVRegistry` 命名空间，不复用 A 的 `Paper.mysql_id` 或 `Venue.name`。没有全库清理语句，不修改 A 原始库。八类业务实体通过 kind 区分：paper、author、institution、topic、method、task、dataset、venue。

`CVEntity(batch_id,id)` 唯一；`CVBatch.id`、`CVRegistry.id` 唯一；普通复合索引 `(batch_id,kind,year)`、`(batch_id,kind,name)`。由 initialize/CLI init 可重跑创建，兼容 Community Edition。子图使用有界 1—2 跳遍历，无 APOC 依赖。名称包含搜索目前扫描批次内节点，周一小样本可用；规模化后需要全文索引及性能基准。

七类逻辑关系保存为 `CV_LINK.kind`，允许列表及方向：

| kind | 起点 | 终点 | 含义 |
|---|---|---|---|
| has_author | paper | author | 来源署名 |
| affiliated_with | author | institution | 此论文证据中的隶属，非永久归属 |
| published_in | paper | venue | 发表场所 |
| mentions_topic | paper | topic | 主题提及 |
| mentions_method | paper | method | 方法提及，不宣称使用或发明 |
| mentions_task | paper | task | 任务提及 |
| mentions_dataset | paper | dataset | 数据集提及，不宣称完成实验 |

研究方向按 topic 词表表达，不擅自增加第九类实体。若需要方向独立维度，需 B 定义词表层级并共同升级契约。

## ID、证据和统一写入

id 为跨机器稳定字符串，如 `paper:W4402754006`，不使用 MySQL 自增 ID 或 Neo4j elementId 作为业务 ID。B 适配器保留 B 的 entity.key，来源 OpenAlex ID 保存在 source_id；这两种输入 ID 不自动拼接合并，应整批采用同一种命名策略。D 跳转需使用 C 返回的 id，不将 A 的数字 id 直接用于 C。

调用 `GraphRepository.ingest(BatchInput)` 或受保护的 `POST /api/admin/graph/batches` 是 C 的唯一图写入入口。完整 JSON Schema 可由 OpenAPI 的 BatchInput 获得；Python 模型是校验的唯一来源。批次含 source_batch_id、schema_version、vocabulary_version、provenance、entities、relations。原始来源库由 A 持有；C 不复制原始 PDF，不写 MySQL。

实体含 id/kind/name/updated_at，论文必须有 year/source_url；未知摘要为 null，缺失信息放 missing_fields。关系必须 confirmed，必须有至少一条 evidence：paper_id/source_url/field/quote/locator/reviewer/reviewed_at。文本摘录必须在对应标题或摘要中，B 适配器另校验精确偏移和元数据路径。写入时校验端点存在、类型方向、重复关系、证据引用论文，不接受 pending/rejected。审核身份真实性依赖上游受保护的审核服务，JSON 自身不是签名。

关系 ID 是 source/kind/target 的 SHA256；所有证据聚合在关系 JSON 属性中，保留每篇论文的 paper_id。机构筛选必须匹配同一论文的隶属证据，不能把作者另一篇论文的任职传播过来。

## 原子导入、发布和恢复

每个批次是一份**完整快照**，不做增量覆盖或就地修改。快照复制实体和关系，以 batch_id 物理隔离，适合本周 5—30 篇规模。A/B 应聚合要发布的完整数据后一次调用；不能将一份快照分成多个相同 batch_id 上传。最大 10000 实体 / 30000 关系，超过需新设计批量事务和完成标志。

导入用一个 Neo4j managed write transaction 创建批次、节点和关系；中途异常整批回滚。相同 batch_id 与标准化内容摘要一致则 replay=true，无重复写入；内容不同返回 409，不覆盖人工修正。摘要忽略实体/关系的顺序，但保留证据列表顺序，调用方需稳定生成该列表。

所有导入/发布先对单个 registry 执行依赖更新获取写锁，防止并发重复与发布冲突。发布在同一事务检查 expected_active_batch_id、批次计数、provenance，然后切换唯一 active_batch_id。夹具须显式 allow_developer_fixture。失败不切换指针。当前质量门槛仅是结构与计数完整性，不声称达到覆盖率或抽样准确率阈值；完整评估报告门槛留待 B 的封存报告接入。

批次 ready → published；旧批次保留 published 状态以支持已打开页面固定版本读取。指定 batch_id 只允许读取曾发布快照，不允许研究端读取 ready。每个研究事务在开始时解析一次批次，全事务固定该值。前端后续请求必须携带返回的 batch_id，清除／重新检索可重新选择最新版本。恢复可在校验当前版本后重新发布旧批次，禁止手动删除数据库或修改已发布内容。

测试使用 Neo4j 官方驱动的 [managed transaction](https://neo4j.com/docs/python-manual/current/transactions/)；事务函数可能重试，因此输入及返回不能依赖外部副作用。
