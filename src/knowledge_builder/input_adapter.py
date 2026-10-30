"""读取 A 的 OpenAlex 固定样本，不连接数据库，不修改输入文件。"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import PaperInput


def _decode_abstract(index: dict[str, list[int]] | None) -> str | None:
    """按词的位置还原摘要，与 A 的 decode_abstract 保持一致。"""
    if not index:
        return None
    positions: dict[int, str] = {}
    for word, offsets in index.items():
        if not isinstance(word, str) or not isinstance(offsets, list):
            raise ValueError("Invalid abstract word or position list")
        for offset in offsets:
            if type(offset) is not int or offset < 0 or offset in positions:
                raise ValueError(
                    "Abstract positions must be unique nonnegative integers"
                )
            positions[offset] = word
    if not positions:
        return None
    # 不因异常位置创建巨大的字符串；正常摘要的位置应连续。
    if set(positions) != set(range(len(positions))):
        raise ValueError("Abstract positions must be contiguous from zero")
    return " ".join(positions[i] for i in range(len(positions))).strip() or None


def adapt_openalex_work(
    work: dict[str, Any], *, venue: str, dataset_id: str
) -> PaperInput:
    """转换一篇记录；保留原始标题及作者机构，不推测缺失信息。"""
    identifier = work.get("id")
    title = work.get("display_name")
    year = work.get("publication_year")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("Missing OpenAlex ID")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing paper title")
    if type(year) is not int:
        raise ValueError("Missing or invalid publication year")
    if not venue or not dataset_id:
        raise ValueError("Venue and dataset ID are required")
    authorships = work.get("authorships", [])
    if not isinstance(authorships, list) or any(
        not isinstance(item, dict) for item in authorships
    ):
        raise ValueError("Authorships must be a list of records")
    index = work.get("abstract_inverted_index")
    if index is not None and not isinstance(index, dict):
        raise ValueError("Abstract index must be an object or null")
    return PaperInput(
        openalex_id=identifier,
        title=title,
        abstract=_decode_abstract(index),
        year=year,
        venue=venue,
        authorships=deepcopy(authorships),
        source_url=identifier,
        dataset_id=dataset_id,
    )


def load_openalex_sample(manifest_path: str | Path) -> list[PaperInput]:
    """读取 A 的基准清单及相邻 JSONL，校验后一次性返回全部论文。

    清单、文件或记录不一致时抛出 ValueError；文件访问错误原样抛出。
    不返回部分结果，不导入数据库，不创建任务或批次。
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("source") != "openalex":
        raise ValueError("Expected an OpenAlex sample manifest")
    for key in ("filename", "sha256", "dataset_id", "venue", "source_id"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"Missing manifest field: {key}")
    filename = manifest["filename"]
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise ValueError("Sample filename must name a file beside the manifest")
    if type(manifest.get("expected_count")) is not int:
        raise ValueError("Missing or invalid expected_count")
    if type(manifest.get("year")) is not int:
        raise ValueError("Missing or invalid manifest year")
    body = (manifest_path.parent / filename).read_bytes()
    if hashlib.sha256(body).hexdigest() != manifest["sha256"]:
        raise ValueError("Sample checksum differs from A's baseline")
    baseline_rows = manifest.get("papers")
    if not isinstance(baseline_rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("openalex_id"), str)
        for row in baseline_rows
    ):
        raise ValueError("Invalid baseline paper list")
    baseline = {row["openalex_id"]: row for row in baseline_rows}
    if len(baseline) != len(baseline_rows):
        raise ValueError("Duplicate baseline paper IDs")
    papers = []
    seen = set()
    for line_number, line in enumerate(body.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            work = json.loads(line)
            if not isinstance(work, dict):
                raise ValueError("Paper record must be an object")
            paper = adapt_openalex_work(
                work, venue=manifest["venue"], dataset_id=manifest["dataset_id"]
            )
            if paper.openalex_id in seen:
                raise ValueError("Duplicate sample paper ID")
            expected = baseline.get(paper.openalex_id)
            source = ((work.get("primary_location") or {}).get("source") or {}).get(
                "id"
            )
            if (
                expected is None
                or paper.title != expected.get("title")
                or paper.year != expected.get("year")
                or paper.year != manifest["year"]
                or work.get("doi") != expected.get("doi")
                or source != "https://openalex.org/" + manifest["source_id"]
            ):
                raise ValueError("Paper differs from A's baseline")
            seen.add(paper.openalex_id)
            papers.append(paper)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid sample line {line_number}: {exc}") from exc
    if len(papers) != manifest["expected_count"] or seen != set(baseline):
        raise ValueError("Sample count or IDs differ from A's baseline")
    return papers
