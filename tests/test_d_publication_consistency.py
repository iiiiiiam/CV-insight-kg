"""D acceptance: real B feedback and effective export, simulated C storage."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.c_gateway import CServiceClient
from server.configuration.settings import Settings
from src.graph_query.effective import project
from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.review import ReviewSession


def test_feedback_publication_keeps_open_research_on_its_original_batch(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    paper = next(p for p in load_openalex_sample(root / "examples/week1_baseline.json")
                 if "YOLO-World:" in p.title)
    result = extract_candidates(paper, load_vocabulary())
    snapshot = SimpleNamespace(
        papers=[paper], results={paper.openalex_id: result}, review_directory=tmp_path,
        sessions={paper.openalex_id: ReviewSession(paper, result)},
    )
    monkeypatch.setattr("server.api.main.KnowledgeSnapshot", lambda **_: snapshot)
    monkeypatch.setattr("server.api.knowledge_feedback.KnowledgeSnapshot", lambda **_: snapshot)

    batches = {}
    active = None
    reject_publish = False
    attempts = []

    async def request(_self, method, path, *, params=None, body=None, **_):
        nonlocal active
        if path == "/api/admin/graph/effective":
            batch = "effective-" + body["revision"]
            nodes, edges = project(body)
            batches[batch] = {"nodes": nodes, "edges": edges, "status": "ready"}
            return httpx.Response(200, json={"id": batch, "replay": False})
        if path.startswith("/api/admin/batches/"):
            batch = path.split("/")[4]
            if batch not in batches:
                return httpx.Response(404)
            if method == "POST":
                assert body["expected_active_batch_id"] == active
                attempts.append(batch)
                if reject_publish:
                    return httpx.Response(409, json={"error": {
                        "code": "TEST_PUBLISH_BLOCKED", "message": "Simulated failure",
                    }})
                previous, active = active, batch
                batches[batch]["status"] = "published"
                return httpx.Response(200, json={
                    "batch_id": batch, "previous_batch_id": previous, "status": "published",
                })
            return httpx.Response(200, json={
                "id": batch, "provenance": "effective_export", "source_batch_id": batch,
                "status": batches[batch]["status"], "publishable": True, "active_batch_id": active,
            })
        filters = dict(params or ())
        batch = filters.get("batch_id") or active
        assert batch is not None
        data = batches[batch]
        method_edges = [edge for edge in data["edges"] if edge["kind"] == "mentions_method"]
        edges = [dict(edge, evidence=json.loads(edge["evidence_json"])) for edge in data["edges"]]
        papers = [node for node in data["nodes"] if node["kind"] == "paper"]
        if path == "/api/research/statistics":
            value = {"method_count": sum(edge["target"] == method_id for edge in method_edges)}
        elif path == "/api/research/papers":
            value = {"total": sum(edge["target"] == filters["method"] for edge in method_edges)}
        elif path.startswith("/api/research/papers/"):
            value = {"node": papers[0], "relations": edges}
        elif path == "/api/research/graph":
            value = {"nodes": data["nodes"], "edges": edges}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json={**value, "batch_id": batch})

    monkeypatch.setattr(CServiceClient, "request", request)
    settings = Settings(username="test-admin", password="isolated-test-password", secret="s" * 48,
                        graph_sync_interval_seconds=0.05)
    with TestClient(create_app(settings)) as client:
        def read(path, params=None):
            response = client.get(path, params=params)
            assert response.status_code == 200, response.text
            return response.json()

        def wait_for(predicate):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = read("/api/health")["graph_sync"]
                if predicate(state):
                    return state
                time.sleep(0.02)
            raise AssertionError(state)

        first = wait_for(lambda state: state["state"] == "synced")["batch_id"]
        view = read("/api/knowledge/paper", {"paper_id": paper.openalex_id})
        relation = next(item for item in view["relations"] if item["content"]["kind"] == "mentions_method")
        method_id = relation["content"]["target"]
        paper_id = relation["content"]["source"]
        detail_path = "/api/research/papers/" + paper_id
        assert read("/api/research/statistics")["batch_id"] == first
        before = (
            read("/api/research/statistics", {"batch_id": first}),
            read("/api/research/papers", {"batch_id": first, "method": method_id}),
            read(detail_path, {"batch_id": first}),
            read("/api/research/graph", {"batch_id": first, "seed": paper_id, "hops": 2}),
        )
        assert before[0]["method_count"] == before[1]["total"] == 1
        assert any(edge["target"] == method_id and edge["evidence"] for edge in before[2]["relations"])
        assert any(edge["target"] == method_id for edge in before[3]["edges"])

        report = client.post("/api/knowledge/feedback", json={
            "paper_id": paper.openalex_id, "revision": view["revision"],
            "candidate_id": relation["candidate_id"], "message": "Test removal",
        })
        assert report.status_code == 201, report.text
        login = client.post("/api/admin/sessions", json={
            "username": settings.username, "password": settings.password,
        })
        assert login.status_code == 200, login.text
        queue = read("/api/admin/knowledge/feedback")
        reject_publish = True
        resolved = client.post("/api/admin/knowledge/feedback/" + report.json()["id"],
                               headers={"X-CSRF-Token": login.json()["csrf_token"]},
                               json={"revision": queue["revision"], "action": "exclude", "reason": "Test"})
        assert resolved.status_code == 200, resolved.text
        failed = wait_for(lambda state: (state["error"] or {}).get("code") == "TEST_PUBLISH_BLOCKED")
        second = failed["batch_id"]
        assert second != first
        assert read("/api/research/statistics")["batch_id"] == first

        reject_publish = False
        wait_for(lambda state: state["state"] == "synced" and state["batch_id"] == second)
        assert attempts.count(second) >= 2
        latest = read("/api/research/statistics")
        assert latest["batch_id"] == second and latest["method_count"] == 0
        assert read("/api/research/papers", {"batch_id": second, "method": method_id})["total"] == 0
        assert all(edge["target"] != method_id for edge in read(detail_path, {"batch_id": second})["relations"])
        assert all(edge["target"] != method_id for edge in read(
            "/api/research/graph", {"batch_id": second, "seed": paper_id, "hops": 2},
        )["edges"])
        assert before == (
            read("/api/research/statistics", {"batch_id": first}),
            read("/api/research/papers", {"batch_id": first, "method": method_id}),
            read(detail_path, {"batch_id": first}),
            read("/api/research/graph", {"batch_id": first, "seed": paper_id, "hops": 2}),
        )
