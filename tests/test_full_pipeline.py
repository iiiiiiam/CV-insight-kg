import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.ingest import run_job, upsert_paper
from app.models import Base, Job, JobRecord, Paper, PaperBatch, Source


def row(identifier):
    return {"source_id": identifier, "dblp_key": identifier, "title": identifier,
            "doi": "10.1000/" + identifier, "venue": "CVPR", "year": 2024,
            "authors": ["Alice"], "raw": {"id": identifier}}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        with self.Session() as db:
            db.add_all([Source(name="dblp"), Source(name="openalex")])
            job = Job(venue="CVPR", year=2024, source="dblp", active_key="CVPR:2024")
            db.add(job)
            db.commit()
            self.job_id = job.id

    def tearDown(self):
        self.engine.dispose()

    def test_retry_only_failed_enrichment_from_durable_snapshot(self):
        with self.Session() as db, patch("app.ingest.fetch_dblp", return_value=[row("a"), row("b")]), patch(
                "app.ingest.fetch_openalex", side_effect=[requests.ConnectionError("offline"), None]):
            job = db.get(Job, self.job_id)
            run_job(db, job)
            self.assertEqual((job.status, job.succeeded, job.failed), ("partial", 1, 1))
            paper_ids = list(db.scalars(select(Paper.id).order_by(Paper.id)))
            self.assertEqual(len(paper_ids), 2)
        with self.Session() as db, patch("app.ingest.fetch_dblp") as fetch, patch(
                "app.ingest.fetch_openalex", return_value=None) as enrich:
            job = db.get(Job, self.job_id)
            job.status = "queued"
            job.attempted = job.succeeded = job.failed = 0
            db.commit()
            run_job(db, job)
            fetch.assert_not_called()
            enrich.assert_called_once()
            self.assertEqual((job.status, job.attempted, job.succeeded, job.failed), ("succeeded", 2, 2, 0))
            self.assertEqual(list(db.scalars(select(Paper.id).order_by(Paper.id))), paper_ids)
            self.assertEqual(db.scalar(select(func.count()).select_from(PaperBatch)), 2)
            records = db.scalars(select(JobRecord).order_by(JobRecord.id)).all()
            self.assertEqual([r.attempts for r in records], [2, 1])
            self.assertTrue(all(r.error is None for r in records))

    def test_process_interruption_resumes_pending_records_without_refetch(self):
        original = upsert_paper
        calls = []

        def interrupted(db, payload, *args, **kwargs):
            calls.append(payload["source_id"])
            if len(calls) == 2:
                raise KeyboardInterrupt()
            return original(db, payload, *args, **kwargs)

        with self.Session() as db, patch("app.ingest.fetch_dblp", return_value=[row("a"), row("b")]), patch(
                "app.ingest.fetch_openalex", return_value=None), patch("app.ingest.upsert_paper", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                run_job(db, db.get(Job, self.job_id))
        from app.worker import recover_jobs
        with patch("app.worker.SessionLocal", self.Session):
            recover_jobs()
        with self.Session() as db, patch("app.ingest.fetch_dblp") as fetch, patch(
                "app.ingest.fetch_openalex", return_value=None), patch("app.ingest.upsert_paper", wraps=original) as upsert:
            job = db.get(Job, self.job_id)
            run_job(db, job)
            fetch.assert_not_called()
            self.assertEqual(upsert.call_count, 1)
            self.assertEqual(upsert.call_args.args[1]["source_id"], "b")
            self.assertEqual((job.status, job.succeeded), ("succeeded", 2))

    def test_tampered_cache_is_rejected_before_writing_papers(self):
        work = {"id": "https://openalex.org/W1", "publication_year": 2024,
                "display_name": "Paper", "primary_location": {"source": {"id": "https://openalex.org/S4210176548"}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cvpr_2024.jsonl"
            path.write_text(json.dumps(work) + "\n")
            manifest = {"source": "openalex", "source_id": "S4210176548", "venue": "CVPR", "year": 2024,
                        "count": 1, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
            path.write_text(path.read_text().replace('"Paper"', '"Tampered"'))
            with self.Session() as db, patch.dict(os.environ, {"BATCH_DIR": directory}), patch(
                    "scripts.fetch_openalex_batch.fetch_batch", side_effect=requests.ConnectionError("offline")):
                job = db.get(Job, self.job_id)
                job.source = "openalex"
                db.commit()
                run_job(db, job)
                self.assertEqual(job.status, "failed")
                self.assertIn("checksum", job.error)
                self.assertEqual(db.scalar(select(func.count(Paper.id))), 0)

    def test_late_doi_keeps_existing_paper_id(self):
        with self.Session() as db:
            original = row("a")
            original["doi"] = None
            paper = upsert_paper(db, original)
            db.commit()
            identifier = paper.id
            incoming = row("other")
            incoming["title"] = "a"
            incoming.pop("dblp_key")
            paper = upsert_paper(db, incoming, "openalex")
            db.commit()
            self.assertEqual(paper.id, identifier)
            self.assertEqual(paper.doi, "10.1000/other")
            self.assertEqual(db.scalar(select(func.count(Paper.id))), 1)

    def test_failure_message_does_not_leak_credentials(self):
        with self.Session() as db, patch.dict(os.environ, {"OPENALEX_API_KEY": "secret-key"}), patch(
                "app.ingest.fetch_dblp", return_value=[row("a")]), patch("app.ingest.fetch_openalex",
                side_effect=requests.ConnectionError("https://api.openalex.org/works?api_key=secret-key secret-key")):
            run_job(db, db.get(Job, self.job_id))
            error = db.scalar(select(JobRecord.error))
            self.assertNotIn("secret-key", error)
            self.assertNotIn("api_key", error)
