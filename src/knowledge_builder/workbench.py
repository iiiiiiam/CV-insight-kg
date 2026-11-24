"""本地工作台应用协调层；不导入 Streamlit，复用已有核心和存储规则。"""

import io
import json
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .assessment import build_evaluation_manifest, build_quality_report
from .assessment_io import demo_markdown, quality_markdown, write_assessment
from .evaluation import build_annotation_template, score_annotations
from .export import build_exports
from .export_io import export_files, write_exports
from .extraction import extract_candidates, fingerprint, load_vocabulary
from .input_adapter import load_openalex_sample
from .models import Entity
from .paths import default_review_directory, workspace_data
from .review import ReviewSession
from .review_storage import load_review_records, review_to_dict, save_review


def json_bytes(document):
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


class Workbench:
    def __init__(self, root: str | Path, *, vocabulary_path=None, data_directory=None):
        self.root = Path(root).resolve()
        self.vocabulary_path = vocabulary_path
        self.data_directory = (
            Path(data_directory).resolve()
            if data_directory is not None
            else workspace_data(self.root)
        )
        self.review_directory = (
            self.data_directory / "reviews"
            if data_directory is not None
            else default_review_directory(self.root)
        )
        self.vocabulary = load_vocabulary(vocabulary_path)
        self.papers = load_openalex_sample(self.root / "examples/week1_baseline.json")
        self.results = [
            extract_candidates(paper, self.vocabulary) for paper in self.papers
        ]
        self.paper_by_id = {paper.openalex_id: paper for paper in self.papers}
        records = load_review_records(self.review_directory, self.papers, self.results)
        self.sessions = {}
        self._archives, self._revisions = {}, {}
        for paper, result in zip(self.papers, self.results):
            identifier = paper.openalex_id
            if identifier in records:
                path, stored = records[identifier]
                self.sessions[identifier] = stored.session
                self._archives[identifier] = path
                self._revisions[identifier] = stored.revision
            else:
                self.sessions[identifier] = ReviewSession(paper, result)
        self._quality = None
        self._exports = None

    def counts(self):
        return {
            status: {
                "entities": sum(
                    len(session.select(status).entities)
                    for session in self.sessions.values()
                ),
                "relations": sum(
                    len(session.select(status).relations)
                    for session in self.sessions.values()
                ),
            }
            for status in ("pending", "confirmed", "rejected")
        }

    def filter_papers(self, *, query="", year=None, method=None, topic=None):
        matches = []
        for paper in self.papers:
            if year is not None and paper.year != year:
                continue
            if (
                query.strip().casefold()
                not in (paper.title + " " + (paper.abstract or "")).casefold()
            ):
                continue
            keys = {
                item.content.key
                for item in self.sessions[paper.openalex_id].items
                if isinstance(item.content, Entity) and item.status != "rejected"
            }
            if any(key is not None and key not in keys for key in (method, topic)):
                continue
            matches.append(paper)
        return matches

    def terms(self, kind):
        keys = {
            item.content.key
            for session in self.sessions.values()
            for item in session.items
            if isinstance(item.content, Entity)
            and item.content.kind == kind
            and item.status != "rejected"
        }
        return sorted(
            (kind + ":term:" + term["key"], term["name"])
            for term in self.vocabulary["terms"]
            if term["kind"] == kind and kind + ":term:" + term["key"] in keys
        )

    def endpoint_items(self, paper_id, relation):
        items = {
            item.content.key: item
            for item in self.sessions[paper_id].items
            if isinstance(item.content, Entity)
        }
        return tuple(items[key] for key in (relation.source, relation.target))

    def apply(self, paper_id, candidate_id, action, *, reviewer, reason, name=None):
        if paper_id not in self.sessions or action not in {
            "confirm",
            "reject",
            "correct",
            "reopen",
        }:
            raise ValueError("Unknown paper or review action")
        proposed = deepcopy(self.sessions[paper_id])
        kwargs = {"reviewer": reviewer, "reason": reason}
        if action == "correct":
            proposed.correct(candidate_id, name=name, **kwargs)
        else:
            getattr(proposed, action)(candidate_id, **kwargs)
        path = self._archives.get(
            paper_id, self.review_directory / (fingerprint(paper_id) + ".json")
        )
        revision = save_review(
            path, proposed, expected_revision=self._revisions.get(paper_id)
        )
        # 成功保存才替换页面当前会话；写盘冲突或失败不丢失旧状态。
        self.sessions[paper_id] = proposed
        self._archives[paper_id], self._revisions[paper_id] = path, revision
        self._quality, self._exports = None, None
        return proposed.get(candidate_id)

    def archive_bytes(self, paper_id):
        return json_bytes(review_to_dict(self.sessions[paper_id]))

    def quality(self):
        if self._quality is None:
            self._quality = build_quality_report(
                self.papers, self.results, self.sessions
            )
        return deepcopy(self._quality)

    def exports(self):
        if self._exports is None:
            self._exports = build_exports(self.papers, self.results, self.sessions)
        return deepcopy(self._exports)

    def export_to_disk(self):
        path = (
            self.data_directory
            / "exports"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        return write_exports(path, self.exports(), self.papers)

    def export_zip(self):
        # 下载生成同样五个文件，但不必为下载在磁盘制造临时副本。
        files = export_files(self.exports(), self.papers)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return output.getvalue()

    def prepare_validation(self):
        report = self.quality()
        annotations = build_annotation_template(self.papers)
        documents = {
            "quality.json": report,
            "quality.md": quality_markdown(report),
            "evaluation_manifest.json": build_evaluation_manifest(self.papers),
            "annotations.json": annotations,
            "evaluation.json": score_annotations(
                annotations, self.papers, self.results
            ),
            "demo_packet.md": demo_markdown(
                self.papers, self.results, vocabulary_path=self.vocabulary_path
            ),
        }
        path = (
            self.data_directory
            / "validation"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        return write_assessment(path, documents)
