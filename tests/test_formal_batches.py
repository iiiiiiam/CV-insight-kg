import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select,func
from app.models import database,Paper,Job,JobRecord,StablePaper
from app.formal_batches import queue_batch,process_batch,batch_manifest,withdraw_batch,effective_state,export_json
from app.ingest import openalex_work_row
from app.paper_quality import research_paper_scope


def record(i,**changes):
    raw={'id':f'https://openalex.org/W{i}','display_name':f'Research Paper {i}','publication_year':2024,
         'doi':f'https://doi.org/10.1234/{i}','authorships':[{'author':{'display_name':'Test Author'}}],
         'abstract_inverted_index':{'Research':[0],'abstract':[1]},'cited_by_count':1,
         'primary_location':{'source':{'id':'https://openalex.org/S4210176548'}}}
    raw.update(changes)
    return {'source':'openalex','row':openalex_work_row(raw,'CVPR',2024)}


class FormalBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.factory=database('sqlite:///'+str(Path(self.tmp.name)/'test.db'))
    def tearDown(self):self.factory.kw['bind'].dispose();self.tmp.cleanup()
    def ingest(self,db,key,records):
        job,replay=queue_batch(db,key,'CVPR',2024,records)
        return job,process_batch(db,job) if not replay else batch_manifest(db,job.id)
    def test_two_batches_withdrawal_restores_prior_content_and_keeps_shared_ids(self):
        with self.factory() as db:
            first,a=self.ingest(db,'first',[record(1),record(2)])
            ids=list(db.scalars(select(Paper.id).order_by(Paper.id)))
            second,b=self.ingest(db,'second',[record(2,cited_by_count=9),record(3)])
            self.assertEqual((len(b['changes']['added']),len(b['changes']['updated'])),(1,1))
            self.assertEqual(effective_state(db)['paper_count'],3)
            before=effective_state(db)['revision']
            result=withdraw_batch(db,second.id,'Remove second batch')
            active=effective_state(db)
            self.assertEqual(active['paper_count'],2);self.assertNotEqual(active['revision'],before)
            self.assertEqual([db.get(Paper,i).id for i in ids],ids)
            self.assertEqual(db.scalar(select(Paper).where(Paper.openalex_id=='https://openalex.org/W2')).cited_by_count,1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper).where(research_paper_scope())),2)
            kept=[x for x in result['changes']['withdrawn'] if x['still_effective']]
            self.assertEqual(len(kept),1);self.assertEqual(kept[0]['remaining_batches'],[a['batch_code']])
            repeated=withdraw_batch(db,second.id,'Again')
            self.assertEqual(effective_state(db)['revision'],active['revision'])
            self.assertEqual(repeated['withdrawal_reason'],'Remove second batch')
            self.assertEqual(batch_manifest(db,second.id)['items'],b['items'])
    def test_replay_is_immutable_and_independent_batches_deduplicate(self):
        with self.factory() as db:
            job,a=self.ingest(db,'a',[record(1)])
            ids=a['stable_papers'];n= db.scalar(select(func.count()).select_from(Paper))
            replay,same=queue_batch(db,'a','CVPR',2024,[record(1)])
            self.assertTrue(same);self.assertEqual(replay.id,job.id)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),n)
            with self.assertRaises(ValueError):queue_batch(db,'a','CVPR',2024,[record(2)])
            _,b=self.ingest(db,'b',[record(1)])
            self.assertEqual(b['stable_papers'],ids);self.assertEqual(len(b['changes']['duplicate']),1)
    def test_source_failure_retry_uses_frozen_inputs_and_preserves_committed_paper(self):
        from app.formal_batches import upsert_paper
        with self.factory() as db:
            job,_=queue_batch(db,'retry','CVPR',2024,[record(1),record(2)])
            def fail(db,row,*a,**kw):
                if row['source_id'].endswith('W2'):raise OSError('temporary failure')
                return upsert_paper(db,row,*a,**kw)
            with patch('app.formal_batches.upsert_paper',side_effect=fail):result=process_batch(db,job)
            self.assertEqual(job.status,'partial');self.assertEqual(len(result['changes']['failed']),1)
            identifier=db.scalar(select(Paper.id))
            self.assertEqual(process_batch(db,job)['status'],'succeeded')
            self.assertEqual(db.scalar(select(Paper.id).where(Paper.openalex_id.endswith('W1'))),identifier)
            self.assertEqual(list(db.scalars(select(JobRecord.attempts).order_by(JobRecord.id))),[1,2])
    def test_withdrawn_unique_paper_reappears_with_same_identity_in_new_batch(self):
        with self.factory() as db:
            job,a=self.ingest(db,'a',[record(1)])
            withdraw_batch(db,job.id,'Withdraw');self.assertEqual(effective_state(db)['paper_count'],0)
            _,b=self.ingest(db,'b',[record(1)])
            self.assertEqual(a['stable_papers'],b['stable_papers']);self.assertEqual(len(b['changes']['added']),1)
            self.assertEqual(effective_state(db)['paper_count'],1)
    def test_preexisting_nonformal_paper_remains_valid_after_withdrawal(self):
        from app.ingest import upsert_paper
        with self.factory() as db:
            upsert_paper(db,record(1)['row'],'openalex');db.commit()
            job,_=self.ingest(db,'later',[record(1,cited_by_count=3)])
            withdraw_batch(db,job.id,'Cancel change')
            paper=db.scalar(select(Paper).where(research_paper_scope()))
            self.assertIsNotNone(paper);self.assertEqual(paper.cited_by_count,1)
    def test_no_destructive_write_for_invalid_scope_or_active_withdrawal(self):
        with self.factory() as db:
            with self.assertRaises(ValueError):queue_batch(db,'bad','ICCV',2024,[record(1)])
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),0)
            job,_=queue_batch(db,'queued','CVPR',2024,[record(1)])
            with self.assertRaises(ValueError):withdraw_batch(db,job.id,'Cancel')
    def test_retry_of_older_batch_does_not_replace_newer_effective_metadata(self):
        from app.formal_batches import upsert_paper
        with self.factory() as db:
            old,_=queue_batch(db,'old','CVPR',2024,[record(1)])
            with patch('app.formal_batches.upsert_paper',side_effect=OSError('temporary')):process_batch(db,old)
            latest,_=self.ingest(db,'latest',[record(1,cited_by_count=99)])
            process_batch(db,old)
            paper=db.scalar(select(Paper))
            self.assertEqual(paper.cited_by_count,99)
            self.assertEqual(effective_state(db)['papers'][0]['paper']['cited_by_count'],99)
            withdraw_batch(db,latest.id,'roll back latest')
            self.assertEqual(db.scalar(select(Paper)).cited_by_count,1)
    def test_withdrawing_older_batch_keeps_newer_shared_paper(self):
        with self.factory() as db:
            old,_=self.ingest(db,'old',[record(1)])
            latest,_=self.ingest(db,'latest',[record(1,cited_by_count=3)])
            withdraw_batch(db,old.id,'remove old')
            self.assertEqual(effective_state(db)['paper_count'],1)
            self.assertEqual(db.scalar(select(Paper)).cited_by_count,3)
    def test_source_identity_tampering_is_rejected_before_queue(self):
        changed=record(1);changed['row']['source_id']='https://openalex.org/W2'
        with self.factory() as db:
            with self.assertRaises(ValueError):queue_batch(db,'bad','CVPR',2024,[changed])
            changed=record(1);changed['row']['title']='Not the original title'
            with self.assertRaises(ValueError):queue_batch(db,'bad-title','CVPR',2024,[changed])

    def test_interrupted_processing_resumes_from_durable_checkpoint(self):
        from app.formal_batches import upsert_paper
        with self.factory() as db:job,_=queue_batch(db,'interrupt','CVPR',2024,[record(i) for i in range(1,31)]);job_id=job.id
        def interrupt(db,row,*args,**kwargs):
            if row['source_id'].endswith('W30'):raise KeyboardInterrupt()
            return upsert_paper(db,row,*args,**kwargs)
        try:
            with self.factory() as db,patch('app.formal_batches.upsert_paper',side_effect=interrupt):process_batch(db,db.get(Job,job_id))
        except KeyboardInterrupt:pass
        else:self.fail('Expected simulated interruption')
        with self.factory() as db:
            identifiers=list(db.scalars(select(Paper.id)))
            self.assertEqual(len(identifiers),25)
            self.assertEqual(db.get(Job,job_id).succeeded,25)
            result=process_batch(db,db.get(Job,job_id))
            self.assertEqual(result['status'],'succeeded')
            self.assertTrue(set(identifiers)<=set(db.scalars(select(Paper.id))))
            self.assertEqual(effective_state(db)['paper_count'],30)

    def test_export_keeps_existing_paperinput_shape_and_verified_checksum(self):
        import hashlib
        from src.knowledge_builder.models import PaperInput
        with self.factory() as db:
            _,result=self.ingest(db,'handoff',[record(1)])
            PaperInput(**result['items'][0]);self.assertEqual(result['format_version'],'a-paperinput/1')
            path=Path(self.tmp.name)/'export.json';export_json(result,path)
            self.assertEqual(path.with_suffix('.json.sha256').read_text().split()[0],hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):export_json(result,path)

    def test_annotations_only_change_is_an_update_with_stable_identity(self):
        with self.factory() as db:
            _,first=self.ingest(db,'before-annotations',[record(1)])
            _,second=self.ingest(db,'with-annotations',[record(1,keywords=[{'id':'https://openalex.org/keywords/test','display_name':'Computer vision'}])])
            self.assertEqual(second['counts']['updated'],1)
            self.assertEqual(first['stable_papers'][0]['paper_id'],second['stable_papers'][0]['paper_id'])
