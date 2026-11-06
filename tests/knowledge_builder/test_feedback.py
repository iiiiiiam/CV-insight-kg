"""Feedback cases use temporary stores, never the user's real decisions."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.review import ReviewSession

ROOT = Path(__file__).resolve().parents[2]


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paper = next(p for p in load_openalex_sample(ROOT / "examples/week1_baseline.json")
                         if "YOLO-World:" in p.title)
        cls.vocabulary = load_vocabulary()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FeedbackStore(Path(self.temp.name) / "_feedback/state.json")
        self.result = extract_candidates(self.paper, self.vocabulary)
        self.session = ReviewSession(self.paper, self.result)
        self.workspace = self.make_workspace()

    def make_workspace(self, papers=None):
        papers = papers or [self.paper]
        results = {p.openalex_id: extract_candidates(p, self.vocabulary) for p in papers}
        sessions = {p.openalex_id: self.session if p == self.paper else ReviewSession(p, results[p.openalex_id]) for p in papers}
        return KnowledgeFeedback(papers, results, sessions, self.vocabulary, self.store)

    def view(self):
        return self.workspace.view(self.paper.openalex_id)

    def dataset(self):
        return next(i for i in self.view()["entities"] if i["content"]["kind"] == "dataset")

    def request_item(self):
        return self.workspace.submit(self.paper.openalex_id, self.view()["revision"],
            "程序测试：核对数据集显示", candidate_id=self.dataset()["candidate_id"])

    def process(self, request, action, **kwargs):
        return self.workspace.resolve(request["id"], revision=self.workspace.queue()["revision"],
            action=action, reason="程序测试中的处理依据", reviewer="test-admin", **kwargs)

    def test_reading_shows_automatic_knowledge_without_review_status_or_writes(self):
        view = self.view()
        self.assertEqual(len(view["entities"]), 15)
        self.assertEqual(len(view["relations"]), 18)
        self.assertNotIn("status", json.dumps(view))
        self.assertFalse(self.store.path.exists())
        self.assertTrue(all(i.status == "pending" for i in self.session.items))

    def test_report_does_not_change_reading_and_duplicate_is_idempotent(self):
        before = self.view()
        first = self.request_item()
        revision = self.store.read()["revision"]
        second = self.request_item()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.store.read()["revision"], revision)
        self.assertEqual(before, self.view())
        self.assertEqual(self.workspace.queue()["counts"]["open"], 1)

    def test_exclusion_hides_link_endpoints_without_mutating_source_or_review(self):
        original = deepcopy(self.result)
        target = self.dataset()["content"]["key"]
        request = self.request_item()
        self.process(request, "exclude")
        view = self.view()
        self.assertFalse(any(i["content"]["key"] == target for i in view["entities"]))
        self.assertFalse(any(i["content"]["target"] == target for i in view["relations"]))
        self.assertEqual(self.result, original)
        self.assertTrue(all(i.status == "pending" for i in self.session.items))
        self.assertEqual(self.make_workspace().view(self.paper.openalex_id), view)
        self.assertEqual(self.workspace.queue()["counts"], dict(open=0, resolved=1, dismissed=0))

    def test_rename_changes_display_only_and_is_preserved_after_reopen(self):
        request = self.request_item()
        original = self.dataset()
        self.process(request, "rename", name="LVIS dataset")
        renamed = next(i for i in self.view()["entities"] if i["candidate_id"] == original["candidate_id"])
        self.assertEqual(renamed["content"]["name"], "LVIS dataset")
        self.assertEqual(renamed["content"]["key"], original["content"]["key"])
        self.assertEqual(renamed["evidence"], original["evidence"])
        public_status = self.workspace.status(request["id"])
        self.assertEqual(set(public_status), {"id", "status", "updated_at"})
        self.assertNotIn("test-admin", json.dumps(self.view()))

    def test_dismiss_keeps_original_and_records_real_action(self):
        before = self.view()
        request = self.request_item()
        self.process(request, "dismiss")
        self.assertEqual(self.view(), before)
        self.assertEqual(self.workspace.queue()["counts"]["dismissed"], 1)
        self.assertEqual(self.store.read()["requests"][0]["resolution"]["reviewer"], "test-admin")

    def test_stale_queue_and_reading_requests_do_not_overwrite(self):
        request = self.request_item()
        before = self.store.path.read_bytes()
        with self.assertRaises(FeedbackConflict):
            self.workspace.resolve(request["id"], revision=0, action="exclude", reason="test", reviewer="test")
        self.assertEqual(before, self.store.path.read_bytes())
        self.process(request, "rename", name="LVIS revised")
        with self.assertRaises(FeedbackConflict):
            self.workspace.submit(self.paper.openalex_id, "0" * 64, "stale", candidate_id=self.dataset()["candidate_id"])

    def test_changed_source_blocks_correction_but_allows_explained_dismissal(self):
        request = self.request_item()
        changed = replace(self.paper, title=self.paper.title + " revised")
        result = extract_candidates(changed, self.vocabulary)
        workspace = KnowledgeFeedback([changed], {changed.openalex_id: result},
            {changed.openalex_id: ReviewSession(changed, result)}, self.vocabulary, self.store)
        with self.assertRaises(FeedbackConflict):
            workspace.resolve(request["id"], revision=self.store.read()["revision"],
                action="exclude", reason="test", reviewer="test")
        workspace.resolve(request["id"], revision=self.store.read()["revision"],
            action="dismiss", reason="原文已变化，关闭旧申请", reviewer="test")

    def test_missing_term_addition_reextracts_new_papers_without_handwritten_answers(self):
        new_paper = replace(self.paper, openalex_id="https://openalex.org/W9999999999",
                            title="RepVL-PAN for detection", abstract=None)
        self.workspace = self.make_workspace([self.paper, new_paper])
        request = self.workspace.submit(self.paper.openalex_id, self.view()["revision"],
            "程序测试：请求识别摘要中的名称", term="RepVL-PAN")
        self.process(request, "add_term", name="RepVL-PAN", kind="method",
                     aliases=["RepVL-PAN"], source_url=self.paper.source_url)
        for paper in [self.paper, new_paper]:
            view = self.workspace.view(paper.openalex_id)
            self.assertTrue(any(i["content"]["name"] == "RepVL-PAN" for i in view["entities"]))
            self.assertIn("+feedback.", view["vocabulary_version"])
        self.assertNotIn("RepVL-PAN", [t["name"] for t in self.vocabulary["terms"]])

    def test_unknown_term_and_conflicting_alias_do_not_leave_partial_decision(self):
        with self.assertRaises(ValueError):
            self.workspace.submit(self.paper.openalex_id, self.view()["revision"], "test", term="not-present-xyz")
        request = self.workspace.submit(self.paper.openalex_id, self.view()["revision"], "test", term="RepVL-PAN")
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.process(request, "add_term", name="Conflicting term", kind="method",
                         aliases=["YOLO"], source_url=self.paper.source_url)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.workspace.queue()["counts"]["open"], 1)

    def test_existing_term_new_alias_reuses_identity_instead_of_duplicate_entity(self):
        paper = replace(self.paper, title="You Only Look Once for detection", abstract=None)
        result = extract_candidates(paper, self.vocabulary)
        workspace = KnowledgeFeedback([paper], {paper.openalex_id: result},
            {paper.openalex_id: ReviewSession(paper, result)}, self.vocabulary, self.store)
        view = workspace.view(paper.openalex_id)
        request = workspace.submit(paper.openalex_id, view["revision"], "test alias", term="You Only Look Once")
        workspace.resolve(request["id"], revision=self.store.read()["revision"], action="add_term",
            reason="test alias mapping", reviewer="test-admin", name="YOLO", kind="method",
            aliases=["You Only Look Once"], source_url=paper.source_url)
        matches = [i for i in workspace.view(paper.openalex_id)["entities"] if i["content"]["name"] == "YOLO"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["content"]["key"], "method:term:yolo")

    def test_lock_and_checksum_errors_never_silently_reset_data(self):
        self.request_item()
        before = self.store.path.read_bytes()
        lock = self.store.path.with_suffix(".lock")
        lock.write_text("test", encoding="utf-8")
        with self.assertRaises(FeedbackConflict):
            self.request_item()
        self.assertTrue(lock.exists())
        lock.unlink()
        doc = json.loads(before)
        doc["payload"]["revision"] += 1
        self.store.path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.view()


if __name__ == "__main__":
    unittest.main()
