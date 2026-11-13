"""Admin batch writes and public reading/export share an isolated real ledger."""
import tempfile
import unittest
from dataclasses import asdict
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import Mock, patch

READY = all(find_spec(m) is not None for m in ("fastapi", "httpx", "pwdlib", "argon2", "itsdangerous"))
if READY:
    from fastapi.testclient import TestClient
    from server.api.main import create_app
    from server.configuration.settings import Settings
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.extraction import fingerprint
from src.knowledge_builder.enrichment_sources import SourceUnavailable


def batch(number, *ids, title="Image Segmentation"):
    items = [asdict(PaperInput(f"https://openalex.org/W{i}", title, "We evaluate COCO.",
        2024, "CVPR", [], f"https://openalex.org/W{i}", f"source-{number}")) for i in ids]
    return dict(format_version="a-paperinput/1", batch_id=number, batch_code=f"TEST-{number}",
        dataset_id=f"source-{number}", total_papers=len(items), exported_papers=len(items),
        excluded_papers=0, items=items, excluded=[])


@unittest.skipUnless(READY, "Server dependencies not installed")
class BatchAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings(username="batch-test", password="isolated-password", secret="s"*48,
            auto_graph_sync=False, b_source_offline=True, b_source_cache=str(self.directory/"cache"), b_batch_registry=str(self.directory/"ledger.json"))
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        self.path = "/api/admin/knowledge/batches"

    def login(self):
        response = self.client.post("/api/admin/sessions", json=dict(username=self.settings.username,
                                                                   password=self.settings.password))
        self.assertEqual(response.status_code, 200)
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def ingest(self, document, revision, headers):
        return self.client.post(self.path, json=dict(document=document, revision=revision,
            acknowledge_switch=True), headers=headers)

    def export(self):
        response = self.client.get("/api/admin/knowledge/effective-export")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_auth_csrf_and_explicit_switch(self):
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.ingest(batch(1, 1), 0, {}).status_code, 401)
        headers = self.login()
        self.assertEqual(self.ingest(batch(1, 1), 0, {}).status_code, 403)
        self.assertEqual(self.client.post(self.path, json=dict(document=batch(1, 1), revision=0), headers=headers).status_code, 422)
        self.assertFalse((self.directory/"ledger.json").exists())

    def test_import_dedup_withdraw_updates_reading_and_export_and_empty_stays_empty(self):
        headers = self.login()
        self.assertFalse(self.client.get(self.path).json()["managed"])
        self.assertEqual(self.ingest(batch(1, 1, 2), 0, headers).json()["new"], 2)
        second = self.ingest(batch(2, 2, 3), 1, headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["duplicates"], 1)
        self.assertEqual(len(self.client.get("/api/knowledge/papers").json()), 3)
        before = self.export()
        self.assertEqual(before["counts"]["papers"], 3)
        path = self.path+"/TEST-2/withdraw"
        self.assertEqual(self.client.post(path, json={"revision":2}).status_code, 403)
        self.assertEqual(self.client.post(path, json={"revision":2}, headers=headers).json()["removed"], 1)
        self.assertEqual(self.export()["counts"]["papers"], 2)
        self.assertNotEqual(before["revision"], self.export()["revision"])
        self.assertEqual(self.client.get("/api/knowledge/paper", params={"paper_id":"https://openalex.org/W3"}).status_code, 404)
        self.client.post(self.path+"/TEST-1/withdraw", json={"revision":3}, headers=headers)
        self.assertEqual(self.client.get("/api/knowledge/papers").json(), [])
        self.assertEqual(self.export()["counts"]["papers"], 0)
        self.assertTrue(self.client.get(self.path).json()["managed"])

    def test_stale_writes_conflicts_and_invalid_batch_preserve_knowledge(self):
        headers = self.login()
        self.ingest(batch(1, 1), 0, headers)
        before = self.export()["revision"]
        self.assertEqual(self.ingest(batch(2, 2), 0, headers).status_code, 409)
        bad = batch(2, 2)
        bad["items"][0]["year"] = "invalid"
        self.assertEqual(self.ingest(bad, 1, headers).json()["status"], "failed")
        self.assertEqual(self.export()["revision"], before)
        status = self.client.get(self.path).json()
        self.assertEqual(len(status["failures"]), 1)
        self.assertEqual(self.ingest(batch(2, 2), status["revision"], headers).json()["status"], "accepted")

    def test_corrupt_registry_fails_closed(self):
        self.login()
        (self.directory/"ledger.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(self.path).status_code, 503)
        self.assertEqual(self.client.get("/api/knowledge/papers").status_code, 503)
        self.assertEqual(self.client.get("/api/admin/knowledge/effective-export").status_code, 503)

    def test_batch_content_update_then_withdraw_restores_previous(self):
        headers = self.login()
        self.ingest(batch(1, 1), 0, headers)
        before = self.export()["revision"]
        self.ingest(batch(2, 1, title="Object Detection"), 1, headers)
        self.assertEqual(self.client.get("/api/knowledge/papers").json()[0]["title"], "Object Detection")
        result = self.client.post(self.path+"/TEST-2/withdraw", json={"revision":2}, headers=headers)
        self.assertEqual(result.json()["restored"], 1)
        self.assertEqual(self.export()["revision"], before)

    def test_import_prepares_sources_and_authenticated_retry_completes_missing_source(self):
        headers = self.login()
        payload = dict(id="https://openalex.org/W1", topics=[dict(
            id="https://openalex.org/T1", display_name="Image segmentation", score=.9)])
        record = dict(source="openalex", url="https://api.openalex.org/works/W1",
            fetched_at="2026-11-13T00:00:00Z", payload=payload, digest=fingerprint(payload))
        client = Mock(openalex=Mock(return_value=record),
                      papers_with_code=Mock(side_effect=SourceUnavailable("not found")))
        with patch("src.knowledge_builder.batch_sources.SourceClient", return_value=client):
            self.assertEqual(self.ingest(batch(1, 1), 0, headers).json()["status"], "accepted")
            status = self.client.get(self.path).json()["source_enrichment"]
            self.assertEqual((status["completed"], status["with_sources"], status["partial"]), (1, 1, 1))
            self.assertFalse(status["running"])
            view = self.client.get("/api/knowledge/paper", params={"paper_id":"https://openalex.org/W1"}).json()
            self.assertEqual(view["source_enrichment"]["source_records"][0]["source"], "openalex")
            before = self.export()["revision"]
            self.assertEqual(self.client.post(self.path+"/enrich").status_code, 403)
            self.assertEqual(self.client.post(self.path+"/enrich", headers=headers).status_code, 200)
            self.assertEqual(client.openalex.call_count, 1)
            self.assertEqual(self.export()["revision"], before)
