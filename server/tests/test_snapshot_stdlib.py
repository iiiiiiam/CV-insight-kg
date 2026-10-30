"""Runnable without installing third party packages: unittest this module."""

from dataclasses import asdict
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server.application.knowledge import KnowledgeSnapshot, UnknownSnapshotPaper
from server import init_local
from src.knowledge_builder.extraction import extract_candidates, validate_result


class SnapshotTests(unittest.TestCase):
    def test_all_twenty_outputs_match_b_and_all_evidence_validates(self):
        root = Path(__file__).resolve().parents[2]
        paths = [root / 'examples/week1_baseline.json', root / 'examples/cvpr_2024_seed.jsonl']
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        snapshot = KnowledgeSnapshot()
        self.assertEqual(len(snapshot.papers), 20)
        for paper in snapshot.papers:
            result = snapshot.results[paper.openalex_id]
            validate_result(paper, result)
            output = snapshot.candidates(paper.openalex_id)
            self.assertEqual(output['result'], asdict(extract_candidates(paper)))
            self.assertTrue(all(c['status'] == 'pending' for c in output['result']['entities'] + output['result']['relations']))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])

    def test_overview_counts_are_computed_and_unconfirmed(self):
        snapshot = KnowledgeSnapshot()
        overview = snapshot.overview()
        self.assertEqual(overview['entity_count'], sum(len(r.entities) for r in snapshot.results.values()))
        self.assertEqual(overview['relation_count'], sum(len(r.relations) for r in snapshot.results.values()))
        self.assertEqual(overview['confirmed_count'], 0)
        self.assertEqual(overview['entity_counts'].get('topic', 0), 0)
        self.assertTrue(overview['read_only'])

    def test_unknown_paper_is_not_synthesized(self):
        with self.assertRaises(UnknownSnapshotPaper):
            KnowledgeSnapshot().candidates('missing')

    def test_response_mutation_does_not_change_cached_candidates(self):
        snapshot = KnowledgeSnapshot()
        paper_id = snapshot.papers[0].openalex_id
        first = snapshot.candidates(paper_id)
        first['result']['entities'].clear()
        self.assertTrue(snapshot.candidates(paper_id)['result']['entities'])

    def test_initialization_keeps_existing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_bytes((init_local.ROOT / '.env.example').read_bytes())
            with patch.object(init_local, 'ROOT', root), patch('builtins.print'):
                init_local.initialize()
                first = (root / '.env').read_bytes()
                init_local.initialize()
                self.assertEqual(first, (root / '.env').read_bytes())
                self.assertNotIn(b'ADMIN_PASSWORD=\n', first)
                self.assertNotIn(b'A_ADMIN_TOKEN=\n', first)


if __name__ == '__main__':
    unittest.main()
