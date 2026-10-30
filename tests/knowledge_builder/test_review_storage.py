"""审核存档与 CLI 测试；所有确认动作均是临时目录中的程序测试。"""

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.knowledge_builder.extraction import extract_candidates, fingerprint
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.review import ReviewSession
from src.knowledge_builder.review_storage import (
    load_review,
    restore_review,
    review_to_dict,
    save_review,
)

ROOT = Path(__file__).resolve().parents[2]


class ReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.paper = PaperInput(
            "test:paper",
            "Object Detection with YOLO",
            "Object detection on COCO.",
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
        self.link = next(r for r in self.result.relations if r.kind == "mentions_task")
        self.actor = {"reviewer": "program-test", "reason": "Not real human review"}

    def document(self):
        return review_to_dict(self.session)

    def restore(self, document):
        return restore_review(document, self.paper, self.result)

    @staticmethod
    def rehash(document):
        document["sha256"] = fingerprint(document["payload"])
        return document

    def decide_and_reopen(self):
        self.session.correct(self.task.candidate_id, name="目标检测", **self.actor)
        for candidate in (self.root, self.task, self.link):
            self.session.confirm(candidate.candidate_id, **self.actor)
        self.session.reopen(self.task.candidate_id, **self.actor)

    def test_pending_archive_round_trip_and_independent_sessions(self):
        restored = self.restore(self.document())
        self.assertEqual(restored.items, self.session.items)
        restored.confirm(self.root.candidate_id, **self.actor)
        self.assertEqual(self.session.history, ())

    def test_full_history_round_trip_preserves_snapshots_times_and_dependency_events(
        self,
    ):
        self.decide_and_reopen()
        self.session.reject(self.task.candidate_id, **self.actor)
        self.session.reopen(self.task.candidate_id, **self.actor)
        self.session.confirm(self.task.candidate_id, **self.actor)
        self.session.confirm(self.link.candidate_id, **self.actor)
        self.session.reopen(self.link.candidate_id, **self.actor)
        self.session.correct(
            self.link.candidate_id,
            evidence=self.session.get(self.link.candidate_id).evidence[:1],
            **self.actor,
        )
        self.session.confirm(self.link.candidate_id, **self.actor)
        restored = self.restore(self.document())
        self.assertEqual(restored.history, self.session.history)
        self.assertEqual(restored.items, self.session.items)
        self.assertEqual(restored.select("confirmed"), self.session.select("confirmed"))

    def test_checksum_and_unsupported_versions_rejected(self):
        document = self.document()
        document["payload"]["paper_id"] = "changed"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.restore(document)
        for field in ("format_version", "review_version"):
            document = self.document()
            document["payload"][field] = "future-version"
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "version"),
            ):
                self.restore(self.rehash(document))

    def test_input_and_extraction_changes_rejected(self):
        document = self.document()
        paper = deepcopy(self.paper)
        paper.abstract = "Changed input"
        with self.assertRaises(ValueError):
            restore_review(document, paper, self.result)
        for field in ("rule_version", "vocabulary_version", "vocabulary_fingerprint"):
            result = deepcopy(self.result)
            setattr(result, field, "changed")
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "extraction changed"),
            ):
                restore_review(document, self.paper, result)

    def test_rehashed_current_state_cannot_invent_confirmations(self):
        document = self.document()
        document["payload"]["items"][0]["status"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "current state"):
            self.restore(self.rehash(document))

    def test_event_order_before_after_and_actor_changes_rejected(self):
        self.session.confirm(self.root.candidate_id, **self.actor)
        original = self.document()
        for field, value in (
            ("sequence", 3),
            ("reviewer", ""),
            ("action", "unknown"),
            ("occurred_at", "2026-10-31T12:00:00"),
        ):
            document = deepcopy(original)
            document["payload"]["events"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.restore(self.rehash(document))
        document = deepcopy(original)
        document["payload"]["events"][0]["before"]["status"] = "rejected"
        with self.assertRaisesRegex(ValueError, "snapshots"):
            self.restore(self.rehash(document))

    def test_missing_and_orphan_dependency_events_rejected(self):
        self.decide_and_reopen()
        document = self.document()
        self.assertEqual(
            document["payload"]["events"][-1]["action"], "reopen_dependency"
        )
        document["payload"]["events"].pop()
        with self.assertRaisesRegex(ValueError, "Missing dependent"):
            self.restore(self.rehash(document))
        document = self.document()
        document["payload"]["events"] = document["payload"]["events"][-1:]
        with self.assertRaisesRegex(ValueError, "orphan"):
            self.restore(self.rehash(document))

    def test_bad_fields_offsets_paths_and_empty_evidence_rejected(self):
        original = self.document()
        for change in ("extra", "offset", "path", "empty", "status"):
            document = deepcopy(original)
            item = document["payload"]["items"][0]
            if change == "extra":
                item["unknown"] = "value"
            elif change == "offset":
                item["evidence"][0]["start"] = True
            elif change == "path":
                item["evidence"][0]["path"] = [True]
            elif change == "empty":
                item["evidence"] = []
            else:
                item["status"] = "unknown"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.restore(self.rehash(document))

    def test_new_file_load_and_revision_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "review.json"
            revision = save_review(path, self.session)
            stored = load_review(path, self.paper, self.result)
            self.assertEqual(stored.revision, revision)
            stored.session.confirm(self.root.candidate_id, **self.actor)
            updated = save_review(
                path, stored.session, expected_revision=stored.revision
            )
            self.assertNotEqual(updated, revision)
            self.assertEqual(
                load_review(path, self.paper, self.result).session.history,
                stored.session.history,
            )
            self.assertFalse(list(path.parent.glob("*.tmp")))
            self.assertFalse(list(path.parent.glob("*.lock")))

    def test_existing_stale_and_removed_archive_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            revision = save_review(path, self.session)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_review(path, self.session)
            with self.assertRaisesRegex(ValueError, "changed on disk"):
                save_review(path, self.session, expected_revision="wrong")
            self.assertEqual(path.read_bytes(), original)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "removed"):
                save_review(path, self.session, expected_revision=revision)
            self.assertFalse(path.exists())
            self.assertFalse(list(path.parent.glob("*.lock")))

    def test_failed_atomic_replace_keeps_existing_file_and_cleans_own_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            revision = save_review(path, self.session)
            original = path.read_bytes()
            self.session.confirm(self.root.candidate_id, **self.actor)
            with patch(
                "src.knowledge_builder.review_storage.os.replace",
                side_effect=OSError("test write failure"),
            ):
                with self.assertRaises(OSError):
                    save_review(path, self.session, expected_revision=revision)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_existing_lock_is_not_removed_or_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            lock = path.with_name(path.name + ".lock")
            lock.write_text("other writer", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                save_review(path, self.session)
            self.assertEqual(lock.read_text(encoding="utf-8"), "other writer")
            self.assertFalse(path.exists())

    def test_invalid_json_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_review(path, self.paper, self.result)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_cli_saves_and_resumes_test_decisions_only_in_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            command = [
                sys.executable,
                "-m",
                "scripts.knowledge_builder.review",
                "--reviewer",
                "program-test",
                "--archive",
                str(path),
            ]
            first = subprocess.run(
                command,
                cwd=ROOT,
                input="confirm 1\nProgram test only\nquit\n",
                text=True,
                capture_output=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("confirmed: entities=1", first.stdout)
            second = subprocess.run(
                command,
                cwd=ROOT,
                input="summary\nhistory\nquit\n",
                text=True,
                capture_output=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("confirmed: entities=1", second.stdout)
            self.assertIn("Program test only", second.stdout)
            self.assertEqual(
                len(json.loads(path.read_text(encoding="utf-8"))["payload"]["events"]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
