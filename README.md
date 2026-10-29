# Insight-into-the-field-of-CV-research

目前本仓库的 gitignore 为自定义设置，说明如下：

### 允许提交（会被Git追踪）
下面这些内容正常 `git add` 即可：
- 项目源代码：爬虫脚本、文本抽取、知识图谱构建、后端查询、可视化前端代码（`src/`、`web_frontend/`）
- 项目文档：方案文档、设计图、部署说明（`docs/`）
- 少量测试样例数据：`sample_data/`，仅放几条论文样例用于演示调试，体积很小
- 依赖声明文件：`requirements.txt`
- 配置模板文件：例如 `config.template.yaml`（只保留占位符，**不含真实密码、Cookie**）
- 项目说明：`README.md`、`.gitignore`

### 忽略（不会被提交，由 `.gitignore` 控制）
1. **爬虫原始数据**：`raw_data/`、`raw_papers/`、`pdfs/`、`crawl_cache/`、爬取得到的大批量 `*.raw.jsonl`
2. **数据处理中间产物**：`processed_data/`、`output/`、`tmp/`、`temp/`、日志文件夹 `logs/`、`*.log`
3. **知识图谱与向量缓存**：Neo4j数据库目录 `neo4j_data/`、数据库dump备份 `*.dump`、embedding向量文件 `*.npy`、模型权重 `checkpoints/`、`model_weights/`、`vector_cache/`
4. **环境与依赖**：Python虚拟环境 `venv/`、`.venv/`、前端 `node_modules/`、打包产物 `dist/`、`build/`
5. **敏感隐私配置**：`.env`、`config_secret.yaml`、`secret.json`（存放Neo4j账号、爬虫Cookie、密钥）
6. IDE、系统缓存文件：`.idea/`、`.vscode/`、`.DS_Store`、`__pycache__/`

---

## 如果想提交少量原始样本说明，可以修改 gitignore:
1. 如果**希望某一类原本被忽略的文件能够提交**：
   打开 `.gitignore`，找到对应那一行，**删掉该行**，或者在行首加 `#` 注释掉。
   > 示例：如果想提交 `output/` 里的可视化截图，找到 `output/` 这一行，改成 `# output/`
2. 如果**希望新增一类文件不要提交**：
   在 `.gitignore` 文件末尾新加一行，写入文件夹名或者匹配规则。
   > 示例：新增忽略 `experiment_result/`，直接在文件里添加一行：`experiment_result/`
