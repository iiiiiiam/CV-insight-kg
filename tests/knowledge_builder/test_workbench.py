"""本地工作台协调层测试；所有决定只在临时目录，非真人标注。"""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from prototypes.knowledge_builder.presentation import graph_svg, highlighted_context
from src.knowledge_builder.export_io import load_exports
from src.knowledge_builder.models import Entity, Evidence, PaperInput, ReviewItem
from src.knowledge_builder.review_storage import save_review
from src.knowledge_builder.workbench import Workbench

ROOT = Path(__file__).resolve().parents[2]


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.workbench = Workbench(ROOT, data_directory=self.data)
        self.paper = self.workbench.papers[0]
        self.identifier = self.paper.openalex_id
        items = self.workbench.sessions[self.identifier].items
        self.root = next(
            item
            for item in items
            if isinstance(item.content, Entity) and item.content.kind == "paper"
        )
        self.task = next(
            item
            for item in items
            if isinstance(item.content, Entity) and item.content.kind == "task"
        )
        self.actor = {
            "reviewer": "workbench-program-test",
            "reason": "Program test, not real human annotation",
        }

    def test_initial_view_is_read_only_and_filter_dimensions_combine(self):
        self.assertEqual(
            self.workbench.counts()["confirmed"], {"entities": 0, "relations": 0}
        )
        matches = self.workbench.filter_papers(
            query="open-vocabulary", year=2024, method="method:term:yolo-world"
        )
        self.assertEqual(len(matches), 1)
        self.assertIn("YOLO-World", matches[0].title)
        self.assertEqual(self.workbench.filter_papers(query="no-such-phrase-test"), [])
        self.assertEqual(self.workbench.filter_papers(year=1900), [])
        self.assertEqual(list(self.data.iterdir()), [])

    def test_saved_decision_restores_and_invalid_decision_does_not_write(self):
        with self.assertRaises(ValueError):
            self.workbench.apply(
                self.identifier,
                self.root.candidate_id,
                "confirm",
                reviewer="",
                reason="test",
            )
        self.assertEqual(list(self.data.iterdir()), [])
        self.workbench.apply(
            self.identifier, self.root.candidate_id, "confirm", **self.actor
        )
        restored = Workbench(ROOT, data_directory=self.data)
        self.assertEqual(restored.counts()["confirmed"]["entities"], 1)
        self.assertEqual(
            restored.sessions[self.identifier].history,
            self.workbench.sessions[self.identifier].history,
        )

    def test_conflicting_window_cannot_overwrite_or_change_its_memory(self):
        self.workbench.apply(
            self.identifier, self.root.candidate_id, "confirm", **self.actor
        )
        other = Workbench(ROOT, data_directory=self.data)
        self.workbench.apply(
            self.identifier, self.task.candidate_id, "confirm", **self.actor
        )
        with self.assertRaisesRegex(ValueError, "changed on disk"):
            other.apply(self.identifier, self.task.candidate_id, "reject", **self.actor)
        self.assertEqual(
            other.sessions[self.identifier].get(self.task.candidate_id).status,
            "pending",
        )
        self.assertEqual(len(other.sessions[self.identifier].history), 1)

    def test_existing_custom_archive_name_is_updated_in_place(self):
        archive = self.data / "reviews" / "custom-name.json"
        save_review(archive, self.workbench.sessions[self.identifier])
        loaded = Workbench(ROOT, data_directory=self.data)
        loaded.apply(self.identifier, self.root.candidate_id, "confirm", **self.actor)
        self.assertEqual(list((self.data / "reviews").glob("*.json")), [archive])
        self.assertEqual(
            len(json.loads(archive.read_text(encoding="utf-8"))["payload"]["events"]), 1
        )

    def test_correction_and_reopen_reuse_core_endpoint_constraints(self):
        session = self.workbench.sessions[self.identifier]
        relation = next(
            item
            for item in session.items
            if getattr(item.content, "kind", None) == "mentions_task"
        )
        with self.assertRaisesRegex(ValueError, "endpoint"):
            self.workbench.apply(
                self.identifier, relation.candidate_id, "confirm", **self.actor
            )
        self.workbench.apply(
            self.identifier,
            self.task.candidate_id,
            "correct",
            name="目标检测",
            **self.actor,
        )
        for candidate in (self.root, self.task, relation):
            self.workbench.apply(
                self.identifier, candidate.candidate_id, "confirm", **self.actor
            )
        self.workbench.apply(
            self.identifier, self.task.candidate_id, "reopen", **self.actor
        )
        self.assertEqual(
            self.workbench.sessions[self.identifier].get(relation.candidate_id).status,
            "pending",
        )
        self.assertEqual(
            self.workbench.sessions[self.identifier]
            .get(self.task.candidate_id)
            .content.name,
            "目标检测",
        )

    def test_zip_download_is_the_same_valid_export_format(self):
        body = self.workbench.export_zip()
        target = self.data / "unzipped"
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "pending.json",
                    "confirmed.json",
                    "rejected.json",
                    "schema.json",
                    "manifest.json",
                },
            )
            for name in archive.namelist():
                (target / name).write_bytes(archive.read(name))
        bundle = load_exports(target, self.workbench.papers)
        self.assertEqual(
            bundle["pending"]["counts"],
            {"papers": 20, "entities": 285, "relations": 341},
        )
        self.assertEqual(bundle["confirmed"]["papers"], [])

    def test_validation_materials_keep_gold_blank_and_scores_null(self):
        destination = self.workbench.prepare_validation()
        annotations = json.loads(
            (destination / "annotations.json").read_text(encoding="utf-8")
        )
        outcome = json.loads(
            (destination / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            all(case["gold_entities"] is None for case in annotations["cases"])
        )
        self.assertEqual(outcome["status"], "awaiting_annotations")
        self.assertIsNone(outcome["precision"])

    def test_source_text_is_escaped_in_evidence_and_graph(self):
        paper = PaperInput(
            "test:p",
            "<script>COCO</script>",
            None,
            2024,
            "CVPR",
            [],
            "test:source",
            "test-only",
        )
        proof = Evidence(
            "test:p", "test-only", "test:source", "test", "title", "COCO", 8, 12
        )
        context = highlighted_context(paper, proof)
        self.assertNotIn("<script>", context)
        self.assertIn("&lt;script&gt;", context)
        item = ReviewItem(
            "test", Entity("test", "method", "<script>alert(1)</script>"), (), "pending"
        )
        svg, shown, total = graph_svg(SimpleNamespace(items=(item,)))
        self.assertEqual((shown, total), (1, 1))
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)


if __name__ == "__main__":
    unittest.main()
