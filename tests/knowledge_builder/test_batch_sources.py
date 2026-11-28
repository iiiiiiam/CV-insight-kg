"""Offline source enrichment parity, immutable input identity and withdrawal."""
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

from src.knowledge_builder.batch_sources import BatchSources, BatchSourcesInvalid, input_key
from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.enrichment_sources import SourceUnavailable
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.feedback import FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.source_corpus import FORMAT


def record(source, payload):
    return dict(source=source, url="https://example.test/source", fetched_at="2026-11-13T00:00:00+00:00",
                payload=payload, digest=fingerprint(payload))


class BatchSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.registry = BatchRegistry(self.directory/"ledger.json")
        self.sources = BatchSources(self.registry.path, offline=True, cache_path=self.directory/"cache")
        self.paper = PaperInput("https://openalex.org/W123", "StarNet for image segmentation",
            "We introduce StarNet and evaluate NewSet dataset.", 2024, "CVPR",
            [{"author":{"display_name":"Ada Example"}}], "https://openalex.org/W123", "original")
        self.records = [record("openalex", dict(id=self.paper.openalex_id, topics=[dict(
            id="https://openalex.org/T1", display_name="Image segmentation", score=.9)], keywords=[])),
            record("paperswithcode", dict(title=self.paper.title, authors=["Ada Example"], published="2024-01-01",
                tasks=[dict(name="Image segmentation")], methods=[dict(name="StarNet")],
                datasets=[dict(name="NewSet")]))]

    def batch(self, number, paper=None):
        return dict(format_version="a-paperinput/1", batch_id=number, batch_code=f"B{number}",
            total_papers=1, exported_papers=1, excluded_papers=0,
            items=[asdict(paper or self.paper)], excluded=[])

    def client(self):
        return Mock(openalex=Mock(return_value=self.records[0]), papers_with_code=Mock(return_value=self.records[1]))

    def annotated_batch(self, number, topic):
        document = self.batch(number)
        payload = dict(id=self.paper.openalex_id, display_name=self.paper.title,
                       publication_year=self.paper.year,
                       topics=[dict(id='https://openalex.org/T1', display_name=topic, score=.9)], keywords=[])
        annotation = record('openalex', payload)
        annotation['url']='https://api.openalex.org/works/W123'
        document['batch_revision']='revision-'+str(number)
        document['source_annotations']=[dict(paper_id=self.paper.openalex_id,record=annotation)]
        return document

    def test_a_annotations_reused_without_fetch_and_restored_on_withdrawal(self):
        first=self.annotated_batch(1,'Image segmentation')
        self.assertEqual(self.registry.ingest(first)['status'],'accepted')
        client=self.client()
        client.openalex.side_effect=AssertionError('A already supplied OpenAlex')
        client.papers_with_code.side_effect=SourceUnavailable('offline')
        self.sources.prepare([self.paper],client=client)
        client.openalex.assert_not_called()
        old=self.sources.records([self.paper])[self.paper.openalex_id]
        self.assertEqual(old[0]['payload']['topics'][0]['display_name'],'Image segmentation')
        self.registry.ingest(self.annotated_batch(2,'Object detection'))
        current=self.sources.records([self.paper])[self.paper.openalex_id]
        self.assertEqual(current[0]['payload']['topics'][0]['display_name'],'Object detection')
        self.registry.withdraw('B2')
        restored=self.sources.records([self.paper])[self.paper.openalex_id]
        self.assertEqual(restored,old)
        # Shared-input cache remains on disk; withdrawing all batches removes its A seeds.
        self.registry.withdraw('B1')
        self.assertEqual(self.registry.snapshot()['paper_count'],0)

    def test_bad_optional_a_annotations_do_not_block_usable_rule_results(self):
        document=self.annotated_batch(1,'Image segmentation')
        document['source_annotations'][0]['record']['digest']='0'*64
        self.assertEqual(self.registry.ingest(document)['status'],'accepted')
        self.assertEqual(self.sources.records([self.paper])[self.paper.openalex_id],[])
        workspace=self.registry.workspace(self.directory/'feedback.json',source_store=self.sources)
        self.assertIn('NewSet',{item['content']['name'] for item in workspace.view(self.paper.openalex_id)['entities']})
        self.assertEqual(workspace.export_effective()['counts']['papers'],1)

    def test_same_pipeline_as_existing_reading_and_no_network_on_view_export(self):
        client = self.client()
        summary = self.sources.prepare([self.paper], client=client)
        self.assertEqual((summary["completed"], summary["with_sources"], summary["partial"]), (1, 1, 0))
        self.registry.ingest(self.batch(1))
        workspace = self.registry.workspace(self.directory/"feedback.json", source_store=self.sources)
        normalized = PaperInput(**self.registry.snapshot()["papers"][0]["input"])
        vocabulary = load_vocabulary()
        old = KnowledgeFeedback([normalized], {normalized.openalex_id:extract_candidates(normalized, vocabulary)},
            {}, vocabulary, FeedbackStore(self.directory/"other.json"), source_records={normalized.openalex_id:self.records})
        self.assertEqual(workspace.view(normalized.openalex_id), old.view(normalized.openalex_id))
        self.assertEqual(workspace.export_effective()["revision"], old.export_effective()["revision"])
        self.sources.prepare([self.paper], client=client)
        self.assertEqual(client.openalex.call_count, 1)
        self.assertEqual(client.papers_with_code.call_count, 1)

    def test_source_failures_fallback_retry_and_preserve_good_records(self):
        client = self.client()
        client.papers_with_code.side_effect = SourceUnavailable("unavailable")
        self.sources.prepare([self.paper], client=client)
        self.assertEqual(self.sources.summary([self.paper])["partial"], 1)
        self.assertEqual(len(self.sources.records([self.paper])[self.paper.openalex_id]), 1)
        client.papers_with_code.side_effect = None
        self.sources.prepare([self.paper], client=client)
        self.assertEqual(self.sources.summary([self.paper])["partial"], 0)
        self.assertEqual(client.openalex.call_count, 1)
        self.assertEqual(client.papers_with_code.call_count, 2)

    def test_input_update_does_not_reuse_old_sources_and_withdraw_restores_them(self):
        self.registry.ingest(self.batch(1))
        self.sources.prepare([self.paper], client=self.client())
        before = self.registry.workspace(self.directory/"feedback.json").export_effective()["revision"]
        updated = deepcopy(self.paper)
        updated.title = "Object Detection with NewMethod"
        self.assertNotEqual(input_key(updated), input_key(self.paper))
        self.registry.ingest(self.batch(2, updated))
        self.assertEqual(self.sources.records([updated])[updated.openalex_id], [])
        self.assertEqual(self.sources.summary([updated])["pending"], 1)
        self.registry.withdraw("B2")
        self.assertEqual(self.registry.workspace(self.directory/"feedback.json").export_effective()["revision"], before)
        self.registry.withdraw("B1")
        self.assertEqual(self.registry.workspace(self.directory/"feedback.json").export_effective()["counts"]["papers"], 0)

    def test_seed_corpus_reused_without_modifying_original_or_network(self):
        payload = dict(format_version=FORMAT, papers=[dict(paper=asdict(self.paper), records=self.records)])
        corpus = self.directory/"corpus.json"
        corpus.write_text(json.dumps(dict(payload=payload, sha256=fingerprint(payload))), encoding="utf-8")
        original = corpus.read_bytes()
        sources = BatchSources(self.registry.path, corpus_path=corpus)
        normalized = deepcopy(self.paper)
        normalized.dataset_id = "b-paper:W123"
        client = self.client()
        self.assertEqual(sources.records([normalized])[normalized.openalex_id], self.records)
        sources.prepare([normalized], client=client)
        client.openalex.assert_not_called()
        client.papers_with_code.assert_not_called()
        self.assertEqual(corpus.read_bytes(), original)

    def test_corrupt_snapshot_fails_closed_and_wrong_paper_is_rejected(self):
        client = self.client()
        bad = deepcopy(self.records[0])
        bad["payload"]["id"] = "https://openalex.org/W999"
        bad["digest"] = fingerprint(bad["payload"])
        client.openalex.return_value = bad
        self.sources.prepare([self.paper], client=client)
        self.assertEqual([r["source"] for r in self.sources.records([self.paper])[self.paper.openalex_id]], ["paperswithcode"])
        path = next(self.sources.directory.glob("*.json"))
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(BatchSourcesInvalid):
            self.sources.records([self.paper])

    def test_offline_miss_is_recorded_and_rules_still_work(self):
        self.sources.prepare([self.paper])
        summary = self.sources.summary([self.paper])
        self.assertEqual((summary["completed"], summary["partial"], summary["with_sources"]), (1, 1, 0))
        self.registry.ingest(self.batch(1))
        view = self.registry.workspace(self.directory/"feedback.json").view(self.paper.openalex_id)
        self.assertIn("NewSet", {item["content"]["name"] for item in view["entities"]})
        self.assertIn("source_enrichment", view)

    def test_direction_catalog_matches_reading_and_counts_papers_once(self):
        self.registry.ingest(self.batch(1))
        self.sources.prepare([self.paper], client=self.client())
        workspace = self.registry.workspace(self.directory/"feedback.json")
        catalog = workspace.direction_catalog()
        self.assertEqual(len(catalog["directions"]), 18)
        expected = [{"id":d["source_id"], "name":d["name"]} for d in
            workspace.view(self.paper.openalex_id)["source_enrichment"]["source_classifications"]
            if d["kind"] == "research_direction"]
        self.assertEqual(catalog["papers"][0]["research_directions"], expected)
        self.assertEqual(next(d["count"] for d in catalog["directions"] if d["id"]==expected[0]["id"]),1)
