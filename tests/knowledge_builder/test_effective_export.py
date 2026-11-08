"""Effective export must match reading, preserve automation and reverse corrections."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from src.knowledge_builder.effective_export import validate_effective_export, write_effective_export
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.review import ReviewSession


class EffectiveExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.vocabulary = load_vocabulary()
        self.papers = [PaperInput(f"https://openalex.org/W{i}", f"Vision paper {i}",
            "We evaluate COCO and FreshSet.", 2024, "CVPR", [], f"https://openalex.org/W{i}", "fixture") for i in (1, 2)]
        results = {p.openalex_id: extract_candidates(p, self.vocabulary) for p in self.papers}
        self.sessions = {p.openalex_id: ReviewSession(p, results[p.openalex_id]) for p in self.papers}
        self.store = FeedbackStore(self.directory / "feedback.json")
        self.workspace = KnowledgeFeedback(self.papers, results, self.sessions, self.vocabulary, self.store)
        self.pid = self.papers[0].openalex_id

    def export(self):
        return self.workspace.export_effective()

    def entries(self, document, group="entities", paper_index=0):
        return document["papers"][paper_index][group]

    def target(self):
        return next(i for i in self.workspace.view(self.pid)["entities"] if i["content"]["key"] == "dataset:term:coco")

    def submit(self):
        return self.workspace.submit(self.pid, self.workspace.view(self.pid)["revision"], "private-test-message",
            candidate_id=self.target()["candidate_id"], owner_token="a" * 64)

    def resolve(self, request, action, **extra):
        return self.workspace.resolve(request["id"], revision=self.workspace.queue()["revision"], action=action,
            reviewer="private-admin", reason="private-reason", **extra)

    def reopen(self, request):
        self.workspace.reopen(request["id"], revision=self.workspace.queue()["revision"], reviewer="private-admin")

    def test_automatic_results_match_public_reading_and_stable_revision_without_writes(self):
        document = self.export()
        self.assertEqual(document["revision"], self.export()["revision"])
        self.assertFalse(self.store.path.exists())
        for part in document["papers"]:
            public = self.workspace.view(part["input"]["openalex_id"])
            for group in ("entities", "relations"):
                self.assertEqual(json.loads(json.dumps(sorted(public[group], key=lambda i: i["candidate_id"]))),
                    [{k: v for k, v in i.items() if k != "provenance"} for i in part[group]])
                self.assertTrue(all(i["provenance"]["review_state"] == "automatic" for i in part[group]))
            self.assertEqual(part["origin"]["public_revision"], public["revision"])
        self.assertEqual(validate_effective_export(document), document)

    def test_pending_report_and_withdrawal_do_not_change_effective_revision_or_leak_private_fields(self):
        before = self.export()
        request = self.submit()
        self.assertEqual(self.export()["revision"], before["revision"])
        self.workspace.withdraw(request["id"], owner_token="a" * 64)
        self.assertEqual(self.export()["revision"], before["revision"])
        body = json.dumps(self.export())
        for private in ("private-test-message", "owner_digest", "owner_token", "private-admin", "private-reason"):
            self.assertNotIn(private, body)

    def test_public_rename_and_reopen_restore_effective_content(self):
        before = self.export()
        request = self.submit()
        self.resolve(request, "rename", name="COCO corrected")
        document = self.export()
        item = next(i for i in self.entries(document) if i["content"]["name"] == "COCO corrected")
        self.assertEqual(item["provenance"]["review_state"], "human_corrected")
        self.assertNotEqual(document["revision"], before["revision"])
        self.assertTrue(all(i["provenance"]["review_state"] == "automatic" for i in self.entries(document, "relations")))
        self.assertNotIn("private-admin", json.dumps(document))
        self.assertNotIn("private-reason", json.dumps(document))
        self.assertIn("COCO", [i["content"]["name"] for i in self.entries(document, paper_index=1)])
        self.reopen(request)
        self.assertEqual(self.export()["revision"], before["revision"])

    def test_exclusion_removes_incident_edges_and_reopen_restores_them(self):
        before = self.export()
        key = self.target()["content"]["key"]
        request = self.submit()
        self.resolve(request, "exclude")
        document = self.export()
        self.assertFalse(any(i["content"]["key"] == key for i in self.entries(document)))
        self.assertFalse(any(key in (i["content"]["source"], i["content"]["target"]) for i in self.entries(document, "relations")))
        self.reopen(request)
        self.assertEqual(self.export()["revision"], before["revision"])

    def test_added_rule_reextracts_all_papers_as_automatic_and_undo_restores_snapshot(self):
        before = self.export()
        request = self.workspace.submit(self.pid, self.workspace.view(self.pid)["revision"], "private request", term="FreshSet")
        self.resolve(request, "add_term", name="FreshSet", kind="dataset", aliases=["FreshSet"], source_url="https://example.org/freshset")
        document = self.export()
        for part in document["papers"]:
            item = next(i for i in part["entities"] if i["content"]["name"] == "FreshSet")
            self.assertEqual(item["provenance"], dict(generation="automatic", review_state="automatic", rule_adjusted=True))
            relation = next(i for i in part["relations"] if i["content"]["target"] == item["content"]["key"])
            self.assertEqual(relation["provenance"]["review_state"], "automatic")
            self.assertTrue(relation["provenance"]["rule_adjusted"])
            coco = next(i for i in part["entities"] if i["content"]["name"] == "COCO")
            self.assertFalse(coco["provenance"]["rule_adjusted"])
        self.reopen(request)
        self.assertEqual(self.export()["revision"], before["revision"])

    def test_real_legacy_confirmation_and_correction_are_separate_from_automatic_items(self):
        key = self.target()["candidate_id"]
        session = self.sessions[self.pid]
        session.confirm(key, reviewer="admin", reason="checked")
        self.assertEqual(next(i for i in self.entries(self.export()) if i["candidate_id"] == key)["provenance"]["review_state"], "human_confirmed")
        session.reopen(key, reviewer="admin", reason="recheck")
        session.correct(key, name="COCO edited", reviewer="admin", reason="corrected")
        self.assertEqual(next(i for i in self.entries(self.export()) if i["candidate_id"] == key)["provenance"]["review_state"], "human_corrected")

    def test_integrity_and_dangling_edges_rejected_even_after_recomputing_checksum(self):
        document = self.export()
        for mutate in (
            lambda d: d["papers"][0]["entities"][0]["evidence"][0].update(quote="tampered"),
            lambda d: d["papers"][0]["relations"][0]["content"].update(target="missing"),
        ):
            changed = deepcopy(document)
            mutate(changed)
            changed["revision"] = fingerprint({k: v for k, v in changed.items() if k not in ("revision", "generated_at")})
            with self.assertRaises(ValueError):
                validate_effective_export(changed)

    def test_stale_revision_and_concurrent_save_fail_without_writing_export(self):
        with self.assertRaises(FeedbackConflict):
            self.workspace.export_effective("0" * 64)
        initial = self.store.read()
        with patch.object(self.store, "read", side_effect=[initial, {**initial, "revision": 1}]):
            with self.assertRaises(FeedbackConflict):
                self.export()

    def test_file_round_trip_and_new_format_is_not_legacy_confirmed(self):
        from src.graph_query.b_adapter import adapt_confirmed
        document = self.export()
        path = self.directory / "effective.json"
        write_effective_export(document, path)
        self.assertEqual(validate_effective_export(json.loads(path.read_text(encoding="utf-8"))), document)
        with self.assertRaises(ValueError):
            adapt_confirmed(document, "test", "test")

    def test_new_rule_evidence_does_not_inherit_old_human_confirmation(self):
        key = self.target()["candidate_id"]
        self.sessions[self.pid].confirm(key, reviewer="admin", reason="checked original quote")
        request = self.workspace.submit(self.pid, self.workspace.view(self.pid)["revision"], "alias test", term="FreshSet")
        self.resolve(request, "add_term", name="COCO", kind="dataset", aliases=["FreshSet"], source_url="https://example.org/alias")
        item = next(i for i in self.entries(self.export()) if i["candidate_id"] == key)
        self.assertEqual(item["provenance"]["review_state"], "automatic")
        self.assertTrue(item["provenance"]["rule_adjusted"])
        self.assertEqual({e["quote"] for e in item["evidence"]}, {"COCO", "FreshSet"})
        self.reopen(request)
        restored = next(i for i in self.entries(self.export()) if i["candidate_id"] == key)
        self.assertEqual(restored["provenance"]["review_state"], "human_confirmed")

    def test_excluding_only_a_relation_keeps_both_entities(self):
        before = self.export()
        view = self.workspace.view(self.pid)
        target = view["relations"][0]
        request = self.workspace.submit(self.pid, view["revision"], "relation test", candidate_id=target["candidate_id"])
        self.resolve(request, "exclude")
        document = self.export()
        self.assertEqual(self.entries(document), self.entries(before))
        self.assertNotIn(target["candidate_id"], {i["candidate_id"] for i in self.entries(document, "relations")})
        self.reopen(request)
        self.assertEqual(self.export()["revision"], before["revision"])

    def test_successive_renames_undo_one_step_at_a_time(self):
        before = self.export()
        first = self.submit()
        self.resolve(first, "rename", name="COCO first")
        first_revision = self.export()["revision"]
        second = self.submit()
        self.resolve(second, "rename", name="COCO second")
        self.assertIn("COCO second", {i["content"]["name"] for i in self.entries(self.export())})
        self.reopen(second)
        self.assertEqual(self.export()["revision"], first_revision)
        self.reopen(first)
        self.assertEqual(self.export()["revision"], before["revision"])
