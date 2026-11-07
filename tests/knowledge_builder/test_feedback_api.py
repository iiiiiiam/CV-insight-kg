"""Real FastAPI/session/CSRF checks, isolated from A/C services and real files."""

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SERVER_READY = all(find_spec(module) is not None for module in
                   ("fastapi", "httpx", "pwdlib", "argon2", "itsdangerous"))
if SERVER_READY:
    from fastapi.testclient import TestClient
    from server.api.main import create_app
    from server.configuration.settings import Settings
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.review import ReviewSession

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(SERVER_READY, "Integrated server dependencies not installed")
class FeedbackAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paper = next(p for p in load_openalex_sample(ROOT / "examples/week1_baseline.json")
                         if "YOLO-World:" in p.title)

    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store_path = directory / "_feedback/state.json"
        result = extract_candidates(self.paper, load_vocabulary())
        snapshot = SimpleNamespace(papers=[self.paper], results={self.paper.openalex_id: result},
            sessions={self.paper.openalex_id: ReviewSession(self.paper, result)}, review_directory=directory)
        self.enterContext(patch("server.api.knowledge_feedback.KnowledgeSnapshot", return_value=snapshot))
        self.settings = Settings(username="feedback-test", password="isolated-test-password", secret="s" * 48,
                                 origins=("http://testserver",))
        self.client = self.enterContext(TestClient(create_app(self.settings)))

    def reading(self):
        r = self.client.get("/api/knowledge/paper", params={"paper_id": self.paper.openalex_id})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def submit(self, **extra):
        view = self.reading()
        item = next(i for i in view["entities"] if i["content"]["name"] == "LVIS")
        return self.client.post("/api/knowledge/feedback", json=dict(paper_id=self.paper.openalex_id,
            revision=view["revision"], candidate_id=item["candidate_id"], message="API test feedback", **extra))

    def login(self):
        result = self.client.post("/api/admin/sessions", json={"username":self.settings.username,
                                                              "password":self.settings.password})
        self.assertEqual(result.status_code, 200)
        return {"X-CSRF-Token":result.json()["csrf_token"]}

    def test_public_view_report_and_minimal_status_without_admin_history(self):
        self.assertEqual(self.client.get("/api/knowledge/papers").status_code, 200)
        self.assertNotIn("status", str(self.reading()))
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        identifier = response.json()["id"]
        status = self.client.get("/api/knowledge/feedback/" + identifier)
        self.assertEqual(set(status.json()), {"id", "status", "updated_at"})
        self.assertEqual(self.client.get("/api/admin/knowledge/feedback").status_code, 401)

    def test_authenticated_resolution_requires_csrf_and_rejects_spoofed_identity(self):
        identifier = self.submit().json()["id"]
        headers = self.login()
        queue = self.client.get("/api/admin/knowledge/feedback").json()
        body = dict(revision=queue["revision"], action="rename", reason="API test", name="LVIS revised")
        path = "/api/admin/knowledge/feedback/" + identifier
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        self.assertEqual(self.client.post(path, json={**body, "reviewer":"fake"}, headers=headers).status_code, 422)
        self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, 200)
        self.assertTrue(any(i["content"]["name"] == "LVIS revised" for i in self.reading()["entities"]))
        queue = self.client.get("/api/admin/knowledge/feedback").json()
        self.assertEqual(queue["requests"][0]["resolution"]["reviewer"], self.settings.username)
        self.assertNotIn(self.settings.username, str(self.reading()))
        self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, 409)

    def test_public_submission_validates_origin_fields_and_snapshot(self):
        view = self.reading()
        body = dict(paper_id=self.paper.openalex_id, revision=view["revision"], term="RepVL-PAN", message="test")
        self.assertEqual(self.client.post("/api/knowledge/feedback", json=body,
            headers={"Origin":"https://outside.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/knowledge/feedback", json={**body,"reviewer":"fake"}).status_code, 422)
        self.assertEqual(self.client.post("/api/knowledge/feedback", json={**body,"revision":"0"*64}).status_code, 409)
        self.assertFalse(self.store_path.exists())
        self.assertEqual(self.client.post("/api/knowledge/feedback", json=body).status_code, 201)

    def test_corrupt_storage_is_unavailable_not_empty_or_overwritten(self):
        self.submit()
        self.store_path.write_text("broken-json",encoding="utf-8")
        response = self.client.get("/api/knowledge/paper", params={"paper_id":self.paper.openalex_id})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.store_path.read_text(encoding="utf-8"),"broken-json")

    def test_withdrawal_requires_owner_token_and_is_reflected_in_admin_queue(self):
        token = "a" * 64
        identifier = self.submit(owner_token=token).json()["id"]
        path = "/api/knowledge/feedback/" + identifier + "/withdraw"
        self.assertEqual(self.client.post(path, json={}).status_code, 422)
        self.assertEqual(self.client.post(path, json={"owner_token":"b" * 64}).status_code, 404)
        self.assertEqual(self.client.post(path, json={"owner_token":token},
            headers={"Origin":"https://outside.example"}).status_code, 403)
        self.assertEqual(self.client.post(path, json={"owner_token":token}).status_code, 200)
        self.assertEqual(self.client.post(path, json={"owner_token":token}).status_code, 200)
        self.assertEqual(self.client.get("/api/knowledge/feedback/" + identifier).json()["status"], "withdrawn")
        headers = self.login()
        queue = self.client.get("/api/admin/knowledge/feedback").json()
        self.assertNotIn("withdrawn", queue["counts"])
        self.assertEqual(queue["counts"]["open"], 0)
        self.assertEqual(queue["requests"], [])
        self.assertEqual(self.client.post("/api/admin/knowledge/feedback/" + identifier,
            json=dict(revision=queue["revision"], action="exclude", reason="test"), headers=headers).status_code, 409)

    def test_admin_reopen_is_authenticated_revision_bound_and_returns_to_open(self):
        before = self.reading()
        identifier = self.submit(owner_token="a" * 64).json()["id"]
        path = "/api/admin/knowledge/feedback/" + identifier
        self.assertEqual(self.client.post(path + "/reopen", json={"revision":0}).status_code, 401)
        headers = self.login()
        revision = self.client.get("/api/admin/knowledge/feedback").json()["revision"]
        self.assertEqual(self.client.post(path, headers=headers,
            json=dict(revision=revision, action="rename", reason="test", name="LVIS revised")).status_code, 200)
        revision = self.client.get("/api/admin/knowledge/feedback").json()["revision"]
        self.assertEqual(self.client.post(path + "/reopen", json={"revision":revision}).status_code, 403)
        self.assertEqual(self.client.post(path + "/reopen", headers=headers,
            json={"revision":0}).status_code, 409)
        self.assertEqual(self.client.post(path + "/reopen", headers=headers,
            json={"revision":revision,"reviewer":"fake"}).status_code, 422)
        self.assertEqual(self.client.post(path + "/reopen", headers=headers,
            json={"revision":revision}).status_code, 200)
        self.assertEqual(self.reading(), before)
        queue = self.client.get("/api/admin/knowledge/feedback").json()
        self.assertEqual(queue["requests"][0]["status"], "open")
        self.assertIsNone(queue["requests"][0]["resolution"])
        self.assertEqual(queue["requests"][0]["processing_history"][0]["reopened_by"], self.settings.username)
        self.assertEqual(self.client.post("/api/knowledge/feedback/" + identifier + "/withdraw",
            json={"owner_token":"a" * 64}).status_code, 200)
        queue = self.client.get("/api/admin/knowledge/feedback").json()
        self.assertEqual(self.client.post(path + "/reopen", headers=headers,
            json={"revision":queue["revision"]}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
