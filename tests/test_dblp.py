import json
import unittest
from unittest.mock import Mock,patch
import requests
from app.dblp import DblpAccessError,fetch_search
from app.ingest import fetch_dblp


def response(payload=None,status=200,body=None):
    r=requests.Response();r.status_code=status
    r.headers['Content-Type']='text/html' if body is not None else 'application/json'
    r._content=body.encode() if body is not None else json.dumps(payload).encode()
    return r


def page(keys,total,first=0):
    return response({'result':{'hits':{'@total':str(total),'@first':str(first),'@sent':str(len(keys)),
            'hit':[{'info':{'key':key,'year':'2024','type':'Conference and Workshop Papers','title':'A Paper.',
                           'authors':{'author':{'text':'Alice'}},'ee':'https://doi.org/10.1000/PAPER'}} for key in keys]}}})


class DblpTests(unittest.TestCase):
    def test_challenge_is_not_retried_or_imported(self):
        session=Mock();session.get.return_value=response(status=202,body='<html>Making sure you are not a bot!</html>')
        with self.assertRaisesRegex(DblpAccessError,'DBLP_ACCESS_CHALLENGE'):
            fetch_dblp('CVPR',2024,session,retries=3)
        self.assertEqual(session.get.call_count,1)

    @patch('app.dblp.time.sleep')
    def test_search_paginates_and_preserves_source_metadata(self,_):
        session=Mock();session.get.side_effect=[page(['conf/cvpr/A24'],2),page(['conf/cvpr/B24'],2,1)]
        rows=fetch_search('CVPR',2024,session,page_size=1)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['doi'],'10.1000/paper')
        self.assertEqual(rows[0]['authors'],['Alice'])
        self.assertIn('dblp_search_info',rows[0]['raw'])
        self.assertEqual(session.get.call_args.kwargs['params']['f'],1)
        self.assertEqual(session.get.call_args.kwargs['params']['q'],'toc:db/conf/cvpr/cvpr2024.bht:')

    @patch('app.dblp.time.sleep')
    def test_incomplete_duplicate_or_changed_pages_are_rejected(self,_):
        for second in [page([],2,1),page(['conf/cvpr/A24'],2,1),page(['conf/cvpr/B24'],3,1)]:
            session=Mock();session.get.side_effect=[page(['conf/cvpr/A24'],2),second]
            with self.assertRaises(ValueError):fetch_search('CVPR',2024,session,page_size=1)

    def test_wrong_conference_is_rejected(self):
        session=Mock();session.get.return_value=page(['conf/iccv/A24'],1)
        with self.assertRaisesRegex(ValueError,'scope'):fetch_search('CVPR',2024,session)

    def test_xml_failure_uses_official_search_api(self):
        session=Mock();session.get.side_effect=[response(status=404,body='Not found'),page(['conf/cvpr/A24'],1)]
        rows=fetch_dblp('CVPR',2024,session,retries=1)
        self.assertEqual(rows[0]['dblp_key'],'conf/cvpr/A24')
        self.assertTrue(session.get.call_args.args[0].endswith('/search/publ/api'))
