"""纯显示转换：中文标签、表格、原文高亮和本地关系示意。"""

import html
import math

from src.knowledge_builder.models import Entity, Relation

KINDS = {
    "paper": "论文",
    "author": "作者",
    "institution": "机构",
    "venue": "会议/期刊",
    "topic": "主题",
    "method": "方法",
    "task": "任务",
    "dataset": "数据集",
}
STATUSES = {"pending": "待核对", "confirmed": "已确认", "rejected": "已驳回"}
RELATIONS = {
    "has_author": "作者",
    "affiliated_with": "所属机构",
    "published_in": "发表于",
    "mentions_topic": "提及主题",
    "mentions_method": "提及方法",
    "mentions_task": "提及任务",
    "mentions_dataset": "提及数据集",
}
COLORS = {
    "paper": "#172b4d",
    "author": "#7c3aed",
    "institution": "#64748b",
    "venue": "#059669",
    "topic": "#0891b2",
    "method": "#2563eb",
    "task": "#0f766e",
    "dataset": "#b45309",
}


def candidate_label(item, session):
    if isinstance(item.content, Entity):
        label = f"{KINDS[item.content.kind]} · {item.content.name}"
    else:
        entities = {
            entry.content.key: entry.content.name
            for entry in session.items
            if isinstance(entry.content, Entity)
        }
        label = f"{entities[item.content.source]} → {RELATIONS[item.content.kind]} → {entities[item.content.target]}"
    return f"{STATUSES[item.status]} | {label}"


def candidate_rows(session, *, collection=None):
    rows = []
    for item in session.items:
        entity = isinstance(item.content, Entity)
        if (
            collection == "entities"
            and not entity
            or collection == "relations"
            and entity
        ):
            continue
        rows.append(
            {
                "类型": KINDS[item.content.kind]
                if entity
                else RELATIONS[item.content.kind],
                "内容": candidate_label(item, session).split(" | ", 1)[1],
                "状态": STATUSES[item.status],
                "证据数": len(item.evidence),
                "候选编号": item.candidate_id,
            }
        )
    return rows


def highlighted_context(paper, proof, padding=110):
    """只高亮已验证切片；所有原文都转义，避免把输入当 HTML。"""
    if proof.field not in {"title", "abstract"}:
        return None
    text = getattr(paper, proof.field) or ""
    start, end = proof.start, proof.end
    before = html.escape(text[max(0, start - padding) : start])
    quote = html.escape(text[start:end])
    after = html.escape(text[end : min(len(text), end + padding)])
    return f'<div style="line-height:1.9;padding:12px;background:#f0fdfa;border-radius:8px">{before}<mark style="background:#fde68a;padding:2px">{quote}</mark>{after}</div>'


def graph_svg(session, limit=13):
    all_nodes = [
        item
        for item in session.items
        if isinstance(item.content, Entity) and item.status != "rejected"
    ]
    nodes = sorted(
        all_nodes,
        key=lambda item: (
            item.content.kind != "paper",
            item.content.kind not in {"method", "task", "dataset", "topic"},
        ),
    )[:limit]
    if not nodes:
        return "<p>当前没有可展示的对象。</p>", 0, 0
    positions = {nodes[0].content.key: (500, 290)}
    for index, item in enumerate(nodes[1:]):
        angle = 2 * math.pi * index / max(len(nodes) - 1, 1) - math.pi / 2
        positions[item.content.key] = (
            500 + 375 * math.cos(angle),
            290 + 245 * math.sin(angle),
        )
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 590" role="img" aria-label="本地候选关系示意" style="width:100%;background:#f8fafc;border-radius:12px">',
        '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="7" refY="3.5" orient="auto"><path d="M0,0 L0,7 L7,3.5 z" fill="#94a3b8"/></marker></defs>',
    ]
    for item in session.items:
        if isinstance(item.content, Relation) and item.status != "rejected":
            relation = item.content
            if relation.source in positions and relation.target in positions:
                x1, y1 = positions[relation.source]
                x2, y2 = positions[relation.target]
                dx, dy = x2 - x1, y2 - y1
                # 线段停在节点边缘，使箭头不被节点矩形盖住。
                edge = min(
                    92 / abs(dx) if dx else math.inf, 28 / abs(dy) if dy else math.inf
                )
                start_x, start_y = x1 + dx * edge, y1 + dy * edge
                end_x, end_y = x2 - dx * edge, y2 - dy * edge
                parts.append(
                    f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" stroke="#cbd5e1" stroke-width="1.5" marker-end="url(#arrow)"/>'
                )
    for item in nodes:
        entity = item.content
        x, y = positions[entity.key]
        color = COLORS[entity.kind]
        label = entity.name if len(entity.name) <= 21 else entity.name[:20] + "…"
        border = "#16a34a" if item.status == "confirmed" else color
        dash = "" if item.status == "confirmed" else 'stroke-dasharray="5 3"'
        parts.append(
            f'<g><title>{html.escape(entity.name)} · {KINDS[entity.kind]} · {STATUSES[item.status]}</title><rect x="{x - 88}" y="{y - 24}" width="176" height="48" rx="10" fill="white" stroke="{border}" stroke-width="2" {dash}/><text x="{x}" y="{y - 4}" text-anchor="middle" font-size="12" fill="{color}" font-family="sans-serif">{KINDS[entity.kind]}</text><text x="{x}" y="{y + 14}" text-anchor="middle" font-size="12" fill="#172b4d" font-family="sans-serif">{html.escape(label)}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts), len(nodes), len(all_nodes)
