import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, db_session
from app.db import seed_sources
from app.ingest import upsert_paper
from app.models import Base, Job, Paper, PaperBatch
from app.datasets import DATASET_ID, sample_directory


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        with self.Session() as db:
            paper = upsert_paper(db, {
                "source_id": "https://openalex.org/W123", "title": "DETR, Object Detection",
                "year": 2024, "venue": "CVPR", "doi": "10.1000/example",
                "authors": ["作者甲", "Alice Example"], "abstract": "Object detection evidence.\nSecond line.",
                "source_url": "https://openalex.org/W123", "raw": {"id": "W123"}}, "openalex")
            self.paper_id = paper.id
            upsert_paper(db, {"source_id": "https://openalex.org/W124", "title": "Image Classification",
                             "year": 2024, "venue": "CVPR", "authors": [], "source_url": "https://openalex.org/W124"}, "openalex")
            db.commit()

        def session_override():
            with self.Session() as db:
                yield db

        app.dependency_overrides[db_session] = session_override
        self.token_patch = patch.dict(os.environ, {"ADMIN_TOKEN": "test-token", "LOCAL_DEMO": "0"})
        self.token_patch.start()
        self.seed_patch = patch("app.api.seed_sources", lambda: seed_sources(self.Session))
        self.seed_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.auth = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        app.dependency_overrides.clear()
        self.seed_patch.stop()
        self.token_patch.stop()
        self.engine.dispose()

    def test_pagination_search_and_literal_wildcards(self):
        response = self.client.get("/api/papers", params={"q": "OBJECT DETECTION", "venue": "cvpr"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["id"], self.paper_id)
        second_page = self.client.get("/api/papers", params={"page": 2, "page_size": 1}).json()
        self.assertEqual(second_page["total"], 2)
        self.assertEqual(len(second_page["items"]), 1)
        self.assertNotEqual(second_page["items"][0]["id"], self.paper_id)
        self.assertEqual(self.client.get("/api/papers", params={"q": "%"}).json()["total"], 0)
        self.assertEqual(self.client.get("/api/papers?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/papers?venue=unknown").status_code, 422)

    def test_preview_page_is_available_without_an_admin_token(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("论文数据开发预览", response.text)
        self.assertIn('href="/admin"', response.text)

    def test_local_demo_can_import_without_manual_credentials(self):
        with patch.dict(os.environ, {"LOCAL_DEMO": "1"}):
            with TestClient(app, client=("127.0.0.1", 50000)) as local:
                self.assertTrue(local.get('/api/runtime').json()['local_demo'])
                response = local.post('/api/admin/imports', json={"dataset_id": DATASET_ID})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()['paper_count'], 20)
                self.assertNotIn('id="token"', local.get('/admin').text)
            with TestClient(app, client=("192.0.2.1", 50000)) as remote:
                self.assertFalse(remote.get('/api/runtime').json()['local_demo'])
                self.assertEqual(remote.post('/api/admin/imports', json={"dataset_id": DATASET_ID}).status_code, 401)

    def test_detail_keeps_provenance_and_graph_has_valid_endpoints(self):
        detail = self.client.get(f"/api/papers/{self.paper_id}").json()
        self.assertEqual(detail["authors"], ["作者甲", "Alice Example"])
        self.assertIn("evidence", detail["abstract"])
        self.assertEqual(detail["sources"][0]["name"], "openalex")
        self.assertEqual(detail["annotations"], [])
        graph = self.client.get(f"/api/papers/{self.paper_id}/graph").json()
        nodes = {node["id"] for node in graph["nodes"]}
        self.assertEqual(graph["basis"], "paper_metadata")
        for edge in graph["edges"]:
            self.assertIn(edge["source"], nodes)
            self.assertIn(edge["target"], nodes)
        self.assertEqual(self.client.get("/api/papers/9999").status_code, 404)

    def test_csv_export_requires_token_and_preserves_paper_keys(self):
        self.assertEqual(self.client.get("/api/admin/export").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/export", headers={"Authorization": "Bearer wrong"}).status_code, 403)
        response = self.client.get("/api/admin/export?venue=CVPR&year=2024", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["paper_id"], str(self.paper_id))
        self.assertEqual(rows[0]["title"], "DETR, Object Detection")
        self.assertIn("\nSecond line.", rows[0]["abstract"])
        self.assertIn("作者甲", rows[0]["authors_json"])

    def test_api_initializes_sources_and_retries_failed_jobs(self):
        sources = self.client.get("/api/admin/sources", headers=self.auth).json()
        self.assertEqual({s["name"] for s in sources}, {"dblp", "openalex", "ecva"})
        payload = {"venue": "CVPR", "year": 2024, "source": "openalex"}
        response = self.client.post("/api/admin/jobs", headers=self.auth, json=payload)
        self.assertEqual(response.status_code, 201)
        job_id = response.json()["id"]
        self.assertEqual(self.client.post("/api/admin/jobs", headers=self.auth, json=payload).status_code, 409)
        with self.Session() as db:
            job = db.get(Job, job_id)
            job.status = "failed"
            job.active_key = None
            job.attempted = 3
            job.failed = 3
            db.commit()
        retried = self.client.post(f"/api/admin/jobs/{job_id}/retry", headers=self.auth)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["status"], "queued")
        self.assertEqual(retried.json()["attempted"], 0)

    def test_frontend_dev_origin_can_call_api(self):
        response = self.client.options("/api/admin/export", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_fixed_sample_import_is_protected_and_tracks_two_batches(self):
        payload = {"dataset_id": DATASET_ID}
        self.assertEqual(self.client.post("/api/admin/imports", json=payload).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/imports", json=payload,
                         headers={"Authorization": "Bearer wrong"}).status_code, 403)
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count(Job.id))), 0)
        baseline = self.client.get("/api/admin/datasets", headers=self.auth).json()["items"][0]
        expected_ids = {paper["openalex_id"] for paper in baseline["papers"]}
        batches, internal_ids = [], []
        for _ in range(2):
            response = self.client.post("/api/admin/imports", json=payload, headers=self.auth)
            self.assertEqual(response.status_code, 201, response.text)
            job = response.json()
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["paper_count"], 20)
            self.assertEqual(job["total_papers"], 22)
            batches.append(job["batch_id"])
            result = self.client.get(f"/api/admin/jobs/{job['id']}/papers", headers=self.auth).json()
            self.assertEqual(result["total"], 20)
            self.assertEqual({paper["openalex_id"] for paper in result["items"]}, expected_ids)
            self.assertTrue(all(job["id"] in paper["batch_ids"] for paper in result["items"]))
            internal_ids.append({paper["id"] for paper in result["items"]})
        self.assertNotEqual(*batches)
        self.assertEqual(*internal_ids)
        detail = self.client.get(f"/api/papers/{next(iter(internal_ids[0]))}").json()
        self.assertEqual(detail["batch_ids"], batches)
        self.assertEqual(self.client.get(f"/api/papers?batch_id={batches[0]}").json()["total"], 20)
        export = self.client.get(f"/api/admin/export?batch_id={batches[1]}", headers=self.auth)
        rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 20)
        self.assertEqual(json.loads(rows[0]["batch_ids_json"]), batches)
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count(PaperBatch.paper_id))), 40)

    def test_unknown_or_tampered_sample_does_not_create_a_batch(self):
        response = self.client.post("/api/admin/imports", headers=self.auth, json={"dataset_id": "unknown"})
        self.assertEqual(response.status_code, 422)
        directory = sample_directory()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "week1_baseline.json").write_bytes((directory / "week1_baseline.json").read_bytes())
            (root / "cvpr_2024_seed.jsonl").write_text('{}\n', encoding="utf-8")
            with patch.dict(os.environ, {"SAMPLE_DIR": temporary}):
                response = self.client.post("/api/admin/imports", headers=self.auth, json={"dataset_id": DATASET_ID})
            self.assertEqual(response.status_code, 422)
            self.assertIn("checksum", response.json()["detail"])
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count(Job.id))), 0)

    def test_sample_retry_stays_offline_and_preserves_paper_ids(self):
        response = self.client.post("/api/admin/imports", headers=self.auth, json={"dataset_id": DATASET_ID})
        job_id = response.json()["id"]
        with self.Session() as db:
            job = db.get(Job, job_id)
            job.status = "failed"
            db.commit()
        with patch("scripts.fetch_openalex_batch.fetch_batch", side_effect=AssertionError("Must remain offline")):
            response = self.client.post(f"/api/admin/jobs/{job_id}/retry", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "succeeded")
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count(Paper.id))), 22)
            self.assertEqual(db.scalar(select(func.count(PaperBatch.paper_id))), 20)

    def test_interrupted_sample_is_replayed_from_the_fixed_dataset(self):
        from app.ingest import run_job
        with self.Session() as db:
            job = Job(venue="CVPR", year=2024, kind="sample", source="openalex", dataset_id=DATASET_ID,
                      status="queued", active_key="CVPR:2024")
            db.add(job)
            db.commit()
            with patch("scripts.fetch_openalex_batch.fetch_batch", side_effect=AssertionError("No external fetch")):
                run_job(db, job)
            self.assertEqual(job.status, "succeeded")
            self.assertEqual(job.succeeded, 20)
            self.assertEqual(db.scalar(select(func.count()).select_from(PaperBatch)), 20)
