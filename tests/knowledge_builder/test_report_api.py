"""B report/tag routes, isolated sessions and concurrent-snapshot rejection."""

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import Mock, patch

from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.batch_sources import BatchSources
from src.knowledge_builder.enrichment_sources import SourceUnavailable
from src.knowledge_builder.extraction import fingerprint
from src.knowledge_builder.feedback import FeedbackConflict
from src.knowledge_builder.report_knowledge import validate_report_knowledge
from tests.knowledge_builder.test_report_knowledge import author, batch, paper

READY = all(find_spec(m) is not None for m in ("fastapi", "httpx", "pwdlib", "argon2", "itsdangerous"))
if READY:
    from fastapi.testclient import TestClient
    from server.api.main import create_app
    from server.configuration.settings import Settings
    from server.application.knowledge_reading import reading_report, reading_workspace


@unittest.skipUnless(READY, "Integrated server dependencies not installed")
class ReportAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.registry = BatchRegistry(self.directory / "ledger.json")
        self.registry.ingest(batch(1, paper(1, [author("Ada", "https://openalex.org/A1")])))
        self.settings = Settings(username="report-test", password="isolated-password", secret="s" * 48,
                                 auto_graph_sync=False, user_store=str(self.directory / "users.json"),
                                 b_batch_registry=str(self.registry.path), b_source_offline=True,
                                 b_source_cache=str(self.directory / "cache"))
        self.enterContext(patch("src.knowledge_builder.batch_sources.SourceClient", side_effect=AssertionError("Unexpected source HTTP")))
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        self.path = "/api/admin/knowledge/report-export"

    def login(self):
        response = self.client.post("/api/admin/sessions", json=dict(username=self.settings.username,
                                                                   password=self.settings.password))
        self.assertEqual(response.status_code, 200)

    def test_admin_report_public_explainable_tags_and_no_writes(self):
        before = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(self.client.get(self.path).status_code, 401)
        tags = self.client.get("/api/knowledge/author-tags")
        self.assertEqual(tags.status_code, 200, tags.text)
        self.login()
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        validate_report_knowledge(report)
        self.assertEqual(tags.json(), report["author_tags"])
        self.assertEqual(response.headers["X-Knowledge-Revision"], report["scope"]["knowledge_revision"])
        self.assertEqual(response.headers["X-Report-Revision"], report["revision"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()})

    def test_expected_revision_rejects_batch_change_and_malformed_query(self):
        self.login()
        revision = self.client.get(self.path).json()["scope"]["knowledge_revision"]
        self.registry.ingest(batch(2, paper(2, [author("Bob", "https://openalex.org/A2")])))
        for path in (self.path, "/api/knowledge/author-tags"):
            self.assertEqual(self.client.get(path, params={"expected_revision": revision}).status_code, 409)
            self.assertEqual(self.client.get(path, params={"expected_revision": "bad"}).status_code, 422)
        self.assertEqual(self.client.get(self.path).json()["scope"]["paper_count"], 2)

    def test_change_during_construction_is_detected_by_fresh_workspace(self):
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.registry.withdraw("TEST-1")
            return reading_workspace(*args, **kwargs)

        with patch("server.application.knowledge_reading.reading_workspace", side_effect=changing):
            with self.assertRaises(FeedbackConflict):
                reading_report(self.settings)
        self.assertEqual(calls, 2)

    def test_fully_withdrawn_snapshot_is_empty_and_corruption_is_not_empty_success(self):
        self.login()
        self.registry.withdraw("TEST-1")
        self.assertEqual(self.client.get(self.path).json()["scope"]["paper_count"], 0)
        self.assertEqual(self.client.get("/api/knowledge/author-tags").json()["authors"], [])
        self.registry.path.write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(self.path).status_code, 503)
        self.assertEqual(self.client.get("/api/knowledge/author-tags").status_code, 503)

    def test_exact_author_selection_does_not_match_same_name_or_unknown_identity(self):
        self.registry.ingest(batch(2, paper(2, [author("Ada", "https://openalex.org/A2")])))
        path = "/api/knowledge/author-tags"
        complete = self.client.get(path).json()
        selected = self.client.get(path, params={"source_id": "https://openalex.org/A1"}).json()
        self.assertEqual(len(complete["authors"]), 2)
        row, = selected["authors"]
        self.assertEqual(row["source_id"], "https://openalex.org/A1")
        self.assertEqual(selected["knowledge_revision"], complete["knowledge_revision"])
        self.assertEqual(selected["revision"], fingerprint({k: v for k, v in selected.items() if k != "revision"}))
        by_ref = self.client.get(path, params={"author_ref": row["author_ref"]}).json()
        self.assertEqual(by_ref["authors"], selected["authors"])
        self.assertEqual(self.client.get(path, params={"source_id": "Ada"}).json()["authors"], [])
        self.assertEqual(self.client.get(path, params={"source_id": "https://openalex.org/A2",
                                                     "author_ref": row["author_ref"]}).json()["authors"], [])

    def test_effective_download_rejects_batch_change_during_export(self):
        self.login()
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.registry.withdraw("TEST-1")
            return reading_workspace(*args, **kwargs)

        with patch("server.application.knowledge_reading.reading_workspace", side_effect=changing):
            response = self.client.get("/api/admin/knowledge/effective-export")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/admin/knowledge/effective-export").json()["counts"]["papers"], 0)

    def test_readiness_distinguishes_pending_partial_available_empty_and_unpublished(self):
        path = "/api/admin/knowledge/batches/readiness"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.login()
        before = self.client.get(path)
        self.assertEqual(before.status_code, 200, before.text)
        document = before.json()
        self.assertEqual(document["source_enrichment"]["state"], "pending")
        self.assertTrue(document["results"]["available"])
        self.assertEqual(document["publication"]["state"], "not_checked")
        self.assertEqual(document["input_mode"], "batches")
        missing = Mock(side_effect=SourceUnavailable("offline test"))
        BatchSources(self.registry.path, offline=True).prepare(
            [paper(1, [author("Ada", "https://openalex.org/A1")])],
            client=Mock(openalex=missing, papers_with_code=missing))
        partial = self.client.get(path).json()
        self.assertEqual(partial["source_enrichment"]["state"], "partial")
        self.assertEqual(partial["source_enrichment"]["partial"], 1)
        self.assertEqual(partial["knowledge_revision"], document["knowledge_revision"])
        self.registry.withdraw("TEST-1")
        self.assertEqual(self.client.get(path, params={"expected_revision": document["knowledge_revision"]}).status_code, 409)
        empty = self.client.get(path).json()
        self.assertTrue(empty["results"]["available"])
        self.assertTrue(empty["results"]["empty"])
        self.assertEqual(empty["source_enrichment"]["state"], "empty")

    def test_readiness_does_not_claim_available_for_corrupt_feedback(self):
        self.login()
        feedback = self.directory / "feedback/state.json"
        feedback.parent.mkdir()
        feedback.write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get("/api/admin/knowledge/batches/readiness").status_code, 503)

    def test_readiness_complete_sources_and_interrupted_retry_are_separate_from_results(self):
        self.login()
        path = "/api/admin/knowledge/batches/readiness"
        records = {}
        for source, payload in (
            ("openalex", dict(id="https://openalex.org/W1", topics=[], keywords=[])),
            ("paperswithcode", dict(title="Vision paper", authors=["Ada"], published="2024-01-01",
                                    tasks=[], methods=[], datasets=[])),
        ):
            records[source] = dict(source=source, payload=payload, digest=fingerprint(payload),
                                   url="https://example.test/" + source, fetched_at="2026-11-19T00:00:00Z")
        BatchSources(self.registry.path, offline=True).prepare(
            [paper(1, [author("Ada", "https://openalex.org/A1")])],
            client=Mock(openalex=Mock(return_value=records["openalex"]),
                        papers_with_code=Mock(return_value=records["paperswithcode"])))
        complete = self.client.get(path).json()
        self.assertEqual(complete["source_enrichment"]["state"], "complete")
        self.assertEqual(complete["source_enrichment"]["with_sources"], 1)
        login = self.client.get("/api/admin/session").json()
        headers = {"X-CSRF-Token": login["csrf_token"]}
        with patch("src.knowledge_builder.batch_sources.BatchSources.prepare", side_effect=OSError("test interruption")):
            with self.assertLogs("server.api.knowledge_batches", level="ERROR"):
                self.assertEqual(self.client.post("/api/admin/knowledge/batches/enrich", headers=headers).status_code, 200)
        interrupted = self.client.get(path).json()
        self.assertEqual(interrupted["source_enrichment"]["state"], "interrupted")
        self.assertTrue(interrupted["results"]["available"])
        with patch("src.knowledge_builder.batch_sources.BatchSources.prepare", return_value={}):
            self.assertEqual(self.client.post("/api/admin/knowledge/batches/enrich", headers=headers).status_code, 200)
        self.assertEqual(self.client.get(path).json()["source_enrichment"]["state"], "complete")


if __name__ == "__main__":
    unittest.main()
