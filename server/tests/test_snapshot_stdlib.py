"""D/B adapter tests use real inputs and isolated, explicitly synthetic review archives."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server.application.knowledge import (KnowledgeSnapshot, UnknownSnapshotPaper,
                                          KnowledgeSnapshotInvalid, KnowledgeSnapshotChanged)
from server import init_local
from src.knowledge_builder.extraction import extract_candidates, validate_result
from src.knowledge_builder.models import Entity, Relation
from src.knowledge_builder.review_storage import save_review


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def snapshot(self, **kwargs):
        return KnowledgeSnapshot(reviews_directory=self.directory, **kwargs)

    def save_test_decisions(self, snapshot):
        identifier = snapshot.papers[0].openalex_id
        session = snapshot.sessions[identifier]
        root = next(c for c in session.items if isinstance(c.content, Entity) and c.content.kind == 'paper')
        task = next(c for c in session.items if isinstance(c.content, Entity) and c.content.kind == 'task')
        relation = next(c for c in session.items if isinstance(c.content, Relation) and c.content.kind == 'mentions_task')
        actor = {'reviewer': 'D-program-test', 'reason': 'Program test only, not real human annotation'}
        session.correct(task.candidate_id, name='程序测试显示名', **actor)
        for item in (root, task, relation):
            session.confirm(item.candidate_id, **actor)
        save_review(self.directory / 'custom-review.json', session)
        return identifier, task.candidate_id, relation.candidate_id

    def test_all_twenty_outputs_match_b_and_all_evidence_validates(self):
        root = Path(__file__).resolve().parents[2]
        paths = [root / 'examples/week1_baseline.json', root / 'examples/cvpr_2024_seed.jsonl']
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot.papers), 20)
        for paper in snapshot.papers:
            result = snapshot.results[paper.openalex_id]
            validate_result(paper, result)
            output = snapshot.candidates(paper.openalex_id)
            self.assertEqual(output['result'], asdict(extract_candidates(paper)))
            self.assertTrue(all(c['status'] == 'pending' for c in output['result']['entities'] + output['result']['relations']))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])

    def test_counts_follow_actual_b_categories_without_inventing_or_suppressing_topics(self):
        snapshot = self.snapshot()
        overview = snapshot.overview()
        actual = Counter(c.entity.kind for r in snapshot.results.values() for c in r.entities)
        self.assertEqual(overview['entity_counts'], dict(actual))
        self.assertEqual(overview['entity_count'], sum(actual.values()))
        self.assertEqual(overview['relation_count'], sum(len(r.relations) for r in snapshot.results.values()))
        self.assertEqual(overview['confirmed_count'], 0)
        self.assertTrue(overview['read_only'])
        self.assertEqual(overview['review_counts']['pending']['entities'], overview['entity_count'])
        self.assertEqual(list(self.directory.iterdir()), [])  # Reads never create archives.

    def test_saved_review_is_separate_from_original_and_history_is_preserved(self):
        original = self.snapshot()
        identifier, task_id, _ = self.save_test_decisions(original)
        restored = self.snapshot()
        output = restored.candidates(identifier)
        current = next(item for item in output['review']['items'] if item['candidate_id'] == task_id)
        raw = next(item for item in output['result']['entities'] if item['candidate_id'] == task_id)
        self.assertEqual(current['content']['name'], '程序测试显示名')
        self.assertEqual(current['status'], 'confirmed')
        self.assertNotEqual(raw['entity']['name'], current['content']['name'])
        self.assertEqual(raw['status'], 'pending')
        self.assertEqual(output['confirmed_count'], 3)
        self.assertEqual(output['review']['counts']['confirmed'], {'entities': 2, 'relations': 1})
        self.assertEqual(len(output['review']['history']), 4)
        self.assertEqual(output['review']['history'][0]['reviewer'], 'D-program-test')
        self.assertEqual(output['review']['history'], [asdict(e) for e in original.sessions[identifier].history])
        self.assertTrue(output['review']['archive_revision'])

    def test_refresh_changes_revision_and_stale_cross_request_read_is_rejected(self):
        before = self.snapshot()
        self.assertEqual(before.snapshot_revision, self.snapshot().snapshot_revision)
        identifier, _, _ = self.save_test_decisions(before)
        after = self.snapshot()
        self.assertNotEqual(before.snapshot_revision, after.snapshot_revision)
        self.assertEqual(after.overview()['confirmed_count'], 3)
        with self.assertRaises(KnowledgeSnapshotChanged):
            after.candidates(identifier, before.snapshot_revision)
        self.assertEqual(after.candidates(identifier, after.snapshot_revision)['confirmed_count'], 3)

    def test_reopened_endpoint_reflects_dependent_relation_and_history(self):
        before = self.snapshot()
        identifier, task_id, relation_id = self.save_test_decisions(before)
        snapshot = self.snapshot()
        session = snapshot.sessions[identifier]
        session.reopen(task_id, reviewer='D-program-test', reason='Program test only')
        save_review(self.directory / 'custom-review.json', session,
                    expected_revision=snapshot.archive_revisions[identifier])
        response = self.snapshot().candidates(identifier)
        self.assertEqual(next(c for c in response['review']['items'] if c['candidate_id'] == relation_id)['status'], 'pending')
        self.assertIn('reopen_dependency', [e['action'] for e in response['review']['history']])

    def test_corrupt_archive_is_rejected_without_overwrite_or_fallback(self):
        path = self.directory / 'broken.json'
        body = b'{invalid json'
        path.write_bytes(body)
        with self.assertRaises(KnowledgeSnapshotInvalid):
            self.snapshot()
        self.assertEqual(path.read_bytes(), body)

    def test_old_archive_requires_explicit_matching_vocabulary(self):
        vocabulary = Path(__file__).resolve().parents[2] / 'examples/knowledge_builder/vocabulary_v0.1.json'
        old = self.snapshot(vocabulary_path=vocabulary)
        identifier, _, _ = self.save_test_decisions(old)
        with self.assertRaises(KnowledgeSnapshotInvalid):
            self.snapshot()
        restored = self.snapshot(vocabulary_path=vocabulary)
        self.assertEqual(restored.candidates(identifier)['confirmed_count'], 3)
        self.assertEqual(restored.overview()['vocabulary_version'], 'cv-terms/0.1')

    def test_input_or_vocabulary_change_invalidates_archive(self):
        before = self.snapshot()
        self.save_test_decisions(before)
        root = Path(__file__).resolve().parents[2]
        vocabulary = json.loads((root / 'src/knowledge_builder/vocabulary.json').read_text(encoding='utf-8'))
        vocabulary['version'] += '-program-test'
        path = self.directory / 'vocabulary.txt'  # Not scanned as a review archive.
        path.write_text(json.dumps(vocabulary), encoding='utf-8')
        with self.assertRaises(KnowledgeSnapshotInvalid):
            self.snapshot(vocabulary_path=path)

    def test_unknown_paper_is_not_synthesized(self):
        with self.assertRaises(UnknownSnapshotPaper):
            self.snapshot().candidates('missing')

    def test_response_mutation_does_not_change_cached_candidates(self):
        snapshot = self.snapshot()
        paper_id = snapshot.papers[0].openalex_id
        first = snapshot.candidates(paper_id)
        first['result']['entities'].clear()
        first['review']['items'].clear()
        self.assertTrue(snapshot.candidates(paper_id)['result']['entities'])
        self.assertTrue(snapshot.candidates(paper_id)['review']['items'])

    def test_initialization_keeps_existing_credentials(self):
        (self.directory / '.env.example').write_bytes((init_local.ROOT / '.env.example').read_bytes())
        with patch.object(init_local, 'ROOT', self.directory), patch('builtins.print'):
            init_local.initialize()
            first = (self.directory / '.env').read_bytes()
            init_local.initialize()
            self.assertEqual(first, (self.directory / '.env').read_bytes())
            self.assertNotIn(b'ADMIN_PASSWORD=\n', first)
            self.assertNotIn(b'A_ADMIN_TOKEN=\n', first)


if __name__ == '__main__':
    unittest.main()
