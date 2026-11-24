"""Temporary ledgers exercise batch ownership, rollback, retries and export."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from src.knowledge_builder.batches import BatchRegistry, BatchConflict, BatchStoreInvalid
from src.knowledge_builder.extraction import fingerprint
from src.knowledge_builder.models import PaperInput


def paper(identifier, *, title="Image Segmentation", dataset="source-one"):
    return asdict(PaperInput(f"https://openalex.org/W{identifier}", title, "We evaluate COCO.",
                            2024, "CVPR", [], f"https://openalex.org/W{identifier}", dataset))


def batch(number, *items, excluded=None):
    excluded = excluded or []
    return dict(format_version="a-paperinput/1", batch_id=number, batch_code=f"BATCH-{number:06d}",
        dataset_id=f"dataset-{number}", total_papers=len(items)+len(excluded), exported_papers=len(items),
        excluded_papers=len(excluded), items=list(items), excluded=excluded)


class BatchRegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.registry = BatchRegistry(self.directory / "ledger.json")

    def inputs(self):
        return {p["input"]["openalex_id"]: p["input"] for p in self.registry.snapshot()["papers"]}

    def test_two_batches_deduplicate_and_withdraw_only_exclusive_papers(self):
        self.registry.ingest(batch(1, paper(1), paper(2)))
        result = self.registry.ingest(batch(2, paper(2, dataset="source-two"), paper(3)))
        self.assertEqual((result["new"], result["duplicates"], result["updated"]), (1, 1, 0))
        self.assertEqual(len(self.inputs()), 3)
        shared = next(p for p in self.registry.snapshot()["papers"] if p["input"]["openalex_id"].endswith("W2"))
        self.assertEqual(len(shared["providers"]), 2)
        result = self.registry.withdraw("BATCH-000002")
        self.assertEqual((result["removed"], result["retained"], result["restored"]), (1, 1, 0))
        self.assertEqual(set(self.inputs()), {"https://openalex.org/W1", "https://openalex.org/W2"})

    def test_new_content_wins_then_withdraw_restores_previous_and_original_history(self):
        self.registry.ingest(batch(99, paper(1)))
        previous = deepcopy(self.inputs())
        result = self.registry.ingest(batch(2, paper(1, title="Object Detection")))
        self.assertEqual(result["updated"], 1)
        self.assertEqual(next(iter(self.inputs().values()))["title"], "Object Detection")
        result = self.registry.withdraw("BATCH-000002")
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.inputs(), previous)
        self.assertEqual(self.registry.read()["batches"][1]["document"]["items"][0]["title"], "Object Detection")

    def test_duplicate_dataset_only_preserves_effective_input_and_original_sources(self):
        original = batch(1, paper(1))
        frozen = deepcopy(original)
        self.registry.ingest(original)
        before = self.inputs()
        self.registry.ingest(batch(2, paper(1, dataset="different-dataset")))
        self.registry.withdraw("BATCH-000001")
        self.assertEqual(self.inputs(), before)
        self.assertEqual(original, frozen)
        self.assertEqual(next(iter(before.values()))["dataset_id"], "b-paper:W1")

    def test_same_successful_batch_and_repeated_withdraw_are_idempotent(self):
        source = batch(1, paper(1))
        self.registry.ingest(source)
        body = self.registry.path.read_bytes()
        self.assertEqual(self.registry.ingest(source)["status"], "unchanged")
        self.assertEqual(self.registry.path.read_bytes(), body)
        self.registry.withdraw("BATCH-000001")
        body = self.registry.path.read_bytes()
        self.registry.withdraw("BATCH-000001")
        self.assertEqual(self.registry.ingest(source)["status"], "withdrawn")
        self.assertEqual(self.registry.path.read_bytes(), body)
        self.assertEqual(self.registry.snapshot()["paper_count"], 0)

    def test_successful_identity_conflict_never_overwrites(self):
        self.registry.ingest(batch(1, paper(1)))
        before = self.registry.path.read_bytes()
        for changed in (batch(1, paper(2)), {**batch(2, paper(2)), "batch_code": "BATCH-000001"}):
            with self.assertRaises(BatchConflict):
                self.registry.ingest(changed)
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_failure_is_atomic_and_corrected_same_batch_can_retry(self):
        self.registry.ingest(batch(1, paper(1)))
        snapshot = self.registry.snapshot()
        bad = paper(3)
        bad["abstract"] = None
        result = self.registry.ingest(batch(2, paper(2), bad))
        self.assertEqual((result["accepted"], result["failed"], result["not_applied"]), (0, 1, 1))
        self.assertEqual(self.registry.snapshot(), snapshot)
        self.assertEqual(self.registry.read()["events"][-1]["action"], "ingest_failed")
        self.assertEqual(self.registry.ingest(batch(2, paper(2), paper(3)))["status"], "accepted")
        self.assertEqual(len(self.inputs()), 3)

    def test_batch_internal_duplicates_counted_but_conflicting_versions_rejected(self):
        result = self.registry.ingest(batch(1, paper(1), paper(1, dataset="other")))
        self.assertEqual((result["accepted"], result["duplicates"]), (1, 1))
        before = self.registry.snapshot()
        result = self.registry.ingest(batch(2, paper(2), paper(2, title="Changed")))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.registry.snapshot(), before)

    def test_counts_and_upstream_excluded_are_not_silently_accepted(self):
        source = batch(1, paper(1), excluded=[dict(reason="missing abstract")])
        source["total_papers"] = 99
        self.assertEqual(self.registry.ingest(source)["status"], "failed")
        source["total_papers"] = 2
        result = self.registry.ingest(source)
        self.assertEqual((result["accepted"], result["upstream_excluded"]), (1, 1))

    def test_unknown_withdraw_is_read_only(self):
        with self.assertRaises(LookupError):
            self.registry.withdraw("unknown")
        self.assertFalse(self.registry.path.exists())

    def test_corrupt_or_semantically_invalid_store_is_not_treated_as_empty(self):
        self.registry.ingest(batch(1, paper(1)))
        document = json.loads(self.registry.path.read_text(encoding="utf-8"))
        document["payload"]["batches"][0]["papers"][0]["title"] = "Tampered"
        document["sha256"] = fingerprint(document["payload"])
        self.registry.path.write_text(json.dumps(document), encoding="utf-8")
        before = self.registry.path.read_bytes()
        with self.assertRaises(BatchStoreInvalid):
            self.registry.ingest(batch(2, paper(2)))
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_lock_and_atomic_write_failure_preserve_previous_file(self):
        self.registry.ingest(batch(1, paper(1)))
        before = self.registry.path.read_bytes()
        lock = self.registry.path.with_suffix(".json.lock")
        lock.write_text("busy")
        with self.assertRaises(BatchConflict):
            self.registry.ingest(batch(2, paper(2)))
        lock.unlink()
        with patch("src.knowledge_builder.batches.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.registry.ingest(batch(2, paper(2)))
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.assertFalse(lock.exists())
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_current_effective_export_uses_existing_c_contract_without_database(self):
        from src.graph_query.effective import project, validate_effective
        self.registry.ingest(batch(1, paper(1), paper(2)))
        self.registry.ingest(batch(2, paper(2), paper(3)))
        feedback = self.directory / "isolated-feedback.json"
        first = self.registry.workspace(feedback).export_effective()
        validate_effective(first)
        self.assertEqual(first["counts"]["papers"], 3)
        project(first)
        self.registry.withdraw("BATCH-000002")
        second = self.registry.workspace(feedback).export_effective()
        validate_effective(second)
        self.assertEqual(second["counts"]["papers"], 2)
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertFalse(feedback.exists())

    def test_empty_registry_and_last_batch_withdraw_have_explicit_empty_snapshot(self):
        self.assertEqual(self.registry.snapshot()["paper_count"], 0)
        self.assertFalse(self.registry.path.exists())
        self.registry.ingest(batch(1, paper(1)))
        self.registry.withdraw("BATCH-000001")
        exported = self.registry.workspace(self.directory/"feedback.json").export_effective()
        self.assertEqual(exported["counts"]["papers"], 0)

    def test_duplicate_membership_changes_input_snapshot_not_effective_content(self):
        feedback = self.directory / "feedback.json"
        self.registry.ingest(batch(1, paper(1)))
        before_input = self.registry.snapshot()["revision"]
        before_knowledge = self.registry.workspace(feedback).export_effective()["revision"]
        self.registry.ingest(batch(2, paper(1, dataset="new-source")))
        self.assertNotEqual(self.registry.snapshot()["revision"], before_input)
        self.assertEqual(self.registry.workspace(feedback).export_effective()["revision"], before_knowledge)

    def test_feedback_is_not_applied_to_changed_input_but_returns_after_restoring_it(self):
        feedback = self.directory / "feedback.json"
        self.registry.ingest(batch(1, paper(1)))
        workspace = self.registry.workspace(feedback)
        pid = "https://openalex.org/W1"
        public = workspace.view(pid)
        item = next(i for i in public["entities"] if i["content"]["kind"] == "dataset")
        request = workspace.submit(pid, public["revision"], "test", candidate_id=item["candidate_id"], owner_token="a"*64)
        workspace.resolve(request["id"], revision=workspace.queue()["revision"], action="rename",
                          name="COCO corrected", reason="test", reviewer="test")
        self.registry.ingest(batch(2, paper(1, title="Updated Object Detection")))
        changed = self.registry.workspace(feedback).view(pid)
        self.assertNotIn("COCO corrected", [i["content"]["name"] for i in changed["entities"]])
        self.registry.withdraw("BATCH-000002")
        restored = self.registry.workspace(feedback).view(pid)
        self.assertIn("COCO corrected", [i["content"]["name"] for i in restored["entities"]])
