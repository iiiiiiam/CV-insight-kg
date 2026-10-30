"""生成便于检查的 Markdown 与开发评估材料包。"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .assessment import ASSESSMENT_VERSION


def quality_markdown(report):
    lines = [
        "# B 自动质量盘点",
        "",
        "这是开发样本的自动统计，不是准确率评估或真人审核。",
        "",
        f"处理论文：{report['papers']}；实体候选：{report['entity_candidates']}；关系候选：{report['relation_candidates']}。",
        f"来源诊断：{report['diagnostic_count']}；未解析作者 ID：{report['unresolved_author_candidates']}。",
        "",
        "| 找到的类别 | 有候选的论文数 |",
        "| --- | ---: |",
    ]
    for kind, count in report["papers_with_category"].items():
        lines.append(f"| {kind} | {count} / {report['papers']} |")
    lines += [
        "",
        "没有命中不代表论文没有相关内容；命中率不等于召回率。",
        "",
        "## 逐篇情况",
        "",
        "| 论文 ID | 实体/关系数 | 未命中的文本类别 | 诊断数 |",
        "| --- | --- | --- | ---: |",
    ]
    for row in report["per_paper"]:
        lines.append(
            f"| {row['paper_id']} | {row['entity_count']} / {row['relation_count']} | {', '.join(row['missing_text_categories']) or '无'} | {len(row['diagnostics'])} |"
        )
    lines += [
        "",
        "完整标题、缺失列表和版本信息见 quality.json。无参考答案时 precision、recall、f1 保持 null。",
        "",
    ]
    return "\n".join(lines)


def demo_markdown(papers, results, *, vocabulary_path=None):
    lines = [
        "# B 五篇开发样本检查材料",
        "",
        "以下是程序候选，不是已完成人工确认的演示。原文保留输入内容，可能含上游断词或数值错误。",
        "",
        "后续有时间时可检查：名称和类别是否合适、证据是否支持提及、有哪些漏项。不要只为凑数量确认。",
        "",
        "独立标注用 annotations.json，从原文自己填写，不把本文件的预测复制成参考答案。",
        "",
    ]
    for index, (paper, result) in enumerate(zip(papers[:5], results[:5]), 1):
        vocabulary_option = (
            ""
            if vocabulary_path is None
            else f' --vocabulary "{Path(vocabulary_path).as_posix()}"'
        )
        lines += [
            f"## {index}. {paper.title}",
            "",
            f"来源：{paper.source_url}",
            "",
            "### 原始标题",
            "",
            paper.title,
            "",
            "### 还原摘要",
            "",
            paper.abstract or "（缺失）",
            "",
            "### 程序找到的文本候选（初始待审）",
            "",
        ]
        for candidate in result.entities:
            if candidate.entity.kind in {"topic", "method", "task", "dataset"}:
                lines.append(f"- {candidate.entity.kind}: {candidate.entity.name}")
                for proof in candidate.evidence[:2]:
                    lines.append(
                        f"  - {proof.field}[{proof.start}:{proof.end}] = {proof.quote!r}"
                    )
        lines += [
            "",
            "来源诊断："
            + ("；".join(result.diagnostics) or "未发现当前规则覆盖的来源缺失"),
            "",
            f"需要实际确认时可运行：`python -m scripts.review_b_candidates --paper-index {index} --reviewer 你的姓名{vocabulary_option}`。",
            "",
        ]
    return "\n".join(lines)


def write_assessment(destination, documents):
    """先完整写入同级临时目录，再发布；不覆盖已有目录。"""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Validation output exists; choose a new directory")
    files = {}
    for name, content in documents.items():
        if (
            Path(name).name != name
            or "/" in name
            or "\\" in name
            or name in {".", "..", "manifest.json"}
        ):
            raise ValueError("Invalid assessment filename")
        text = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
        )
        files[name] = (text.rstrip() + "\n").encode("utf-8")
    manifest = {
        "format_version": ASSESSMENT_VERSION,
        "purpose": "development_preparation_not_human_gold",
        "files": {
            name: hashlib.sha256(body).hexdigest() for name, body in files.items()
        },
    }
    files["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=destination.parent, prefix=".b-validation-"))
    try:
        for name, body in files.items():
            with (temporary / name).open("wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
        os.rename(temporary, destination)
    finally:
        if temporary.exists() and temporary.resolve().parent == destination.parent:
            for name in files:
                (temporary / name).unlink(missing_ok=True)
            temporary.rmdir()
    return destination
