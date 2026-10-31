"""审核程序测试；自动调用确认函数不是现实中的人工论文审核。"""

import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import Entity, PaperInput
from src.knowledge_builder.review import ReviewSession


class ReviewTests(unittest.TestCase):
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
        self.task = next(c for c in self.result.entities if c.entity.kind == "task")
        self.root = next(c for c in self.result.entities if c.entity.kind == "paper")
        self.link = next(r for r in self.result.relations if r.kind == "mentions_task")
        self.actor = {"reviewer": "test-reviewer", "reason": "Program test only"}

    def confirm_link(self):
        for candidate in (self.root, self.task, self.link):
            self.session.confirm(candidate.candidate_id, **self.actor)

    def test_starts_pending_and_keeps_original_extraction(self):
        before = deepcopy(self.result)
        self.session.confirm(self.task.candidate_id, **self.actor)
        self.assertEqual(self.result, before)
        self.assertEqual(self.session.original, before)
        self.assertEqual(len(self.session.select("confirmed").entities), 1)
        self.assertTrue(
            all(c.status == "pending" for c in self.session.original.entities)
        )

    def test_confirm_relation_requires_both_confirmed_endpoints(self):
        for expected_events in (0, 1):
            with self.assertRaisesRegex(ValueError, "endpoint"):
                self.session.confirm(self.link.candidate_id, **self.actor)
            self.assertEqual(len(self.session.history), expected_events)
            if expected_events == 0:
                self.session.confirm(self.root.candidate_id, **self.actor)
        self.session.confirm(self.task.candidate_id, **self.actor)
        self.session.confirm(self.link.candidate_id, **self.actor)
        selection = self.session.select("confirmed")
        self.assertEqual(len(selection.entities), 2)
        self.assertEqual(len(selection.relations), 1)

    def test_rejection_is_separate_and_does_not_implicitly_decide_relations(self):
        self.session.reject(self.task.candidate_id, **self.actor)
        self.assertEqual(len(self.session.select("rejected").entities), 1)
        self.assertEqual(self.session.get(self.link.candidate_id).status, "pending")
        with self.assertRaisesRegex(ValueError, "endpoint"):
            self.session.confirm(self.link.candidate_id, **self.actor)
        self.assertEqual(len(self.session.history), 1)

    def test_correction_records_before_after_and_stays_pending(self):
        item = self.session.correct(
            self.task.candidate_id, name="目标检测", **self.actor
        )
        self.assertEqual(item.status, "pending")
        self.assertEqual(item.content.name, "目标检测")
        self.assertEqual(item.content.key, self.task.entity.key)
        event = self.session.history[0]
        self.assertEqual(event.before.content.name, "Object Detection")
        self.assertEqual(event.after.content.name, "目标检测")
        self.assertEqual(event.reviewer, "test-reviewer")
        self.assertTrue(event.occurred_at.endswith("+00:00"))
        self.assertEqual(self.session.original.entities, self.result.entities)
        self.session.confirm(self.task.candidate_id, **self.actor)

    def test_relation_evidence_can_be_narrowed_without_removing_entity_evidence(self):
        before = self.session.get(self.link.candidate_id)
        after = self.session.correct(
            self.link.candidate_id, evidence=before.evidence[:1], **self.actor
        )
        self.assertEqual(len(after.evidence), 1)
        self.assertEqual(len(self.session.get(self.task.candidate_id).evidence), 2)

    def test_bad_evidence_and_removed_dependent_evidence_are_atomic(self):
        before = self.session.get(self.task.candidate_id)
        bad = replace(before.evidence[0], quote="invented")
        for evidence in ((bad,), (), before.evidence[:1]):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.session.correct(
                    self.task.candidate_id, evidence=evidence, **self.actor
                )
            self.assertEqual(self.session.get(self.task.candidate_id), before)
            self.assertEqual(self.session.history, ())

    def test_decided_candidates_require_reopen(self):
        self.session.confirm(self.task.candidate_id, **self.actor)
        for operation in (
            self.session.confirm,
            self.session.reject,
            self.session.correct,
        ):
            with self.assertRaisesRegex(ValueError, "Reopen"):
                operation(self.task.candidate_id, **self.actor)
        self.session.reopen(self.task.candidate_id, **self.actor)
        self.session.reject(self.task.candidate_id, **self.actor)
        self.assertEqual(
            [e.action for e in self.session.history], ["confirm", "reopen", "reject"]
        )

    def test_reopen_entity_invalidates_confirmed_relations_with_audit_events(self):
        self.confirm_link()
        self.session.reopen(self.task.candidate_id, **self.actor)
        self.assertEqual(self.session.get(self.task.candidate_id).status, "pending")
        self.assertEqual(self.session.get(self.link.candidate_id).status, "pending")
        self.assertEqual(self.session.get(self.root.candidate_id).status, "confirmed")
        self.assertEqual(
            [e.action for e in self.session.history[-2:]],
            ["reopen", "reopen_dependency"],
        )
        self.assertEqual([e.sequence for e in self.session.history], list(range(1, 6)))
        self.assertEqual(self.session.select("confirmed").relations, ())
        self.session.reject(self.task.candidate_id, **self.actor)

    def test_reopen_relation_keeps_endpoint_decisions(self):
        self.confirm_link()
        self.session.reopen(self.link.candidate_id, **self.actor)
        self.assertEqual(len(self.session.select("confirmed").entities), 2)
        self.assertEqual(self.session.select("confirmed").relations, ())

    def test_reviewer_reason_ids_and_noop_edits_are_checked(self):
        for reviewer, reason in (("", "reason"), ("reviewer", " "), (None, "reason")):
            with self.subTest(reviewer=reviewer), self.assertRaises(ValueError):
                self.session.confirm(
                    self.task.candidate_id, reviewer=reviewer, reason=reason
                )
        for candidate_id in ("unknown", ""):
            with self.assertRaises(ValueError):
                self.session.confirm(candidate_id, **self.actor)
        with self.assertRaises(ValueError):
            self.session.correct(self.task.candidate_id, **self.actor)
        with self.assertRaises(ValueError):
            self.session.correct(self.link.candidate_id, name="Wrong", **self.actor)
        with self.assertRaises(ValueError):
            self.session.reopen(self.task.candidate_id, **self.actor)
        with self.assertRaises(ValueError):
            self.session.select("unknown")
        self.assertEqual(self.session.history, ())

    def test_external_objects_and_views_do_not_mutate_session(self):
        original_copy = self.session.original
        original_copy.entities.clear()
        self.result.entities.clear()
        self.paper.title = "changed externally"
        self.assertTrue(self.session.original.entities)
        with self.assertRaises(FrozenInstanceError):
            self.session.get(self.task.candidate_id).status = "confirmed"
        with self.assertRaisesRegex(ValueError, "Input changed"):
            self.session.check_input(self.paper)
        # 会话仍绑定最初的输入副本，外部修改不会污染当前证据。
        self.session.confirm(self.task.candidate_id, **self.actor)
        with self.assertRaises(FrozenInstanceError):
            self.session.history[0].reason = "tampered"

    def test_changed_input_rejected_when_starting_session(self):
        self.paper.year = 2025
        with self.assertRaisesRegex(ValueError, "different input"):
            ReviewSession(self.paper, self.result)

    def test_real_paper_review_flow_uses_real_evidence_without_claiming_human_review(
        self,
    ):
        root = Path(__file__).resolve().parents[2]
        paper = load_openalex_sample(root / "examples/week1_baseline.json")[0]
        result = extract_candidates(paper)
        session = ReviewSession(paper, result)
        task = next(c for c in result.entities if c.entity.kind == "task")
        link = next(r for r in result.relations if r.kind == "mentions_task")
        paper_candidate = next(c for c in result.entities if c.entity.kind == "paper")
        for candidate in (paper_candidate, task, link):
            session.confirm(candidate.candidate_id, **self.actor)
        self.assertEqual(len(session.select("confirmed").relations), 1)
        self.assertTrue(
            all(
                isinstance(i.content, Entity)
                for i in session.select("confirmed").entities
            )
        )
        self.assertEqual(
            paper.title[task.evidence[0].start : task.evidence[0].end],
            task.evidence[0].quote,
        )


if __name__ == "__main__":
    unittest.main()
