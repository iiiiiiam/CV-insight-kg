import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from app.dblp import fetch_sparql
from app.formal_collection import coverage_report,digest,load_baseline


def count(n):return {'count':{'value':str(n)}}
def binding(pub,name,ordinal=1):
 return {'pub':{'value':'https://dblp.org/rec/conf/cvpr/'+pub},'title':{'value':pub},'doi':{'value':'https://doi.org/10.1234/'+pub},'author':{'value':name},'ordinal':{'value':str(ordinal)}}
def response(rows):
 r=Mock();r.json.return_value={'results':{'bindings':rows}};return r


class CollectionTests(unittest.TestCase):
 def test_dblp_exact_proceedings_pagination_and_author_order(self):
  session=Mock();session.get.side_effect=[response([count(2)]),response([binding('a','Bob',2),binding('a','Alice',1)]),response([binding('b','Carol')]),response([count(2)])]
  rows=fetch_sparql('CVPR',2024,session=session,page_size=1)
  self.assertEqual(rows[0]['authors'],['Alice','Bob']);self.assertEqual(rows[0]['doi'],'10.1234/a')
  self.assertIn('listedOnTocPage <https://dblp.org/db/conf/cvpr/cvpr2024>',session.get.call_args_list[0].kwargs['params']['query'])
  self.assertIn('OFFSET 1',session.get.call_args_list[2].kwargs['params']['query'])
 def test_duplicate_or_changing_remote_snapshot_is_rejected(self):
  session=Mock();session.get.side_effect=[response([count(2)]),response([binding('a','Alice')]),response([binding('a','Alice')])]
  with self.assertRaisesRegex(ValueError,'Duplicate'):fetch_sparql('CVPR',2024,session=session,page_size=1)
  session=Mock();session.get.side_effect=[response([count(1)]),response([binding('a','Alice')]),response([count(2)])]
  with self.assertRaisesRegex(ValueError,'changed'):fetch_sparql('CVPR',2024,session=session)
 def test_two_sources_do_not_inflate_frozen_denominator_or_matched_count(self):
  baseline={'venue':'CVPR','year':2024,'revision':'frozen','source_url':'https://official','expected_count':2,'papers':[{'title':'One paper'},{'title':'Missing paper'}]}
  rows=[{'source':source,'row':{'source_id':source,'title':'One paper','authors':['Alice'],'doi':'10.x/1','abstract':None}} for source in ('openalex','dblp')]
  report=coverage_report(baseline,rows,[{'source':'dblp','reason':'test'}])
  self.assertEqual((report['matched_papers'],report['coverage_ratio']),(1,0.5));self.assertEqual(len(report['missing']),1)
  self.assertEqual(report['missing'][0]['title'],'Missing paper');self.assertTrue(report['missing'][0]['reason'])
 def test_frozen_baseline_and_raw_html_tampering_are_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);body=b'<html>frozen</html>';(p/'baseline.html').write_bytes(body)
   baseline={'format_version':'a-coverage-baseline/1','venue':'CVPR','year':2024,'expected_count':1,'papers':[{'title':'One'}],'html_sha256':hashlib.sha256(body).hexdigest()};baseline['revision']=digest(baseline)
   (p/'baseline.json').write_text(json.dumps(baseline));self.assertEqual(load_baseline(p/'baseline.json')['expected_count'],1)
   (p/'baseline.html').write_bytes(body+b'!')
   with self.assertRaises(ValueError):load_baseline(p/'baseline.json')

 def test_strict_collection_requires_both_sources_before_freezing_input(self):
  from app.formal_collection import collect_scope,CollectionIncomplete
  from tests.test_formal_batches import record
  from requests import RequestException
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);raw=record(1)['row']['raw'];body=(json.dumps(raw)+'\n').encode()
   (root/'openalex.jsonl').write_bytes(body)
   (root/'openalex.manifest.json').write_text(json.dumps({'venue':'CVPR','year':2024,'source':'openalex','sha256':hashlib.sha256(body).hexdigest(),'count':1}))
   with patch('app.formal_collection.freeze_baseline'),patch('app.dblp.fetch_sparql',side_effect=RequestException('unavailable')):
    with self.assertRaises(CollectionIncomplete):collect_scope('CVPR',2024,root,require_all_sources=True)
   self.assertFalse((root/'formal-input.json').exists())
 def test_configured_source_parameters_reach_both_downloaders(self):
  from app.formal_collection import collect_scope
  from tests.test_formal_batches import record
  row=record(1)['row']
  baseline={'venue':'CVPR','year':2024,'revision':'frozen','source_url':'https://official','expected_count':1,'papers':[{'title':row['title']}]}
  with tempfile.TemporaryDirectory() as directory:
   def fetch(venue,year,path,**kwargs):path.write_text(json.dumps(row['raw'])+'\n');return {'count':1}
   with patch('app.formal_collection.freeze_baseline',return_value=baseline),patch('app.formal_collection.fetch_batch',side_effect=fetch) as oa,patch('app.dblp.fetch_sparql',return_value=[row]) as dblp:
    result=collect_scope('CVPR',2024,Path(directory),source_options={'openalex':{'page_size':30,'max_retries':2},'dblp':{'page_size':40,'max_retries':3}})
    self.assertEqual(oa.call_args.kwargs['page_size'],30);self.assertEqual(oa.call_args.kwargs['retries'],2)
    self.assertEqual(dblp.call_args.kwargs,{'page_size':40,'retries':3});self.assertEqual(result['records'],2)
