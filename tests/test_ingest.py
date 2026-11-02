import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import requests
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.ingest import decode_abstract, normalize_doi, parse_dblp_xml, run_job
from app.import_openalex import work_row
from app.ingest import upsert_paper
from app.models import Base, Job, Paper, PaperSource, Source, database
from app.api import JobCreate, create_job


DBLP_XML = b'''<?xml version="1.0" encoding="utf-8"?>
<dblp>
  <inproceedings key="conf/cvpr/Test24">
    <author>Alice Example</author><author>Bob Example</author>
    <title>Test &amp; Verify.</title><year>2024</year>
    <ee>https://doi.org/10.1000/TEST.24</ee>
  </inproceedings>
  <inproceedings key="conf/cvpr/Old23"><title>Old</title><year>2023</year></inproceedings>
</dblp>'''


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_xml_scope_and_normalization(self):
        rows = parse_dblp_xml(DBLP_XML, "CVPR", 2024)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doi"], "10.1000/test.24")
        self.assertEqual(rows[0]["title"], "Test & Verify")
        self.assertEqual(rows[0]["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(decode_abstract({"hello": [0], "world": [1]}), "hello world")
        with self.assertRaises(ValueError):
            parse_dblp_xml(b"<html>verification</html>", "CVPR", 2024)

    def test_openalex_only_import_keeps_authors_abstract_and_provenance(self):
        work = {"id": "https://openalex.org/W123", "display_name": "A Test Paper",
                "publication_year": 2024, "doi": None,
                "authorships": [{"author": {"display_name": "Alice Example"}}],
                "abstract_inverted_index": {"hello": [0], "world": [1]},
                "cited_by_count": 5}
        row = work_row(work, "CVPR", 2024)
        with self.Session() as db:
            upsert_paper(db, row, "openalex")
            db.commit()
            upsert_paper(db, row, "openalex")
            db.commit()
            paper = db.scalar(select(Paper))
            self.assertEqual(db.scalar(select(func.count(Paper.id))), 1)
            self.assertEqual(db.scalar(select(func.count(PaperSource.id))), 1)
            self.assertEqual(paper.canonical_key, "openalex:https://openalex.org/W123")
            self.assertEqual(json.loads(paper.authors_json), ["Alice Example"])
            self.assertEqual(paper.abstract, "hello world")

    @patch("app.ingest.fetch_openalex")
    @patch("app.ingest.fetch_dblp")
    def test_rerun_updates_one_paper_and_tracks_both_sources(self, dblp, openalex):
        dblp.return_value = parse_dblp_xml(DBLP_XML, "CVPR", 2024)
        openalex.return_value = {"source_id": "https://openalex.org/W1", "source_url": "https://openalex.org/W1",
                                 "doi": "10.1000/test.24", "abstract": "hello world", "cited_by_count": 7,
                                 "raw": {"id": "https://openalex.org/W1"}}
        with self.Session() as db:
            db.add_all([Source(name="dblp"), Source(name="openalex")])
            db.commit()
            first = Job(venue="CVPR", year=2024)
            db.add(first)
            db.commit()
            run_job(db, first)
            second = Job(venue="CVPR", year=2024)
            db.add(second)
            db.commit()
            run_job(db, second)
            self.assertEqual(first.status, "succeeded")
            self.assertEqual(second.status, "succeeded")
            self.assertEqual(db.scalar(select(func.count(Paper.id))), 1)
            self.assertEqual(db.scalar(select(func.count(PaperSource.id))), 2)
            dblp_source = db.scalar(select(PaperSource).where(PaperSource.source == "dblp"))
            self.assertIn("<inproceedings", json.loads(dblp_source.raw_json)["dblp_xml"])
            paper = db.scalar(select(Paper))
            self.assertEqual(paper.abstract, "hello world")
            self.assertEqual(paper.cited_by_count, 7)
            self.assertEqual(json.loads(paper.authors_json), ["Alice Example", "Bob Example"])

    @patch("app.ingest.fetch_dblp", side_effect=ValueError("upstream verification page"))
    def test_upstream_failure_is_visible(self, _fetch):
        with self.Session() as db:
            db.add(Source(name="dblp"))
            job = Job(venue="CVPR", year=2024)
            db.add(job)
            db.commit()
            run_job(db, job)
            self.assertEqual(job.status, "failed")
            self.assertIn("verification", job.error)

    def test_openalex_job_uses_checked_cache_and_reruns_without_duplicates(self):
        work = {"id": "https://openalex.org/W123", "display_name": "Object Detection Study",
                "publication_year": 2024, "doi": "https://doi.org/10.1000/example",
                "primary_location": {"source": {"id": "https://openalex.org/S4210176548"}},
                "authorships": [{"author": {"display_name": "Alice Example"}}],
                "abstract_inverted_index": {"sample": [0]}, "cited_by_count": 3}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cvpr_2024.jsonl"
            path.write_text(json.dumps(work) + "\n", encoding="utf-8")
            path.with_suffix(".manifest.json").write_text(json.dumps({
                "venue": "CVPR", "year": 2024, "source": "openalex",
                "source_id": "S4210176548", "count": 1}), encoding="utf-8")
            with patch.dict(os.environ, {"BATCH_DIR": directory}), patch(
                "scripts.fetch_openalex_batch.fetch_batch", side_effect=requests.ConnectionError("offline")
            ):
                with self.Session() as db:
                    db.add(Source(name="openalex"))
                    db.commit()
                    for _ in range(2):
                        job = Job(venue="CVPR", year=2024, source="openalex", active_key="CVPR:2024")
                        db.add(job)
                        db.commit()
                        run_job(db, job)
                        self.assertEqual(job.status, "partial")
                        self.assertIn("cached", job.error)
                        self.assertEqual(job.succeeded, 1)
                    self.assertEqual(db.scalar(select(func.count(Paper.id))), 1)
                    self.assertEqual(db.scalar(select(func.count(PaperSource.id))), 1)

    def test_restart_recovery_resets_managed_job_counts(self):
        from app.worker import recover_jobs
        with self.Session() as db:
            managed = Job(venue="CVPR", year=2024, source="openalex", status="running",
                          active_key="CVPR:2024", attempted=20, succeeded=15, failed=5)
            manual = Job(venue="ICCV", year=2023, source="openalex", status="running", attempted=2)
            db.add_all([managed, manual])
            db.commit()
            managed_id, manual_id = managed.id, manual.id
        with patch("app.worker.SessionLocal", self.Session):
            recover_jobs()
        with self.Session() as db:
            recovered = db.get(Job, managed_id)
            self.assertEqual(recovered.status, "queued")
            self.assertEqual((recovered.attempted, recovered.succeeded, recovered.failed), (0, 0, 0))
            self.assertEqual(db.get(Job, manual_id).status, "running")

    @patch("app.ingest.fetch_dblp", side_effect=ValueError("DBLP verification page"))
    def test_auto_job_falls_back_to_openalex(self, _fetch):
        with self.Session() as db:
            db.add_all([Source(name="dblp"), Source(name="openalex")])
            db.commit()
            job = Job(venue="CVPR", year=2024, source="auto")
            db.add(job)
            db.commit()
            with patch("app.ingest.run_openalex_job") as fallback:
                run_job(db, job)
            fallback.assert_called_once_with(db, job)

    def test_admin_can_queue_openalex_and_reject_unsupported_venue(self):
        with self.Session() as db:
            db.add(Source(name="openalex"))
            db.commit()
            result = create_job(JobCreate(venue="CVPR", year=2024, source="openalex"), db)
            self.assertEqual(result["source"], "openalex")
            self.assertEqual(result["status"], "queued")
            with self.assertRaises(HTTPException) as duplicate:
                create_job(JobCreate(venue="CVPR", year=2024, source="openalex"), db)
            self.assertEqual(duplicate.exception.status_code, 409)
            with self.assertRaises(HTTPException) as unsupported:
                create_job(JobCreate(venue="ECCV", year=2024, source="openalex"), db)
            self.assertEqual(unsupported.exception.status_code, 422)


class MigrationTests(unittest.TestCase):
    def test_existing_jobs_table_gets_source_column(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + str(Path(directory) / "legacy.db")
            engine = create_engine(url)
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE jobs (id INTEGER PRIMARY KEY, venue VARCHAR(20), year INTEGER)")
            engine.dispose()
            # Release both database engines before deleting the temporary file.
            with ExitStack() as cleanup:
                session_factory = database(url)
                cleanup.callback(session_factory.kw["bind"].dispose)
                with session_factory() as db:
                    db.execute(select(Job.source).limit(1))
                second_factory = database(url)
                cleanup.callback(second_factory.kw["bind"].dispose)


if __name__ == "__main__":
    unittest.main()
