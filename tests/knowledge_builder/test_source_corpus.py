"""Corpus integration preserves old inputs, feedback reversibility and offline reads."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.knowledge_feedback import feedback_router
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.feedback import FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.source_corpus import FORMAT, load_corpus
from tests.knowledge_builder.test_source_enrichment import source


class SourceCorpusTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.directory / "corpus.json"
        self.vocabulary = load_vocabulary()
        self.original = PaperInput("https://openalex.org/W1", "Original paper", "Existing evidence.",
            2024, "CVPR", [{"author": {"display_name": "Ada Example"}}], "https://openalex.org/W1", "old")
        self.new = deepcopy(self.original)
        self.new.openalex_id = self.new.source_url = "https://openalex.org/W2"
        self.new.title = "StarNet and NewSet"
        self.record = source("paperswithcode", dict(title=self.new.title, authors=["Ada Example"],
            published="2024-01-01", methods=[dict(name="StarNet")], abstract_mentions=[
                dict(entity_type="dataset", name="NewSet", surface="NewSet")]))
        self.payload = dict(format_version=FORMAT, papers=[dict(paper=asdict(self.original), records=[]),
            dict(paper=asdict(self.new), records=[self.record])])
        self.write()

    def write(self):
        self.path.write_text(json.dumps(dict(payload=self.payload, sha256=fingerprint(self.payload))), encoding="utf-8")

    def workspace(self):
        papers, records = load_corpus(self.path, [self.original], self.vocabulary)
        results = {p.openalex_id: extract_candidates(p, self.vocabulary) for p in papers}
        return KnowledgeFeedback(papers, results, {}, self.vocabulary,
            FeedbackStore(self.directory / "feedback.json"), source_records=records)

    def test_expanded_reading_and_new_dataset_evidence_are_offline(self):
        with patch("requests.Session.get", side_effect=AssertionError("Runtime must not request sources")):
            workspace = self.workspace()
            self.assertEqual(len(workspace.list_papers()), 2)
            view = workspace.view(self.new.openalex_id)
        self.assertEqual({e["kind"] for e in view["source_enrichment"]["added_entities"]}, {"method", "dataset"})
        item = next(i for i in view["entities"] if i["content"]["name"] == "NewSet")
        self.assertEqual(item["evidence"][0]["quote"], "NewSet")
        self.assertEqual(view["paper"]["title"][item["evidence"][0]["start"]:item["evidence"][0]["end"]], "NewSet")
        self.assertFalse((self.directory / "feedback.json").exists())

    def test_source_candidate_can_be_corrected_reopened_and_withdrawn(self):
        workspace = self.workspace()
        view = workspace.view(self.new.openalex_id)
        candidate = next(i for i in view["entities"] if i["content"]["name"] == "StarNet")
        report = workspace.submit(self.new.openalex_id, view["revision"], "Rename", candidate_id=candidate["candidate_id"], owner_token="a" * 64)
        workspace.resolve(report["id"], revision=workspace.queue()["revision"], action="rename", reason="Example", reviewer="admin", name="StarNet corrected")
        self.assertIn("StarNet corrected", [i["content"]["name"] for i in workspace.view(self.new.openalex_id)["entities"]])
        workspace.reopen(report["id"], revision=workspace.queue()["revision"], reviewer="admin")
        self.assertEqual(workspace.view(self.new.openalex_id), view)
        workspace.withdraw(report["id"], owner_token="a" * 64)
        self.assertEqual(workspace.queue()["requests"], [])

    def test_corruption_duplicate_and_changed_original_are_rejected(self):
        self.payload["papers"][0]["paper"]["title"] = "Changed original"
        self.write()
        with self.assertRaisesRegex(ValueError, "preserve"):
            self.workspace()
        self.payload["papers"][0]["paper"] = asdict(self.original)
        self.payload["papers"].append(self.payload["papers"][0])
        self.write()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.workspace()
        self.path.write_text(json.dumps(dict(payload=self.payload, sha256="bad")), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.workspace()

    def test_api_opt_in_and_disabled_mode_keep_legacy_contract(self):
        snapshot = SimpleNamespace(papers=[self.original], results={self.original.openalex_id:
            extract_candidates(self.original, self.vocabulary)}, sessions={}, review_directory=self.directory)
        settings = SimpleNamespace(b_vocabulary_path=None, b_reviews_directory=None, b_source_corpus=str(self.path))
        app = FastAPI()
        app.include_router(feedback_router(settings))
        with patch("server.api.knowledge_feedback.KnowledgeSnapshot", return_value=snapshot), TestClient(app) as client:
            self.assertEqual(len(client.get("/api/knowledge/papers").json()), 2)
            response = client.get("/api/knowledge/paper", params=dict(paper_id=self.new.openalex_id))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["source_enrichment"]["added_entities"]), 2)
            settings.b_source_corpus = None
            self.assertEqual(len(client.get("/api/knowledge/papers").json()), 1)
            response = client.get("/api/knowledge/paper", params=dict(paper_id=self.original.openalex_id))
            self.assertNotIn("source_enrichment", response.json())
            settings.b_source_corpus = str(self.directory / "missing.json")
            self.assertEqual(client.get("/api/knowledge/papers").status_code, 503)
