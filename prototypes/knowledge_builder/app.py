"""知识构建本地原型。通过 scripts.knowledge_builder.workbench 启动。"""

import os
from pathlib import Path

import streamlit as st

from prototypes.knowledge_builder.presentation import (
    KINDS,
    STATUSES,
    candidate_label,
    candidate_rows,
    graph_svg,
    highlighted_context,
)
from src.knowledge_builder.assessment_io import quality_markdown
from src.knowledge_builder.evaluation import build_annotation_template
from src.knowledge_builder.models import Entity, Relation
from src.knowledge_builder.workbench import Workbench, json_bytes

ROOT = Path(__file__).resolve().parents[2]


def select_paper(workbench, papers, key):
    identifiers = [paper.openalex_id for paper in papers]
    if st.session_state.get(key) not in identifiers:
        st.session_state[key] = identifiers[0]
    selected = st.selectbox(
        "选择论文",
        identifiers,
        format_func=lambda identifier: workbench.paper_by_id[identifier].title,
        key=key,
    )
    return workbench.paper_by_id[selected]


def metrics(workbench):
    counts = workbench.counts()
    for column, label, value in zip(
        st.columns(4),
        ("真实论文", "实体候选", "关系候选", "已确认关系"),
        (
            len(workbench.papers),
            sum(len(r.entities) for r in workbench.results),
            sum(len(r.relations) for r in workbench.results),
            counts["confirmed"]["relations"],
        ),
    ):
        column.metric(label, value)


def overview(workbench):
    st.subheader("从论文到可追溯知识")
    st.write(
        "先看真实论文和程序找到的内容，需要时核对原文，结果可以保存、恢复并分别导出。"
    )
    metrics(workbench)
    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("#### 第一周能力概览")
        st.dataframe(
            [
                {
                    "环节": "真实样本与证据",
                    "当前情况": "20 篇；标题、摘要、来源和证据位置可查看",
                },
                {
                    "环节": "候选抽取",
                    "当前情况": "8 类实体、7 类关系；词表和规则有版本",
                },
                {
                    "环节": "人工核对工具",
                    "当前情况": "确认 / 驳回 / 改名 / 撤回；每次操作保存",
                },
                {
                    "环节": "导出与检查",
                    "当前情况": "三种状态分文件；自动质量报告与五篇材料",
                },
                {
                    "环节": "真实质量验证",
                    "当前情况": "独立测试、真人标注校准和五篇确认仍待执行",
                },
                {
                    "环节": "团队集成",
                    "当前情况": "图数据库、正式 API、登录与主前端尚未接入",
                },
            ],
            hide_index=True,
            width="stretch",
        )
    with right:
        report = workbench.quality()
        st.markdown("#### 当前找到哪些对象")
        st.bar_chart(
            {
                "类别": [KINDS[k] for k in report["entities_by_type"]],
                "数量": list(report["entities_by_type"].values()),
            },
            x="类别",
            y="数量",
            color="#0f766e",
        )
        st.caption("按篇计数，同一方法出现在多篇会多次计入；候选数量不是准确率。")
    st.info(
        "建议先进入「论文与候选」看效果。核对是按需使用的工具，不要求你现在逐条检查全部结果。"
    )


def paper_browser(workbench):
    st.subheader("论文与候选")
    st.caption("筛选基于当前未驳回候选，用于本地检查，不代替团队正式检索接口。")
    query = st.text_input(
        "关键词", key="paper_query", placeholder="搜索标题或摘要，例如 YOLO"
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        year = st.selectbox(
            "年份",
            [None] + sorted({paper.year for paper in workbench.papers}),
            format_func=lambda value: "全部年份" if value is None else str(value),
            key="paper_year",
        )
    methods, topics = dict(workbench.terms("method")), dict(workbench.terms("topic"))
    # 切换词表版本时，旧筛选项可能不再存在；在创建控件前清空失效选项。
    for key, available in (("paper_method", methods), ("paper_topic", topics)):
        if st.session_state.get(key) not in available:
            st.session_state[key] = None
    with col2:
        method = st.selectbox(
            "方法",
            [None] + list(methods),
            format_func=lambda key: "全部方法" if key is None else methods[key],
            key="paper_method",
        )
    with col3:
        topic = st.selectbox(
            "主题",
            [None] + list(topics),
            format_func=lambda key: "全部主题" if key is None else topics[key],
            key="paper_topic",
        )
    matches = workbench.filter_papers(
        query=query, year=year, method=method, topic=topic
    )
    st.caption(f"找到 {len(matches)} / {len(workbench.papers)} 篇论文")
    if not matches:
        st.info("没有符合条件的论文，请清空关键词或调整筛选。")
        return
    paper = select_paper(workbench, matches, "browser_paper")
    session = workbench.sessions[paper.openalex_id]
    st.markdown(f"#### {paper.title}")
    st.caption(f"{paper.venue} · {paper.year} · {paper.openalex_id}")
    source, objects, graph, details = st.tabs(
        ["原始内容", "实体与关系", "本地关系示意", "来源与版本"]
    )
    with source:
        st.markdown("**摘要**")
        st.write(paper.abstract or "该论文缺少摘要。")
        st.link_button("打开论文来源", paper.source_url)
        st.markdown("**作者与机构（来源记录）**")
        st.dataframe(
            [
                {
                    "类别": KINDS[item.content.kind],
                    "名称": item.content.name,
                    "来源 ID": item.content.source_id or "缺失，使用本地定位",
                }
                for item in session.items
                if isinstance(item.content, Entity)
                and item.content.kind in {"author", "institution"}
            ],
            hide_index=True,
            width="stretch",
        )
    with objects:
        st.dataframe(candidate_rows(session), hide_index=True, width="stretch")
    with graph:
        st.caption(
            "由本地候选生成，不是 Neo4j 查询。虚线表示待核对，绿色边框表示已确认；已驳回对象不展示。"
        )
        svg, shown, total = graph_svg(session)
        st.html(svg)
        st.caption(f"为便于阅读展示 {shown}/{total} 个对象；完整对象与关系见表格。")
    with details:
        index = next(
            i
            for i, p in enumerate(workbench.papers)
            if p.openalex_id == paper.openalex_id
        )
        result = workbench.results[index]
        st.json(
            {
                "论文 ID": paper.openalex_id,
                "样本集": paper.dataset_id,
                "来源": paper.source_url,
                "词表版本": result.vocabulary_version,
                "规则版本": result.rule_version,
                "输入指纹": result.input_fingerprint,
                "诊断": result.diagnostics,
            }
        )


def jump_to_entity(candidate_id):
    st.session_state["review_collection"] = "实体"
    st.session_state["review_status"] = "全部"
    st.session_state["review_candidate"] = candidate_id


def error_message(exc):
    message = str(exc)
    if "reason" in message:
        return "请填写本条判断或修改的理由。"
    if "Reviewer" in message:
        return "请先在左侧填写记录姓名。"
    if "endpoint" in message:
        return "这条关系的两个对象需要先分别确认。"
    if "must change" in message:
        return "名称没有变化，不需要重复保存。"
    if "nonempty display name" in message:
        return "显示名称不能为空。"
    if "changed on disk" in message or "exists" in message:
        return "本地文件已变化或正在被其他窗口使用，请重新载入进度后再操作。"
    return "操作未保存。请检查当前状态、输入内容和本地存档。"


def review_candidates(workbench):
    st.subheader("候选核对")
    st.caption(
        "程序初始结果不等于已确认知识。只有你实际阅读并认可时，再执行确认；每次决定都会保存。"
    )
    paper = select_paper(workbench, workbench.papers, "review_paper")
    session = workbench.sessions[paper.openalex_id]
    left, right = st.columns(2)
    with left:
        collection = st.radio(
            "查看记录", ["实体", "关系"], horizontal=True, key="review_collection"
        )
    with right:
        status_label = st.selectbox(
            "当前状态", ["全部"] + list(STATUSES.values()), key="review_status"
        )
    options = [
        item
        for item in session.items
        if isinstance(item.content, Entity) == (collection == "实体")
        and (status_label == "全部" or STATUSES[item.status] == status_label)
    ]
    if not options:
        st.info("当前条件下没有候选。")
        return
    by_id = {item.candidate_id: item for item in options}
    if st.session_state.get("review_candidate") not in by_id:
        st.session_state["review_candidate"] = options[0].candidate_id
    identifier = st.selectbox(
        "选择候选",
        list(by_id),
        key="review_candidate",
        format_func=lambda key: candidate_label(by_id[key], session),
    )
    item = by_id[identifier]
    st.markdown(f"**当前状态：{STATUSES[item.status]}**")
    can_confirm = item.status == "pending"
    if isinstance(item.content, Relation):
        endpoints = workbench.endpoint_items(paper.openalex_id, item.content)
        can_confirm = can_confirm and all(
            endpoint.status == "confirmed" for endpoint in endpoints
        )
        if not can_confirm and item.status == "pending":
            st.info("先确认这条关系的两个对象；点击下面按钮查看对象及证据。")
        for column, endpoint in zip(st.columns(2), endpoints):
            column.button(
                f"查看{KINDS[endpoint.content.kind]}：{endpoint.content.name[:35]}（{STATUSES[endpoint.status]}）",
                key="endpoint_" + endpoint.candidate_id,
                on_click=jump_to_entity,
                args=(endpoint.candidate_id,),
            )
    st.markdown("#### 证据在哪里")
    for index, proof in enumerate(item.evidence, 1):
        with st.expander(
            f"证据 {index} · "
            + (
                "标题"
                if proof.field == "title"
                else "摘要"
                if proof.field == "abstract"
                else "来源字段"
            ),
            expanded=index == 1,
        ):
            context = highlighted_context(paper, proof)
            if context is not None:
                st.html(context)
                st.caption(f"字符范围 [{proof.start}, {proof.end})，针对当前输入文字")
            else:
                st.code(" → ".join(str(part) for part in proof.path))
            st.code(proof.quote, language="text")
    with st.form("review_decision"):
        reason = st.text_area(
            "判断理由",
            key="decision_reason",
            placeholder="写下你核对原文后的实际判断依据",
        )
        name = st.text_input(
            "显示名称",
            value=item.content.name
            if isinstance(item.content, Entity)
            else "关系不在这里改名",
            disabled=not isinstance(item.content, Entity),
            key="corrected_name_" + identifier,
        )
        cols = st.columns(4)
        confirm = cols[0].form_submit_button(
            "确认", key="confirm_review", type="primary", disabled=not can_confirm
        )
        reject = cols[1].form_submit_button(
            "驳回", key="reject_review", disabled=item.status != "pending"
        )
        correct = cols[2].form_submit_button(
            "修改名称",
            key="correct_review",
            disabled=item.status != "pending" or not isinstance(item.content, Entity),
        )
        reopen = cols[3].form_submit_button(
            "重新检查", key="reopen_review", disabled=item.status == "pending"
        )
    action = (
        "confirm"
        if confirm
        else "reject"
        if reject
        else "correct"
        if correct
        else "reopen"
        if reopen
        else None
    )
    if action:
        try:
            workbench.apply(
                paper.openalex_id,
                identifier,
                action,
                reviewer=st.session_state["reviewer_name"],
                reason=reason,
                name=name,
            )
        except (OSError, ValueError) as exc:
            st.error(error_message(exc))
            with st.expander("查看具体原因"):
                st.code(str(exc))
        else:
            st.session_state["notice"] = (
                "操作已保存。修改名称后仍需确认；重新检查实体时，相关已确认关系会退回待核对。"
            )
            st.rerun()
    st.caption(
        "修改的是显示名称，不改来源原文、对象身份或关系方向；复杂纠正仍需后续完善。"
    )
    with st.expander("这篇论文的操作记录"):
        if session.history:
            st.dataframe(
                [
                    {
                        "序号": event.sequence,
                        "动作": event.action,
                        "记录人": event.reviewer,
                        "理由": event.reason,
                        "时间（UTC）": event.occurred_at,
                        "之前": STATUSES[event.before.status],
                        "之后": STATUSES[event.after.status],
                    }
                    for event in session.history
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.write("还没有操作记录。")
    st.download_button(
        "下载这篇论文的工作进度",
        workbench.archive_bytes(paper.openalex_id),
        file_name="review-progress.json",
        mime="application/json",
    )


def exports_and_quality(workbench):
    st.subheader("导出与质量检查")
    report = workbench.quality()
    metrics(workbench)
    st.markdown("#### 分开保存，避免把候选当成知识")
    bundle = workbench.exports()
    for column, status in zip(st.columns(3), ("confirmed", "pending", "rejected")):
        with column:
            st.markdown(f"**{STATUSES[status]}**")
            counts = bundle[status]["counts"]
            st.caption(f"{counts['entities']} 个实体 · {counts['relations']} 条关系")
            st.download_button(
                "下载 JSON",
                json_bytes(bundle[status]),
                file_name=status + ".json",
                mime="application/json",
                key="download_" + status,
            )
    st.download_button(
        "下载完整交付包 ZIP",
        workbench.export_zip(),
        file_name="knowledge-export.zip",
        mime="application/zip",
        key="download_bundle",
    )
    if st.button("生成并保存导出包", key="save_export"):
        try:
            path = workbench.export_to_disk()
            st.success("已生成新导出目录，不覆盖旧结果。")
            st.code(str(path))
        except (OSError, ValueError) as exc:
            st.error(f"导出未完成：{exc}")
    st.caption("导出格式仍是集成草案；空的已确认文件是正常状态，不会自动补人工确认。")
    st.divider()
    st.markdown("#### 自动质量盘点")
    st.write(
        f"来源诊断 {report['diagnostic_count']} 条；有方法候选的论文 {report['papers_with_category']['method']} 篇；有数据集候选的论文 {report['papers_with_category']['dataset']} 篇。"
    )
    st.dataframe(
        [
            {
                "论文": row["title"],
                "未命中的类别": "、".join(
                    KINDS[k] for k in row["missing_text_categories"]
                )
                or "无",
                "来源诊断数": len(row["diagnostics"]),
            }
            for row in report["per_paper"]
        ],
        hide_index=True,
        width="stretch",
    )
    st.info(
        "这些是命中和缺失统计，不是准确率。当前独立测试集为空，未填参考答案时不会生成评分。"
    )
    st.download_button(
        "下载易读质量报告",
        quality_markdown(report),
        file_name="quality.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载空白独立答案模板",
        json_bytes(build_annotation_template(workbench.papers)),
        file_name="annotations.json",
        mime="application/json",
    )
    if st.button("生成五篇验证材料", key="prepare_validation"):
        try:
            path = workbench.prepare_validation()
            st.success("验证材料已生成；答案模板保持空白，不会将预测当成正确答案。")
            st.code(str(path))
        except (OSError, ValueError) as exc:
            st.error(f"材料未生成：{exc}")
    with st.expander("团队功能占位"):
        st.write(
            "Neo4j 查询、正式检索 API、登录鉴权和团队主前端尚未接入。本页不代替其他成员的实现。"
        )


def main():
    st.set_page_config(
        page_title="Research Insight · 知识构建", page_icon="📚", layout="wide"
    )
    st.markdown(
        """<style>
    .stApp {background:#f7f9fc;} h1,h2,h3,h4 {color:#172b4d;}
    [data-testid="stSidebar"] {background:#ffffff;border-right:1px solid #e2e8f0;}
    [data-testid="stMetric"] {background:white;padding:18px;border:1px solid #e2e8f0;border-radius:12px;}
    .block-container {padding-top:2rem;max-width:1450px;}
    </style>""",
        unsafe_allow_html=True,
    )
    st.sidebar.title("Research Insight")
    st.sidebar.caption("知识构建 · 本地工作台原型")
    page = st.sidebar.radio(
        "工作区域", ["概览", "论文与候选", "候选核对", "导出与质量"], key="page"
    )
    choice = st.sidebar.selectbox(
        "词表版本",
        ["current", "legacy"],
        format_func=lambda value: (
            "当前 · 53 个词条" if value == "current" else "历史 · 8 个词条"
        ),
        key="vocabulary_choice",
    )
    st.sidebar.text_input(
        "记录姓名", key="reviewer_name", placeholder="仅保存核对决定时需要"
    )
    st.sidebar.caption("这里的姓名用于操作记录，不是团队登录。")
    if st.sidebar.button("重新载入本地进度", key="reload_workbench"):
        st.session_state.pop("workbench", None)
        st.rerun()
    data_directory = os.getenv("KNOWLEDGE_WORKBENCH_DATA") or None
    vocabulary_path = (
        ROOT / "examples/knowledge_builder/vocabulary_v0.1.json"
        if choice == "legacy"
        else None
    )
    signature = (choice, data_directory)
    try:
        if (
            "workbench" not in st.session_state
            or st.session_state.get("workbench_signature") != signature
        ):
            with st.spinner("读取真实样本并校验已有进度…"):
                st.session_state["workbench"] = Workbench(
                    ROOT, vocabulary_path=vocabulary_path, data_directory=data_directory
                )
                st.session_state["workbench_signature"] = signature
        workbench = st.session_state["workbench"]
    except (OSError, ValueError) as exc:
        st.error("数据未载入。旧存档请选对应词表；文件冲突或损坏时请先检查本地进度。")
        st.code(str(exc))
        return
    st.sidebar.divider()
    st.sidebar.write(
        f"{len(workbench.papers)} 篇真实论文 · {workbench.vocabulary['version']}"
    )
    st.sidebar.caption("不连接数据库，不访问外网。来源样本保持不变。")
    st.caption("RESEARCH INSIGHT / KNOWLEDGE WORKBENCH")
    st.title("知识构建工作台")
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    {
        "概览": overview,
        "论文与候选": paper_browser,
        "候选核对": review_candidates,
        "导出与质量": exports_and_quality,
    }[page](workbench)


if __name__ == "__main__":
    main()
