import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import requests
from sqlalchemy import select, func
from app.models import database, Job, JobRecord, Paper, PaperBatch, PaperSource, Source, SourceRevision
from app.ingest import upsert_paper, openalex_work_row, run_job
from app.batch_import import queue_upload


def work(n, title=None):
    return {'id':f'https://openalex.org/W{n}', 'display_name':title or f'Research Paper {n}',
            'publication_year':2024, 'doi':f'https://doi.org/10.1234/{n}',
            'primary_location':{'source':{'id':'https://openalex.org/S4210176548'},'landing_page_url':f'https://doi.org/10.1234/{n}'},
            'authorships':[{'author':{'display_name':'Author'}}], 'abstract_inverted_index':{'Abstract':[0]},'cited_by_count':1}


def upload_content(rows):
    content=''.join(json.dumps(w)+'\n' for w in rows)
    return content, {'source':'openalex','source_id':'S4210176548','venue':'CVPR','year':2024,'count':len(rows),'sha256':hashlib.sha256(content.encode()).hexdigest()}


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.factory=database('sqlite:///'+str(self.path/'a.db'))
        self.env=patch.dict('os.environ',{'BATCH_DIR':str(self.path/'batches')});self.env.start()
        with self.factory() as db:
            db.add_all([Source(name=s) for s in ('openalex','dblp','cvf','ecva')]);db.commit()
    def tearDown(self):
        self.env.stop();self.factory.kw['bind'].dispose();self.tmp.cleanup()

    def test_upload_dedup_skips_front_matter_and_stable_updates(self):
        front={**work(2,'Table of Contents'),'authorships':[]}
        content,manifest=upload_content([work(1),front])
        with self.factory() as db:
            first=queue_upload(db,content,manifest);run_job(db,first)
            self.assertEqual((first.status,first.succeeded,first.skipped),('succeeded',1,1))
            paper=db.scalar(select(Paper));identifier=paper.id;stamp=paper.updated_at
            second=queue_upload(db,content,manifest);run_job(db,second)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),1)
            self.assertEqual(db.get(Paper,identifier).updated_at,stamp)
            self.assertFalse(db.get(PaperBatch,(second.id,identifier)).is_new)
            self.assertEqual(db.scalar(select(func.count()).select_from(SourceRevision)),1)
            changed=work(1);changed['cited_by_count']=8
            upsert_paper(db,openalex_work_row(changed,'CVPR',2024),'openalex');db.commit()
            self.assertEqual(db.get(Paper,identifier).cited_by_count,8)
            self.assertEqual(db.scalar(select(func.count()).select_from(SourceRevision)),2)

    def test_upload_rejects_tampered_scope_and_retains_no_job(self):
        content,manifest=upload_content([work(1)])
        with self.factory() as db:
            with self.assertRaises(ValueError):queue_upload(db,content+' ',manifest)
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),0)
            with self.assertRaises(ValueError):queue_upload(db,content,{**manifest,'year':2023})
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),0)


    def test_cross_source_late_doi_and_conflicting_identity(self):
        row={'source_id':'cvf:1','title':'Research Paper 1','authors':['Author'],'venue':'CVPR','year':2024,'raw':{'official':1}}
        with self.factory() as db:
            original=upsert_paper(db,row,'cvf');db.commit();identifier=original.id
            upsert_paper(db,openalex_work_row(work(1),'CVPR',2024),'openalex');db.commit()
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),1)
            self.assertEqual(db.get(Paper,identifier).openalex_id,'https://openalex.org/W1')
            with self.assertRaises(ValueError):upsert_paper(db,openalex_work_row({**work(1),'doi':'https://doi.org/10.1234/different'},'CVPR',2024),'openalex')
            db.rollback()
            self.assertEqual(db.get(Paper,identifier).doi,'10.1234/1')

    def test_ecva_resumes_after_matching_failure_without_refetching_detail(self):
        from app.pipeline import save_snapshot,process_snapshot
        row={'source_id':'eccv2024:1','source_url':'https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/1_ECCV_2024_paper.php','title':'Research Paper 1','venue':'ECCV','year':2024,'doi':'10.1234/1','authors':['Author'],'raw':{}}
        detailed={**row,'abstract':'Official abstract','_detail_complete':True}
        with self.factory() as db:
            job=Job(venue='ECCV',year=2024,source='ecva',active_key='ECCV:2024');db.add(job);db.commit();save_snapshot(db,job,[row],'ecva')
            with patch('app.ecva.fetch_detail',return_value=detailed) as detail,patch('app.ecva.match_openalex',side_effect=requests.ConnectionError('offline')):
                process_snapshot(db,job);self.assertEqual(job.failed,1);detail.assert_called_once()
            with patch('app.ecva.fetch_detail') as detail,patch('app.ecva.match_openalex',return_value={**work(1),'publication_year':2024}):
                process_snapshot(db,job);detail.assert_not_called();self.assertEqual((job.status,job.succeeded),('succeeded',1))
            from app.data_overview import handoff
            self.assertEqual(handoff(db,job)['items'][0]['abstract'],'Official abstract')


    def test_metadata_only_ecva_refresh_retains_previous_abstract_evidence(self):
        from app.additional_samples import import_additional
        from app.official import save_official
        from app.data_overview import handoff
        with self.factory() as db:
            job=import_additional(db,'additional-eccv2024-detection-20-v1')
            paper=db.scalar(select(Paper))
            official=db.scalar(select(PaperSource).where(PaperSource.source=='ecva',PaperSource.paper_id==paper.id))
            incoming={'source_id':official.source_id,'source_url':official.source_url,'title':paper.title,'venue':paper.venue,'year':paper.year,'doi':paper.doi,'authors':json.loads(paper.authors_json),'raw':{'index':'metadata only'}}
            save_official(db,incoming,None,job,'ecva');db.commit()
            self.assertEqual(handoff(db,job)['exported_papers'],20)
            stamp=paper.updated_at
            save_official(db,incoming,None,job,'ecva');db.commit()
            self.assertEqual(paper.updated_at,stamp)

    def test_cached_records_do_not_roll_back_newer_metadata(self):
        with self.factory() as db:
            newer=work(1);newer['cited_by_count']=50
            paper=upsert_paper(db,openalex_work_row(newer,'CVPR',2024),'openalex');db.commit()
            row=dict(openalex_work_row(work(1),'CVPR',2024),_cached=True)
            upsert_paper(db,row,'openalex');db.commit()
            self.assertEqual(paper.cited_by_count,50)
            self.assertEqual(json.loads(db.scalar(select(PaperSource.raw_json)))['cited_by_count'],50)

    def test_abstract_gaps_duplicates_and_author_shapes_are_rejected(self):
        from app.ingest import decode_abstract
        for bad in ({'word':[10**12]},{'one':[0],'two':[0]},{'word':[-1]}):
            with self.assertRaises(ValueError):decode_abstract(bad)
        with self.factory() as db:
            with self.assertRaises(ValueError):upsert_paper(db,{**openalex_work_row(work(1),'CVPR',2024),'authors':'not a list'},'openalex')

    def test_download_checkpoint_resumes_after_incomplete_second_page(self):
        from scripts.fetch_openalex_batch import fetch_batch
        first=Mock();first.status_code=200;first.json.return_value={'meta':{'count':2},'results':[work(1)]}
        second=Mock();second.status_code=200;second.json.return_value={'meta':{'count':2},'results':[work(2)]}
        with patch('scripts.fetch_openalex_batch.time.sleep'),patch.dict('os.environ',{'OPENALEX_API_KEY':''}):
            path=self.path/'download.jsonl'
            with patch('scripts.fetch_openalex_batch.requests.Session') as http:
                http.return_value.get.side_effect=[first,requests.ConnectionError('offline')]
                with self.assertRaises(requests.ConnectionError):fetch_batch('CVPR',2024,path,retries=1,page_size=1)
            with path.with_suffix('.jsonl.part').open('a') as file:file.write('{incomplete')
            with patch('scripts.fetch_openalex_batch.requests.Session') as http:
                http.return_value.get.return_value=second
                manifest=fetch_batch('CVPR',2024,path,retries=1,page_size=1)
                self.assertEqual(http.return_value.get.call_args.kwargs['params']['page'],2)
                self.assertEqual(manifest['count'],2)


class AnnotationCheckpointTests(unittest.TestCase):
    def test_annotation_mode_cannot_change_when_resuming_and_raw_fields_survive(self):
        from scripts.fetch_openalex_batch import fetch_batch, ANNOTATION_FIELDS
        annotated = {**work(1), 'primary_topic': {'display_name': 'Computer Vision'},
                     'topics': [{'display_name': 'Object Detection'}],
                     'keywords': [{'display_name': 'Transformer'}]}
        first = Mock(status_code=200)
        first.json.return_value = {'meta': {'count': 2}, 'results': [annotated]}
        second = Mock(status_code=200)
        second.json.return_value = {'meta': {'count': 2}, 'results': [work(2)]}
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'OPENALEX_API_KEY': ''}), patch('scripts.fetch_openalex_batch.time.sleep'):
            path = Path(directory) / 'papers.jsonl'
            with patch('scripts.fetch_openalex_batch.requests.Session') as http:
                http.return_value.get.side_effect = [first, requests.ConnectionError('offline')]
                with self.assertRaises(requests.ConnectionError):
                    fetch_batch('CVPR', 2024, path, retries=1, page_size=1, with_annotations=True)
            original = path.with_suffix('.jsonl.part').read_bytes()
            with patch('scripts.fetch_openalex_batch.requests.Session') as http:
                with self.assertRaisesRegex(ValueError, 'fields changed'):
                    fetch_batch('CVPR', 2024, path, retries=1, page_size=1)
                http.return_value.get.assert_not_called()
            self.assertEqual(path.with_suffix('.jsonl.part').read_bytes(), original)
            with patch('scripts.fetch_openalex_batch.requests.Session') as http:
                http.return_value.get.return_value = second
                manifest = fetch_batch('CVPR', 2024, path, retries=1, page_size=1, with_annotations=True)
                self.assertEqual(http.return_value.get.call_args.kwargs['params']['page'], 2)
            self.assertTrue(set(ANNOTATION_FIELDS.split(',')) <= set(manifest['requested_fields']))
            self.assertEqual(manifest['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(json.loads(path.read_text().splitlines()[0])['keywords'], annotated['keywords'])
