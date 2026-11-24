"""All writes are isolated program tests; no real review decisions are created."""

from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from server.application.knowledge import (KnowledgeSnapshot, KnowledgeSnapshotChanged,
                                          KnowledgeReviewRejected, KnowledgeReviewStorageError)
from src.knowledge_builder.export_io import load_exports
from src.knowledge_builder.models import Entity, Relation
from src.knowledge_builder.review_storage import save_review


class KnowledgeWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.snapshot = self.read()
        self.paper_id = self.snapshot.papers[0].openalex_id
        session = self.snapshot.sessions[self.paper_id]
        self.root = next(c.candidate_id for c in session.items if isinstance(c.content, Entity) and c.content.kind == 'paper')
        self.task = next(c.candidate_id for c in session.items if isinstance(c.content, Entity) and c.content.kind == 'task')
        self.author = next(c.candidate_id for c in session.items if isinstance(c.content, Entity) and c.content.kind == 'author')
        self.relation = next(c.candidate_id for c in session.items if isinstance(c.content, Relation) and c.content.kind == 'mentions_task')

    def read(self):
        return KnowledgeSnapshot(reviews_directory=self.directory)

    def act(self, candidate, action, **kwargs):
        snapshot = self.read()
        return snapshot.apply_review(self.paper_id, candidate, action, reviewer='D-authenticated-program-test',
                                     reason='Program test only; not real human annotation',
                                     snapshot_revision=snapshot.snapshot_revision, **kwargs)

    def confirm_relation(self):
        for item in (self.root, self.task, self.relation):
            self.act(item, 'confirm')

    def test_rename_confirm_and_restore_preserve_original_and_actor(self):
        raw = asdict(self.snapshot.results[self.paper_id])
        self.act(self.task, 'correct', name='程序测试改名')
        self.act(self.task, 'confirm')
        restored = self.read()
        session = restored.sessions[self.paper_id]
        self.assertEqual(session.get(self.task).status, 'confirmed')
        self.assertEqual(session.get(self.task).content.name, '程序测试改名')
        self.assertEqual(asdict(restored.results[self.paper_id]), raw)
        self.assertEqual([e.reviewer for e in session.history], ['D-authenticated-program-test'] * 2)
        self.assertEqual([e.action for e in session.history], ['correct', 'confirm'])

    def test_relation_confirmation_needs_both_endpoints_and_failure_does_not_write(self):
        with self.assertRaisesRegex(KnowledgeReviewRejected, '两端'):
            self.act(self.relation, 'confirm')
        self.assertEqual(list(self.directory.iterdir()), [])
        self.confirm_relation()
        self.assertEqual(self.read().sessions[self.paper_id].get(self.relation).status, 'confirmed')

    def test_reopen_returns_dependent_relationships_to_pending(self):
        self.confirm_relation()
        result = self.act(self.task, 'reopen')
        self.assertEqual(set(result['affected_candidate_ids']), {self.task, self.relation})
        session = self.read().sessions[self.paper_id]
        self.assertEqual(session.get(self.relation).status, 'pending')
        self.assertEqual(session.history[-1].action, 'reopen_dependency')

    def test_stale_browser_and_first_save_race_cannot_overwrite(self):
        stale = self.read()
        self.act(self.root, 'confirm')
        with self.assertRaises(KnowledgeSnapshotChanged):
            stale.apply_review(self.paper_id, self.task, 'confirm', reviewer='stale-test', reason='Program test',
                               snapshot_revision=stale.snapshot_revision)
        self.assertEqual(len(self.read().sessions[self.paper_id].history), 1)
        fresh = self.read()
        with self.assertRaises(KnowledgeSnapshotChanged):
            fresh.apply_review(self.paper_id, self.task, 'confirm', reviewer='stale-test', reason='Program test',
                               snapshot_revision=stale.snapshot_revision)

    def test_custom_archive_name_is_updated_in_place_and_locked_archive_is_not_touched(self):
        path = self.directory / 'custom.json'
        save_review(path, self.snapshot.sessions[self.paper_id])
        self.act(self.root, 'confirm')
        self.assertEqual(list(self.directory.glob('*.json')), [path])
        body = path.read_bytes()
        lock = path.with_name(path.name + '.lock')
        lock.write_text('another-program-test-writer', encoding='utf-8')
        with self.assertRaises(KnowledgeSnapshotChanged):
            self.act(self.task, 'confirm')
        self.assertEqual(path.read_bytes(), body)
        self.assertTrue(lock.exists())

    def test_business_or_disk_failures_do_not_change_archive_or_in_memory_state(self):
        snapshot = self.read()
        with self.assertRaises(KnowledgeReviewRejected):
            snapshot.apply_review(self.paper_id, self.task, 'confirm', reviewer='test', reason=' ', snapshot_revision=snapshot.snapshot_revision)
        with self.assertRaises(KnowledgeReviewRejected):
            snapshot.apply_review(self.paper_id, self.relation, 'correct', name='invalid', reviewer='test', reason='Program test', snapshot_revision=snapshot.snapshot_revision)
        with patch('server.application.knowledge.save_review', side_effect=PermissionError('program test')):
            with self.assertRaises(KnowledgeReviewStorageError):
                snapshot.apply_review(self.paper_id, self.root, 'confirm', reviewer='test', reason='Program test', snapshot_revision=snapshot.snapshot_revision)
        self.assertEqual(snapshot.sessions[self.paper_id].get(self.root).status, 'pending')
        self.assertFalse(snapshot.sessions[self.paper_id].history)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_three_json_downloads_and_zip_use_b_schema_checksums_and_state_partition(self):
        self.confirm_relation()
        self.act(self.author, 'reject')
        snapshot = self.read()
        archives_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.glob('*.json')}
        for status in ('confirmed', 'pending', 'rejected'):
            body, media, name = snapshot.download(status + '.json', snapshot.snapshot_revision)
            document = json.loads(body)
            self.assertEqual(document['status'], status)
            self.assertEqual(media, 'application/json')
            self.assertEqual(name, 'b-' + status + '.json')
            for paper in document['papers']:
                self.assertTrue(all(record['item']['status'] == status for record in paper['entities'] + paper['relations']))
        body, media, name = snapshot.download('bundle.zip', snapshot.snapshot_revision)
        self.assertEqual((media, name), ('application/zip', 'b-knowledge.zip'))
        target = self.directory / 'export-check'
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {'confirmed.json', 'pending.json', 'rejected.json', 'schema.json', 'manifest.json'})
            for member in archive.namelist():
                (target / member).write_bytes(archive.read(member))
        bundle = load_exports(target, snapshot.papers)
        self.assertEqual(bundle['confirmed']['counts']['relations'], 1)
        self.assertEqual(bundle['rejected']['counts']['entities'], 1)
        self.assertEqual(archives_before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.glob('*.json')})

    def test_public_detail_exposes_only_confirmed_items_without_private_review_metadata(self):
        self.act(self.task, 'correct', name='程序测试公开名称')
        self.confirm_relation()
        self.act(self.author, 'reject')
        snapshot = self.read()
        output = snapshot.confirmed(self.paper_id)
        self.assertEqual(len(output['entities']), 2)
        self.assertEqual(len(output['relations']), 1)
        self.assertTrue(all(item['status'] == 'confirmed' for item in output['entities'] + output['relations']))
        self.assertIn('程序测试公开名称', json.dumps(output, ensure_ascii=False))
        def all_keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(all_keys(item) for item in value.values()), set())
            if isinstance(value, list):
                return set().union(*(all_keys(item) for item in value), set())
            return set()
        self.assertFalse({'reviewer', 'reason', 'history'} & all_keys(output))
        self.act(self.task, 'reopen')
        self.assertEqual(self.read().confirmed(self.paper_id)['relations'], [])

    def test_no_confirmation_is_fabricated_and_out_of_scope_is_explicit(self):
        output = self.read().confirmed(self.paper_id)
        self.assertTrue(output['supported'])
        self.assertEqual(output['entities'], [])
        self.assertFalse(self.read().confirmed('https://openalex.org/NOT-IN-FIXED-SAMPLE')['supported'])
        snapshot = self.read()
        with self.assertRaises(KnowledgeSnapshotChanged):
            snapshot.download('bundle.zip', '0' * 64)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
