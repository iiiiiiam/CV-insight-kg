"""业务导出测试；确认仅模拟程序流程，不作为真人确认样例。"""

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.knowledge_builder.export import build_exports, validate_exports
from src.knowledge_builder.export_io import load_exports, write_exports
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.review import ReviewSession
from src.knowledge_builder.review_storage import save_review

ROOT = Path(__file__).resolve().parents[2]


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.paper = PaperInput(
            "test:paper",
            "Object Detection with YOLO",
            "YOLO for object detection.",
            2024,
            "CVPR",
            [],
            "test:source",
            "test-only",
        )
        self.result = extract_candidates(self.paper)
        self.session = ReviewSession(self.paper, self.result)
        self.root = next(c for c in self.result.entities if c.entity.kind == "paper")
        self.task = next(c for c in self.result.entities if c.entity.kind == "task")
        self.method = next(c for c in self.result.entities if c.entity.kind == "method")
        self.link = next(r for r in self.result.relations if r.kind == "mentions_task")
        self.actor = {
            "reviewer": "program-test",
            "reason": "Test only; not actual annotation",
        }

    def bundle(self):
        return build_exports(
            [self.paper], [self.result], {self.paper.openalex_id: self.session}
        )

    def confirm_task_relation(self):
        self.session.correct(self.task.candidate_id, name="目标检测", **self.actor)
        for candidate in (self.root, self.task, self.link):
            self.session.confirm(candidate.candidate_id, **self.actor)

    def test_unreviewed_candidates_never_become_confirmed_and_build_is_deterministic(
        self,
    ):
        before = deepcopy(self.result)
        bundle = build_exports([self.paper], [self.result])
        self.assertEqual(bundle["confirmed"]["papers"], [])
        self.assertEqual(bundle["rejected"]["papers"], [])
        self.assertEqual(
            bundle["pending"]["counts"]["entities"], len(self.result.entities)
        )
        self.assertEqual(bundle, self.bundle())
        self.assertEqual(bundle, build_exports([self.paper], [self.result]))
        self.assertEqual(self.result, before)
        self.assertEqual(self.session.history, ())

    def test_mixed_states_context_and_explicit_review_provenance(self):
        self.confirm_task_relation()
        self.session.reject(self.method.candidate_id, **self.actor)
        bundle = self.bundle()
        confirmed = bundle["confirmed"]["papers"][0]
        self.assertEqual(
            bundle["confirmed"]["counts"], {"papers": 1, "entities": 2, "relations": 1}
        )
        self.assertEqual(confirmed["endpoint_context"], [])
        task = next(
            e
            for e in confirmed["entities"]
            if e["item"]["candidate_id"] == self.task.candidate_id
        )
        self.assertEqual(task["item"]["content"]["name"], "目标检测")
        self.assertEqual(task["review"]["reviewer"], "program-test")
        self.assertEqual(task["review"]["action"], "confirm")
        self.assertEqual(bundle["rejected"]["counts"]["entities"], 1)
        context = bundle["pending"]["papers"][0]["endpoint_context"]
        self.assertEqual(
            {e["item"]["status"] for e in context}, {"confirmed", "rejected"}
        )
        validate_exports(bundle, [self.paper])

    def test_reopen_removes_confirmed_relation_and_retains_why_it_is_pending(self):
        self.confirm_task_relation()
        self.session.reopen(self.task.candidate_id, **self.actor)
        bundle = self.bundle()
        self.assertEqual(bundle["confirmed"]["counts"]["relations"], 0)
        relation = next(
            e
            for e in bundle["pending"]["papers"][0]["relations"]
            if e["item"]["candidate_id"] == self.link.candidate_id
        )
        self.assertEqual(relation["review"]["action"], "reopen_dependency")

    def test_wrong_session_scope_and_duplicate_papers_rejected(self):
        changed = deepcopy(self.result)
        changed.rule_version = "other-version"
        with self.assertRaisesRegex(ValueError, "another extraction"):
            build_exports(
                [self.paper], [changed], {self.paper.openalex_id: self.session}
            )
        with self.assertRaises(ValueError):
            build_exports([self.paper, self.paper], [self.result, self.result])
        with self.assertRaises(ValueError):
            build_exports([self.paper], [])
        with self.assertRaises(ValueError):
            build_exports([self.paper], [self.result], {"unknown": self.session})

    def test_invalid_version_counts_and_status_leakage_rejected(self):
        original = self.bundle()
        for change in ("version", "count", "status", "review"):
            bundle = deepcopy(original)
            document = bundle["pending"]
            if change == "version":
                document["format_version"] = "future"
            elif change == "count":
                document["counts"]["papers"] = True
            elif change == "status":
                document["papers"][0]["entities"][0]["item"]["status"] = "confirmed"
            else:
                document["papers"][0]["entities"][0]["review"] = {
                    "sequence": 1,
                    "action": "confirm",
                    "reviewer": "test",
                    "reason": "test",
                    "occurred_at": "2026-10-31T00:00:00+00:00",
                }
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_exports(bundle, [self.paper])

    def test_source_text_and_evidence_tampering_rejected(self):
        original = self.bundle()
        for change in ("input", "quote", "offset"):
            bundle = deepcopy(original)
            section = bundle["pending"]["papers"][0]
            task = next(
                e
                for e in section["entities"]
                if e["item"]["candidate_id"] == self.task.candidate_id
            )
            if change == "input":
                section["input"]["title"] = "Invented"
            elif change == "quote":
                task["item"]["evidence"][0]["quote"] = "Invented"
            else:
                task["item"]["evidence"][0]["start"] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_exports(bundle, [self.paper])

    def test_missing_endpoints_and_wrong_relation_types_rejected(self):
        self.confirm_task_relation()
        original = self.bundle()
        for change in ("context", "direction", "unknown", "duplicate"):
            bundle = deepcopy(original)
            section = bundle["pending"]["papers"][0]
            if change == "context":
                section["endpoint_context"] = []
            elif change == "direction":
                section["relations"][0]["item"]["content"]["kind"] = "affiliated_with"
            elif change == "unknown":
                section["relations"][0]["item"]["content"]["source"] = "unknown"
            else:
                section["entities"].append(deepcopy(section["entities"][0]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_exports(bundle, [self.paper])

    def test_cross_file_context_must_match_actual_entity_and_scope_cannot_disappear(
        self,
    ):
        self.confirm_task_relation()
        bundle = self.bundle()
        bundle["pending"]["papers"][0]["endpoint_context"][0]["item"]["content"][
            "name"
        ] = "Inconsistent label"
        with self.assertRaisesRegex(ValueError, "context does not match"):
            validate_exports(bundle, [self.paper])
        empty = build_exports([], [])
        with self.assertRaisesRegex(ValueError, "every source input"):
            validate_exports(empty, [self.paper])

    def test_write_load_checksums_and_no_overwrite(self):
        self.confirm_task_relation()
        bundle = self.bundle()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export"
            write_exports(path, bundle, [self.paper])
            self.assertEqual(load_exports(path, [self.paper]), bundle)
            self.assertEqual(
                {p.name for p in path.iterdir()},
                {
                    "pending.json",
                    "confirmed.json",
                    "rejected.json",
                    "schema.json",
                    "manifest.json",
                },
            )
            before = (path / "confirmed.json").read_bytes()
            with self.assertRaises(FileExistsError):
                write_exports(path, bundle, [self.paper])
            self.assertEqual(before, (path / "confirmed.json").read_bytes())
            (path / "pending.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_exports(path, [self.paper])

    def test_failed_publish_leaves_no_partial_export_or_temp_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export"
            with patch(
                "src.knowledge_builder.export_io.os.rename",
                side_effect=OSError("test publish failure"),
            ):
                with self.assertRaises(OSError):
                    write_exports(path, self.bundle(), [self.paper])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_manifest_cannot_select_paths_outside_export_or_falsify_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export"
            write_exports(path, self.bundle(), [self.paper])
            manifest_path = path / "manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            for change in ("path", "count"):
                manifest = deepcopy(original)
                if change == "path":
                    manifest["files"]["../outside.json"] = "anything"
                else:
                    manifest["processed_papers"] = 100
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.subTest(change=change), self.assertRaises(ValueError):
                    load_exports(path, [self.paper])

    def test_real_twenty_papers_export_without_fabricating_confirmations_or_changing_samples(
        self,
    ):
        paths = [
            ROOT / "examples" / name
            for name in ("week1_baseline.json", "cvpr_2024_seed.jsonl")
        ]
        before = [p.read_bytes() for p in paths]
        papers = load_openalex_sample(paths[0])
        vocabulary = load_vocabulary(
            ROOT / "examples/knowledge_builder/vocabulary_v0.1.json"
        )
        results = [extract_candidates(paper, vocabulary) for paper in papers]
        bundle = build_exports(papers, results)
        self.assertEqual(
            bundle["pending"]["counts"],
            {"papers": 20, "entities": 238, "relations": 294},
        )
        self.assertEqual(
            bundle["confirmed"]["counts"], {"papers": 0, "entities": 0, "relations": 0}
        )
        self.assertEqual(bundle["rejected"]["papers"], [])
        self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_cli_uses_existing_review_archive_and_does_not_modify_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = root / "reviews"
            papers = load_openalex_sample(ROOT / "examples/week1_baseline.json")
            result = extract_candidates(papers[0])
            session = ReviewSession(papers[0], result)
            session.confirm(result.entities[0].candidate_id, **self.actor)
            archive = reviews / "custom-name.json"
            save_review(archive, session)
            before = archive.read_bytes()
            command = [
                sys.executable,
                "-m",
                "scripts.knowledge_builder.export",
                "--reviews-dir",
                str(reviews),
                "--output",
                str(root / "export"),
            ]
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("Loaded review archives: 1", run.stdout)
            self.assertEqual(
                load_exports(root / "export", papers)["confirmed"]["counts"][
                    "entities"
                ],
                1,
            )
            self.assertEqual(archive.read_bytes(), before)

    def test_cli_rejects_broken_or_duplicate_archives_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = root / "reviews"
            reviews.mkdir()
            command = [
                sys.executable,
                "-m",
                "scripts.knowledge_builder.export",
                "--reviews-dir",
                str(reviews),
                "--output",
                str(root / "export"),
            ]
            (reviews / "broken.json").write_text("{}", encoding="utf-8")
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((root / "export").exists())
            (reviews / "broken.json").unlink()
            paper = load_openalex_sample(ROOT / "examples/week1_baseline.json")[0]
            session = ReviewSession(paper, extract_candidates(paper))
            save_review(reviews / "one.json", session)
            save_review(reviews / "two.json", session)
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn("Multiple review archives", run.stderr)
            self.assertFalse((root / "export").exists())


if __name__ == "__main__":
    unittest.main()
