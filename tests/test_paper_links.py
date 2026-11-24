import json
import unittest
from types import SimpleNamespace
from app.paper_links import paper_homepage, safe_web_url

class PaperLinkTests(unittest.TestCase):
    def test_saved_landing_page_preferred_to_openalex_identifier(self):
        paper=SimpleNamespace(doi='10.1234/example', source_url='https://openalex.org/W123')
        source=SimpleNamespace(source='openalex',raw_json=json.dumps({'primary_location':{'landing_page_url':'https://publisher.example/paper/123'}}))
        self.assertEqual(paper_homepage(paper,[source]),'https://publisher.example/paper/123')
        official=SimpleNamespace(source='cvf',source_url='https://openaccess.thecvf.com/content/CVPR2024/html/example_paper.html')
        self.assertEqual(paper_homepage(paper,[source,official]),official.source_url)
    def test_doi_fallback_missing_and_unsafe_links(self):
        paper=SimpleNamespace(doi='10.1234/example',source_url=None)
        self.assertEqual(paper_homepage(paper,[]),'https://doi.org/10.1234/example')
        paper.doi=None;paper.source_url='https://openalex.org/W123'
        self.assertIsNone(paper_homepage(paper,[]))
        self.assertIsNone(safe_web_url('javascript:alert(1)'))
        self.assertIsNone(safe_web_url('https://user:password@example.org'))
