"""Report facts and tags follow effective edges, corrections and batch lifetimes."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from src.graph_query.effective import validate_effective
from src.knowledge_builder.author_tags import build_author_tags
from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.feedback import FeedbackConflict, FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.report_knowledge import (
    build_report_knowledge, validate_report_knowledge, write_report_knowledge,
)

ROOT = Path(__file__).resolve().parents[2]


def author(name, identifier=None):
    value = dict(display_name=name)
    if identifier:
        value["id"] = identifier
    return dict(author=value, institutions=[])


def paper(number, authors=None, abstract="We evaluate COCO and use ResNet."):
    return PaperInput(f"https://openalex.org/W{number}", "Vision paper", abstract,
                      2024, "CVPR", authors or [], f"https://openalex.org/W{number}", "fixture")


def batch(number, *papers):
    return dict(format_version="a-paperinput/1", batch_id=number, batch_code=f"TEST-{number}",
                dataset_id="fixture", total_papers=len(papers), exported_papers=len(papers),
                excluded_papers=0, items=[asdict(p) for p in papers], excluded=[])


class ReportKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.vocabulary = load_vocabulary()
        self.papers = [paper(1, [author("Ada", "https://openalex.org/A1")]),
                       paper(2, [author("Ada Example", "https://openalex.org/A1")])]
        self.workspace = self.make_workspace(self.papers)

    def make_workspace(self, papers):
        results = {p.openalex_id: extract_candidates(p, self.vocabulary) for p in papers}
        return KnowledgeFeedback(papers, results, {}, self.vocabulary,
                                 FeedbackStore(self.directory / "feedback.json"))

    def report(self):
        return build_report_knowledge(self.workspace.export_effective())

    def correct(self, action, *, relation=False, **extra):
        pid = self.papers[0].openalex_id
        view = self.workspace.view(pid)
        target = next(item for item in view["relations" if relation else "entities"]
                      if item["content"]["kind"] == ("mentions_dataset" if relation else "dataset"))
        request = self.workspace.submit(pid, view["revision"], "private-message",
                                        candidate_id=target["candidate_id"], owner_token="a" * 64)
        self.workspace.resolve(request["id"], revision=self.workspace.queue()["revision"], action=action,
                               reviewer="private-reviewer", reason="private-reason", **extra)
        return request

    def test_tags_group_exact_source_identity_and_prove_full_chain(self):
        report = self.report()
        row, = report["author_tags"]["authors"]
        self.assertEqual(row["names"], ["Ada", "Ada Example"])
        tag = next(tag for tag in row["tags"] if tag["kind"] == "dataset")
        self.assertEqual(tag["supporting_paper_count"], 2)
        for support in tag["supports"]:
            self.assertEqual(set(support["witnesses"]), {"author", "authorship", "knowledge", "mention"})
            part = next(p for p in report["knowledge"]["papers"] if p["input"]["openalex_id"] == support["paper_id"])
            items = part["entities"] + part["relations"]
            self.assertTrue(all(item in items for group in support["witnesses"].values() for item in group))
        self.assertNotIn("research_direction", [tag["kind"] for tag in row["tags"]])
        validate_effective(report["knowledge"])

    def test_same_names_do_not_merge_and_unresolved_remain_paper_local(self):
        papers = [paper(1, [author("Same", "https://openalex.org/A1"), author("Same")]),
                  paper(2, [author("Same", "https://openalex.org/A2"), author("Same")])]
        report = build_report_knowledge(self.make_workspace(papers).export_effective())
        rows = report["author_tags"]["authors"]
        self.assertEqual(len(rows), 4)
        local = [row for row in rows if row["identity_state"] == "paper_local_unresolved"]
        self.assertEqual(len(local), 2)
        self.assertTrue(all(row["source_id"] is None and len(row["paper_ids"]) == 1 for row in local))
        quality = report["quality"]["identified_author_coverage"]
        self.assertEqual(quality, dict(numerator=2, denominator=4, ratio=.5))

    def test_duplicate_authorship_does_not_inflate_support_count(self):
        self.papers[0].authorships *= 2
        report = build_report_knowledge(self.make_workspace(self.papers).export_effective())
        row, = report["author_tags"]["authors"]
        self.assertTrue(all(tag["supporting_paper_count"] == 2 for tag in row["tags"]))

    def test_excluding_only_mention_edge_removes_tag_support_but_keeps_entity(self):
        self.correct("exclude", relation=True)
        report = self.report()
        row, = report["author_tags"]["authors"]
        tag = next(tag for tag in row["tags"] if tag["kind"] == "dataset")
        self.assertEqual([support["paper_id"] for support in tag["supports"]], [self.papers[1].openalex_id])
        self.assertEqual(report["quality"]["entities_by_kind"]["dataset"], 2)

    def test_rename_and_undo_change_report_and_preserve_review_provenance(self):
        before = self.report()
        request = self.correct("rename", name="COCO corrected")
        after = self.report()
        tag = next(tag for tag in after["author_tags"]["authors"][0]["tags"] if tag["kind"] == "dataset")
        self.assertEqual(tag["names"], ["COCO", "COCO corrected"])
        self.assertEqual(after["quality"]["review_states"]["human_corrected"], 1)
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertFalse(any(value in json.dumps(after) for value in ("private-message", "private-reason", "private-reviewer")))
        self.workspace.reopen(request["id"], revision=self.workspace.queue()["revision"], reviewer="test")
        self.assertEqual(self.report()["revision"], before["revision"])

    def test_timestamp_does_not_change_content_revision_or_mutate_input(self):
        document = self.workspace.export_effective()
        frozen = deepcopy(document)
        before = build_report_knowledge(document)
        self.assertEqual(document, frozen)
        document["generated_at"] = "2026-11-19T12:00:00+08:00"
        after = build_report_knowledge(document)
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["author_tags"]["revision"], after["author_tags"]["revision"])
        validate_report_knowledge(after)
        with self.assertRaises(FeedbackConflict):
            build_report_knowledge(document, expected_revision="0" * 64)

    def test_empty_report_has_explicit_zero_counts_and_null_ratios(self):
        report = build_report_knowledge(self.make_workspace([]).export_effective())
        self.assertEqual(report["scope"]["paper_ids"], [])
        self.assertEqual(report["author_tags"]["authors"], [])
        self.assertEqual(report["quality"]["counts"], dict(papers=0, entities=0, relations=0))
        self.assertIsNone(report["quality"]["evidence_coverage"]["ratio"])
        self.assertIsNone(report["quality"]["identified_author_coverage"]["ratio"])
        self.assertIsNone(report["quality"]["accuracy"]["precision"])

    def test_no_authors_no_abstract_and_unknown_external_availability(self):
        report = build_report_knowledge(self.make_workspace([paper(3, abstract=None)]).export_effective())
        self.assertEqual(report["author_tags"]["authors"], [])
        self.assertEqual(report["quality"]["papers_with_abstract"]["ratio"], 0)
        self.assertIsNone(report["quality"]["external_source_availability"]["pending"])
        self.assertEqual(report["quality"]["per_paper"][0]["missing_text_categories"], ["topic", "method", "task", "dataset"])

    def test_no_mentions_produce_explicit_empty_author_tags(self):
        report = build_report_knowledge(self.make_workspace([paper(3, [author("Ada", "source:ada")], "Plain text.")]).export_effective())
        row, = report["author_tags"]["authors"]
        self.assertEqual(row["tags"], [])

    def test_invalid_evidence_or_altered_report_never_reaches_output(self):
        report = self.report()
        output = self.directory / "report.json"
        write_report_knowledge(report, output)
        before = output.read_bytes()
        report["quality"]["accuracy"]["precision"] = 1
        with self.assertRaises(ValueError):
            write_report_knowledge(report, output)
        self.assertEqual(output.read_bytes(), before)
        report = self.report()
        report["knowledge"]["papers"][0]["entities"][0]["evidence"][0]["quote"] = "invented"
        with self.assertRaises(ValueError):
            build_author_tags(report["knowledge"])

    def test_atomic_replace_failure_preserves_previous_report_and_cleans_temp(self):
        report = self.report()
        output = self.directory / "report.json"
        output.write_text("previous", encoding="utf-8")
        before = set(self.directory.iterdir())
        with patch("src.knowledge_builder.report_knowledge.os.replace", side_effect=OSError("test")):
            with self.assertRaises(OSError):
                write_report_knowledge(report, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous")
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_offline_cli_round_trip_and_refuses_overwriting_effective(self):
        source, output = self.directory / "effective.json", self.directory / "report.json"
        source.write_text(json.dumps(self.workspace.export_effective()), encoding="utf-8")
        command = [sys.executable, "-B", "-m", "scripts.knowledge_builder.report_knowledge", "--effective", str(source)]
        result = subprocess.run(command + ["--output", str(output)], capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        validate_report_knowledge(json.loads(output.read_text(encoding="utf-8")))
        before = source.read_bytes()
        result = subprocess.run(command + ["--output", str(source)], capture_output=True, cwd=ROOT)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(source.read_bytes(), before)

    def test_real_a_files_merge_withdraw_and_empty_report_without_network(self):
        registry = BatchRegistry(self.directory / "ledger.json")
        reports = []
        for name in ("01-first-batch.json", "02-second-batch.json"):
            path = ROOT / "examples/week3_handoff" / name
            body = path.read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), path.with_suffix(".json.sha256").read_text().split()[0])
            registry.ingest(json.loads(body))
            reports.append(build_report_knowledge(registry.workspace(self.directory / "feedback.json").export_effective()))
        registry.withdraw("BATCH-000002")
        reports.append(build_report_knowledge(registry.workspace(self.directory / "feedback.json").export_effective()))
        registry.withdraw("BATCH-000001")
        reports.append(build_report_knowledge(registry.workspace(self.directory / "feedback.json").export_effective()))
        self.assertEqual([r["scope"]["paper_count"] for r in reports], [20, 30, 20, 0])
        self.assertEqual(reports[0]["revision"], reports[2]["revision"])
        self.assertEqual(reports[0]["author_tags"], reports[2]["author_tags"])
        for report in reports:
            validate_report_knowledge(report)
            validate_effective(report["knowledge"])
            paper_ids = set(report["scope"]["paper_ids"])
            self.assertTrue(all(set(row["paper_ids"]) <= paper_ids for row in report["author_tags"]["authors"]))

    def test_input_update_stops_old_correction_and_withdrawal_restores_report(self):
        registry = BatchRegistry(self.directory / "ledger.json")
        registry.ingest(batch(1, self.papers[0]))
        feedback = self.directory / "feedback.json"
        self.workspace = registry.workspace(feedback)
        self.correct("rename", name="COCO corrected")
        before = self.report()
        replacement = deepcopy(self.papers[0])
        replacement.abstract = "Updated paper about ResNet."
        registry.ingest(batch(2, replacement))
        self.workspace = registry.workspace(feedback)
        changed = self.report()
        self.assertEqual(changed["quality"]["review_states"]["human_corrected"], 0)
        self.assertFalse(any(tag["kind"] == "dataset" for tag in changed["author_tags"]["authors"][0]["tags"]))
        registry.withdraw("TEST-2")
        self.workspace = registry.workspace(feedback)
        self.assertEqual(self.report()["revision"], before["revision"])

    def test_admin_added_rule_labels_stay_automatic(self):
        self.papers[0].abstract += " We evaluate FreshSet."
        self.workspace = self.make_workspace(self.papers)
        pid = self.papers[0].openalex_id
        request = self.workspace.submit(pid, self.workspace.view(pid)["revision"], "add rule", term="FreshSet")
        self.workspace.resolve(request["id"], revision=self.workspace.queue()["revision"], action="add_term",
                               reviewer="test", reason="test", name="FreshSet", kind="dataset",
                               aliases=["FreshSet"], source_url="https://example.test/freshset")
        report = self.report()
        tag = next(tag for tag in report["author_tags"]["authors"][0]["tags"] if tag["names"] == ["FreshSet"])
        witness, = tag["supports"][0]["witnesses"]["knowledge"]
        self.assertEqual(witness["provenance"], dict(generation="automatic", review_state="automatic", rule_adjusted=True))
        self.assertEqual(report["quality"]["review_states"]["human_confirmed"], 0)
        self.assertGreater(report["quality"]["rule_adjusted_items"], 0)

    def test_external_only_classification_is_counted_but_not_turned_into_author_knowledge(self):
        before = self.report()
        pid = self.papers[0].openalex_id
        payload = dict(id=pid, topics=[dict(id="https://openalex.org/T1", display_name="Unmentioned external topic")])
        self.workspace.source_records = {pid: [dict(source="openalex", url=pid, fetched_at="2026-11-19T00:00:00Z",
                                                    payload=payload, digest=fingerprint(payload))]}
        after = self.report()
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertGreater(after["quality"]["papers_with_source_classifications"]["numerator"], 0)
        self.assertFalse(any("Unmentioned external topic" in tag["names"]
                             for row in after["author_tags"]["authors"] for tag in row["tags"]))

    def test_real_explicit_dataset_is_not_mislabeled_as_an_author_method(self):
        raw = next(item for filename in ("01-first-batch.json", "02-second-batch.json")
                   for item in json.loads((ROOT / "examples/week3_handoff" / filename).read_text(encoding="utf-8"))["items"]
                   if item["title"].startswith("OpenStreetView-5M:"))
        registry = BatchRegistry(self.directory / "ledger.json")
        registry.ingest(batch(1, PaperInput(**raw)))
        report = build_report_knowledge(registry.workspace(self.directory / "feedback.json").export_effective())
        types = {item["content"]["kind"] for item in report["knowledge"]["papers"][0]["entities"]
                 if item["content"]["name"] == "OpenStreetView-5M"}
        self.assertEqual(types, {"dataset"})
        tags = [tag for row in report["author_tags"]["authors"] for tag in row["tags"]
                if "OpenStreetView-5M" in tag["names"]]
        self.assertTrue(tags)
        self.assertTrue(all(tag["kind"] == "dataset" for tag in tags))

    def test_existing_effective_cli_honors_configured_batch_scope_and_empty_withdrawal(self):
        registry = BatchRegistry(self.directory / "configured-ledger.json")
        registry.ingest(batch(1, self.papers[0]))
        output = self.directory / "configured-effective.json"
        command = [sys.executable, "-B", "-m", "scripts.knowledge_builder.export_effective", "--output", str(output)]
        environment = dict(os.environ, B_BATCH_REGISTRY=str(registry.path), B_SOURCE_CORPUS="",
                           B_SOURCE_CACHE=str(self.directory / "cache"), B_SOURCE_OFFLINE="true",
                           B_REVIEWS_DIR=str(self.directory / "reviews"), B_VOCABULARY_PATH="")
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([p["input"]["openalex_id"] for p in document["papers"]], [self.papers[0].openalex_id])
        registry.withdraw("TEST-1")
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        empty = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(empty["counts"]["papers"], 0)
        validate_effective(empty)


if __name__ == "__main__":
    unittest.main()
