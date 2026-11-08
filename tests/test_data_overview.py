import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, db_session
from app.db import seed_sources
from app.models import Base, Job, Paper, PaperBatch, PaperSource, database, now
from src.knowledge_builder.models import PaperInput


class DataOverviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        def override():
            with self.Session() as db:
                yield db
        app.dependency_overrides[db_session] = override
        self.env = patch.dict(os.environ, {'ADMIN_TOKEN': 'test-token', 'LOCAL_DEMO': '0'})
        self.env.start()
        self.seed = patch('app.api.seed_sources', lambda: seed_sources(self.Session))
        self.seed.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.auth = {'Authorization': 'Bearer test-token'}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        app.dependency_overrides.clear()
        self.seed.stop(); self.env.stop(); self.engine.dispose()

    def test_file_upload_is_protected_and_runs_from_frozen_inputs(self):
        from tests.test_a_operations import work,upload_content
        from app.ingest import run_job
        content,manifest=upload_content([work(987654)])
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'BATCH_DIR':directory}):
            self.assertEqual(self.client.post('/api/admin/file-imports',json={'content':content,'manifest':manifest}).status_code,401)
            response=self.client.post('/api/admin/file-imports',json={'content':content,'manifest':manifest},headers=self.auth)
            self.assertEqual(response.status_code,201)
            identifier=response.json()['id']
            with self.Session() as db,patch('scripts.fetch_openalex_batch.fetch_batch') as network:
                job=db.get(Job,identifier);run_job(db,job);network.assert_not_called()
                self.assertEqual(job.status,'succeeded')
            detail=self.client.get(f'/api/admin/jobs/{identifier}',headers=self.auth).json()
            self.assertEqual((detail['paper_count'],detail['progress']['succeeded']),(1,1))

    def test_front_matter_excluded_consistently_without_rejecting_authorless_research(self):
        with self.Session() as db:
            db.add_all([Paper(canonical_key='toc',title='Table of Contents',title_normalized='table of contents',year=2024,venue='CVPR',authors_json='[]'),
                        Paper(canonical_key='research',title='An Authorless Research Paper',title_normalized='an authorless research paper',year=2024,venue='CVPR',authors_json='[]')])
            db.commit()
        summary=self.client.get('/api/admin/data-overview',headers=self.auth).json()
        self.assertEqual(summary['total_papers'],1)
        self.assertEqual(summary['latest_papers'][0]['title'],'An Authorless Research Paper')
        papers=self.client.get('/api/papers').json()
        self.assertEqual(papers['total'],1)
        daily=self.client.get('/api/admin/new-papers',params={'day':now().date().isoformat()},headers=self.auth).json()
        self.assertEqual(daily['total'],1)
        from app.ingest import upsert_paper
        with self.Session() as db:
            with self.assertRaises(ValueError):
                upsert_paper(db,{'title':'Copyright Page','authors':[]},'openalex')

    def test_latest_papers_are_ordered_and_batch_quality_uses_full_batch(self):
        with self.Session() as db:
            job=Job(venue='CVPR',year=2024,source='openalex',status='succeeded')
            db.add(job);db.flush();job_id=job.id
            for i in range(25):
                paper=Paper(canonical_key=f'latest-{i}',title=f'Paper {i}',title_normalized=f'paper {i}',year=2024,venue='CVPR',abstract='Abstract' if i%2 else None,authors_json='["Author"]',doi=f'10.example/{i}' if i<3 else None,first_seen_at=now()-timedelta(days=25-i))
                db.add(paper);db.flush();db.add(PaperBatch(job_id=job_id,paper_id=paper.id,is_new=True))
            db.commit()
        latest=self.client.get('/api/admin/data-overview',headers=self.auth).json()['latest_papers']
        self.assertEqual(len(latest),20)
        self.assertEqual([p['title'] for p in latest],[f'Paper {i}' for i in range(24,4,-1)])
        quality=self.client.get(f'/api/admin/jobs/{job_id}',headers=self.auth).json()['quality']
        self.assertEqual(quality,{'total':25,'with_abstract':12,'with_doi':3,'with_authors':25})

    def test_archived_batches_do_not_inflate_current_import_statistics(self):
        with self.Session() as db:
            db.add_all([Job(venue='CVPR',year=2024,source='openalex',kind='archive',status='succeeded',attempted=2700,succeeded=2700,failed=0),
                        Job(venue='CVPR',year=2024,source='openalex',kind='demo',status='succeeded',attempted=120,succeeded=120,failed=0)])
            db.commit()
        response=self.client.get('/api/admin/data-overview',headers=self.auth).json()
        self.assertEqual(response['successful_records'],120)
        self.assertEqual(len(response['recent_batches']),1)
        self.assertEqual(len(self.client.get('/api/admin/jobs',headers=self.auth).json()),1)

    def test_all_displayed_periods_and_overview_interfaces(self):
        for days in (7, 14, 30):
            with self.subTest(days=days):
                response = self.client.get('/api/admin/data-overview', params={'days': days}, headers=self.auth)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['days'], days)
                self.assertEqual(len(response.json()['trend']), days)
        self.assertEqual(self.client.get('/api/admin/data-overview?days=31', headers=self.auth).status_code, 422)
        self.assertEqual(self.client.get('/api/admin/jobs', headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/api/admin/datasets', headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get('/api/admin/new-papers', params={'day': now().date().isoformat()}, headers=self.auth).status_code, 200)

    def test_supplement_import_twice_counts_and_handoff_original_evidence(self):
        self.assertEqual(self.client.get('/api/admin/data-overview').status_code, 401)
        datasets = self.client.get('/api/admin/datasets', headers=self.auth).json()['items']
        self.assertEqual(len(datasets), 4)
        for source in ['cvpr2024', 'iccv2023', 'eccv2024']:
            dataset = f'additional-{source}-detection-20-v1'
            a = self.client.post('/api/admin/imports', headers=self.auth, json={'dataset_id': dataset}).json()
            b = self.client.post('/api/admin/imports', headers=self.auth, json={'dataset_id': dataset}).json()
            self.assertEqual((a['status'], b['status'], a['paper_count'], b['paper_count']), ('succeeded', 'succeeded', 20, 20))
            comparison = self.client.get('/api/admin/batch-comparison', headers=self.auth,
                                         params={'first': a['id'], 'second': b['id']}).json()
            self.assertEqual((comparison['shared_papers'], comparison['only_first'], comparison['only_second']), (20, 0, 0))
            self.assertEqual((comparison['first']['new_papers'], comparison['second']['new_papers']), (20, 0))
            if source == 'cvpr2024':
                with self.Session() as db:
                    old_job = db.get(Job, a['id'])
                    old_job.status = 'partial'; old_job.failed = 1
                    db.commit()
                retried = self.client.post(f"/api/admin/jobs/{a['id']}/retry", headers=self.auth)
                self.assertEqual(retried.status_code, 200)
                again = self.client.get('/api/admin/batch-comparison', headers=self.auth,
                                        params={'first': a['id'], 'second': b['id']}).json()
                self.assertEqual((again['first']['new_papers'], again['second']['new_papers']), (20, 0))
            export = self.client.get('/api/admin/handoff', headers=self.auth, params={'batch_id': b['id']}).json()
            self.assertEqual((export['exported_papers'], export['excluded_papers']), (20, 0))
            for item in export['items']:
                paper = PaperInput(**item)
                self.assertTrue(paper.abstract and paper.openalex_id and paper.source_url)
                if source == 'eccv2024':
                    self.assertTrue(paper.source_url.startswith('https://www.ecva.net/'))
                    self.assertTrue(all(not author['institutions'] for author in paper.authorships))
        overview = self.client.get('/api/admin/data-overview', headers=self.auth).json()
        self.assertEqual((overview['total_papers'], overview['new_papers'], overview['with_abstract']), (60, 60, 60))
        self.assertEqual((overview['successful_records'], overview['failed_records']), (120, 0))
        self.assertEqual({x['name']: x['papers'] for x in overview['sources']}, {'openalex': 60, 'ecva': 20})
        self.assertEqual(sum(x['papers'] for x in overview['trend']), 60)
        self.assertEqual(sum(sum(x['sources'].values()) for x in overview['trend']), 60)
        self.assertEqual(overview['failed_tasks'], 0)
        today = now().date().isoformat()
        page = self.client.get('/api/admin/new-papers', params={'day': today, 'page_size': 10}, headers=self.auth).json()
        self.assertEqual((page['total'], len(page['items'])), (60, 10))
        self.assertEqual(self.client.get('/api/admin/new-papers?day=not-a-date', headers=self.auth).status_code, 422)

    def test_missing_source_and_old_papers_are_not_invented(self):
        with self.Session() as db:
            old = Paper(canonical_key='legacy', title='Old paper', title_normalized='old paper',
                        year=2024, venue='CVPR', first_seen_at=now()-timedelta(days=30))
            job = Job(venue='CVPR', year=2024, source='dblp', status='partial',
                      attempted=2, succeeded=1, failed=1, started_at=now(), finished_at=now())
            db.add_all([old, job]); db.flush(); db.add(PaperBatch(job_id=job.id, paper_id=old.id)); db.commit()
            job_id = job.id
        overview = self.client.get('/api/admin/data-overview', headers=self.auth).json()
        self.assertEqual((overview['total_papers'], overview['new_papers'], overview['missing_abstract']), (1, 0, 1))
        self.assertEqual((overview['successful_records'], overview['failed_records']), (1, 1))
        comparison = self.client.get('/api/admin/batch-comparison', params={'first': job_id, 'second': job_id}, headers=self.auth).json()
        self.assertIsNone(comparison['first']['new_papers'])
        result = self.client.get('/api/admin/handoff', params={'batch_id': job_id}, headers=self.auth).json()
        self.assertEqual((result['exported_papers'], result['excluded_papers']), (0, 1))
        self.assertEqual(self.client.get('/api/admin/batch-comparison?first=1&second=999', headers=self.auth).status_code, 404)

    def test_existing_batch_table_gets_nullable_tracking_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.db'
            engine = create_engine('sqlite:///' + str(path))
            with engine.begin() as conn:
                conn.exec_driver_sql('CREATE TABLE paper_batches (job_id INTEGER NOT NULL, paper_id INTEGER NOT NULL, imported_at DATETIME, PRIMARY KEY(job_id,paper_id))')
                conn.exec_driver_sql('INSERT INTO paper_batches(job_id,paper_id) VALUES (1,42)')
            engine.dispose()
            factory = database('sqlite:///' + str(path))
            try:
                with factory() as db:
                    self.assertIsNone(db.get(PaperBatch, (1, 42)).is_new)
            finally:
                factory.kw['bind'].dispose()

    def test_conflicting_eccv_source_mapping_is_reported_instead_of_merged(self):
        from app.additional_samples import sample_dir
        from app.ingest import openalex_work_row, upsert_paper
        raw = [json.loads(line) for line in (sample_dir() / 'raw/eccv_2024.openalex.jsonl').read_text().splitlines()]
        evidence = [json.loads(line) for line in (sample_dir() / 'raw/eccv_2024.ecva.jsonl').read_text().splitlines()]
        record = evidence[0]
        work = next(item for item in raw if item['id'] == record['openalex_id'])
        with self.Session() as db:
            original = upsert_paper(db, openalex_work_row(work, 'ECCV', 2024), 'openalex')
            other = Paper(canonical_key='different-legacy-paper', title='Conflicting record',
                          title_normalized='conflicting record', year=2024, venue='ECCV')
            db.add(other); db.flush()
            db.add(PaperSource(paper_id=other.id, source='ecva',
                               source_id=record['official_record']['source_id'], raw_json='{}'))
            db.commit(); original_id, other_id = original.id, other.id
        response = self.client.post('/api/admin/imports', headers=self.auth,
                                    json={'dataset_id': 'additional-eccv2024-detection-20-v1'})
        result = response.json()
        self.assertEqual((response.status_code, result['status'], result['succeeded'], result['failed']), (201, 'partial', 19, 1))
        with self.Session() as db:
            self.assertIsNone(db.get(PaperBatch, (result['id'], original_id)))
            self.assertIsNone(db.get(PaperBatch, (result['id'], other_id)))
            self.assertEqual(db.scalar(select(func.count()).select_from(PaperBatch).where(PaperBatch.job_id == result['id'])), 19)


if __name__ == '__main__':
    unittest.main()
