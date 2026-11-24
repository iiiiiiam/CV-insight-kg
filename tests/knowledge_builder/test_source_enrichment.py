"""Offline fixtures verify source gates; no external annotations are accepted by hand."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.fetch_openalex_batch import ANNOTATION_FIELDS, FIELDS, fetch_batch
from src.knowledge_builder.enrichment_sources import SourceClient, SourceUnavailable, same_paper
from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.source_enrichment import analyze_sources
from src.knowledge_builder.curated_vocabulary import load_curated_vocabulary, merge_curated_vocabulary


def source(name, payload):
    return dict(source=name, url="https://example.test/record", fetched_at="2026-11-08T00:00:00+00:00",
                payload=payload, digest=fingerprint(payload))


class SourceEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.paper = PaperInput("https://openalex.org/W123", "StarNet for detection",
            "We introduce StarNet and evaluate NewSet. We also study fine-grained image classification.",
            2024, "CVPR", [{"author":{"display_name":"Ada Example"}}], "https://openalex.org/W123", "fixture")
        self.vocabulary = load_vocabulary()

    def catalog(self, **extra):
        return source("paperswithcode", dict(title=self.paper.title, authors=["Ada Example"], published="2024-01-01", **extra))

    def test_no_source_keeps_exact_old_input_and_result(self):
        original = deepcopy(self.paper)
        report = analyze_sources(self.paper, self.vocabulary, [])
        self.assertEqual(report["enriched"], asdict(extract_candidates(self.paper, self.vocabulary)))
        self.assertEqual(report["baseline"], report["enriched"])
        self.assertEqual(self.paper, original)

    def test_curated_fallback_recognizes_aliases_without_sources_but_not_substrings(self):
        self.paper.abstract = "CIFAR100 with ResNet50 and ViT. OtherSet and notCIFAR100ish are not known."
        before = deepcopy(self.vocabulary)
        report = analyze_sources(self.paper, self.vocabulary, [], fallback=True)
        self.assertEqual({e["name"] for e in report["added_entities"]}, {"CIFAR-100", "ResNet", "Vision Transformer"})
        self.assertEqual(self.vocabulary, before)
        self.assertEqual({p["quote"] for t in report["fallback_matches"] for p in t["matched_evidence"]},
                         {"CIFAR100", "ResNet50", "ViT"})
        self.assertTrue(all(t["source_url"].startswith("https://") for t in load_curated_vocabulary()["terms"]))

    def test_curated_fallback_does_not_override_existing_identity(self):
        vocabulary = deepcopy(self.vocabulary)
        vocabulary["terms"].append(dict(key="existing-resnet", kind="method", name="ResNet", aliases=["ResNet"]))
        merged, _ = merge_curated_vocabulary(vocabulary)
        resnet = [t for t in merged["terms"] if t["name"] == "ResNet"]
        self.assertEqual(len(resnet), 1)
        self.assertEqual(resnet[0]["key"], "existing-resnet")
        self.assertIn("ResNet50", resnet[0]["aliases"])

    def test_lowercase_video_clip_is_not_the_clip_model(self):
        self.paper.abstract = "We clip the values and examine a video clip."
        report = analyze_sources(self.paper, self.vocabulary, [], fallback=True)
        self.assertNotIn("CLIP", {e["name"] for e in report["added_entities"]})

    def test_external_classification_is_not_invented_text_evidence(self):
        record = source("openalex", dict(id=self.paper.openalex_id,
            topics=[dict(id="https://openalex.org/T1",display_name="Broad source classification",score=.9)], keywords=[]))
        report = analyze_sources(self.paper, self.vocabulary, [record])
        self.assertEqual(len([t for t in report["source_classifications"] if t["kind"] == "topic"]), 1)
        self.assertEqual(report["enriched"], report["baseline"])
        self.assertEqual(report["source_classifications"][0]["basis"], "source_classification")

    def test_topic_hierarchy_preserves_shared_parent_without_inventing_entities(self):
        parent = dict(id="https://openalex.org/subfields/1707", display_name="Computer Vision")
        record = source("openalex", dict(id=self.paper.openalex_id, topics=[
            dict(id="https://openalex.org/T1", display_name="Research topic one", subfield=parent,
                 field=dict(id="https://openalex.org/fields/17", display_name="Computer Science")),
            dict(id="https://openalex.org/T2", display_name="Research topic two", subfield=parent)]))
        original = deepcopy(record)
        report = analyze_sources(self.paper, self.vocabulary, [record])
        topics = [t for t in report["source_classifications"] if t["kind"] == "topic"]
        self.assertEqual(len(topics), 2)
        self.assertEqual([t["hierarchy"]["subfield"]["source_id"] for t in topics], [parent["id"]] * 2)
        self.assertEqual(topics[1]["hierarchy"]["subfield"]["source_path"], ["topics", 1, "subfield"])
        self.assertEqual(topics[0]["hierarchy"]["field"]["name"], "Computer Science")
        self.assertEqual(report["enriched"], report["baseline"])
        self.assertEqual(record, original)

    def test_missing_or_incomplete_parent_does_not_create_a_fake_classification(self):
        record = source("openalex", dict(id=self.paper.openalex_id, topics=[
            dict(id="https://openalex.org/T1", display_name="Research topic", subfield=None,
                 field=dict(display_name="Missing ID"), domain="not an object")]))
        topic = analyze_sources(self.paper, self.vocabulary, [record])["source_classifications"][0]
        self.assertNotIn("hierarchy", topic)

    def test_catalog_tasks_form_one_level_directions_with_source_paths(self):
        record = self.catalog(tasks=[dict(name="Image segmentation"), dict(name="Instance Segmentation"),
            dict(name="Object Detection"), dict(name="  image   CLASSIFICATION ")])
        report = analyze_sources(self.paper, self.vocabulary, [record])
        directions = report["source_classifications"]
        # Only classification has corroboration in this fixture's abstract.
        self.assertEqual({t["name"] for t in directions}, {"图像分类"})
        self.paper.title = "Image Segmentation with Instance Segmentation"
        record["payload"]["title"] = self.paper.title
        record["digest"] = fingerprint(record["payload"])
        directions = analyze_sources(self.paper, self.vocabulary, [record])["source_classifications"]
        segmentation = next(t for t in directions if t["name"] == "图像分割")
        task_signals = [s for s in segmentation["mapped_from"] if s["channel"] == "task"]
        self.assertEqual(len(task_signals), 2)
        self.assertEqual(task_signals[1]["source_path"], ["tasks", 1])
        self.assertEqual(task_signals[0]["source_digest"], record["digest"])
        self.assertTrue(all(t["kind"] == "research_direction" and t["parent_name"] == "计算机视觉"
                            for t in directions))
        # Source classification need not occur literally in our abstract; it is
        # not converted into an invented mentions_task/mentions_topic relation.
        self.assertEqual(report["enriched"], report["baseline"])

    def test_unknown_and_generic_non_visual_tasks_do_not_get_guessed_directions(self):
        report = analyze_sources(self.paper, self.vocabulary, [self.catalog(tasks=[
            dict(name="Language Modeling"), dict(name="Retrieval"), dict(name="FutureTask"),
            dict(name="Reinforcement Learning"), {}, None])])
        self.assertEqual([t["name"] for t in report["source_classifications"]], ["其他"])

    def test_typed_catalog_mentions_add_method_dataset_and_real_character_evidence(self):
        record = self.catalog(methods=[dict(name="StarNet")], abstract_mentions=[
            dict(entity_type="dataset", name="NewSet", surface="NewSet", start=9999,end=10000)])
        original = deepcopy(self.vocabulary)
        report = analyze_sources(self.paper, self.vocabulary, [record])
        self.assertEqual({e["kind"] for e in report["added_entities"]}, {"method", "dataset"})
        self.assertEqual(self.vocabulary, original)
        for candidate in report["enriched"]["entities"]:
            for proof in candidate["evidence"]:
                if proof["field"] in ("title", "abstract"):
                    text = getattr(self.paper, proof["field"])
                    self.assertEqual(text[proof["start"]:proof["end"]], proof["quote"])

    def test_catalog_labels_absent_from_our_text_do_not_become_relations(self):
        report = analyze_sources(self.paper, self.vocabulary, [self.catalog(methods=[dict(name="UnmentionedBERT")])])
        self.assertEqual(report["enriched"], report["baseline"])
        self.assertEqual(report["ignored_signals"][0]["reason"], "not_in_frozen_title_or_abstract")

    def test_benchmark_labels_add_only_textual_datasets_and_reuse_known_keys(self):
        self.paper.abstract = "Experiments on CIFAR100 and COCO. NewSet is a task."
        record = self.catalog(evaluated_benchmarks=["CIFAR-100 (test)", "COCO (val2017)", "NewSet (test)"])
        report = analyze_sources(self.paper, self.vocabulary, [record], fallback=True)
        self.assertEqual([(e["kind"], e["name"]) for e in report["added_entities"]], [("dataset", "CIFAR-100")])
        self.assertEqual(sum(e["entity"]["name"] == "COCO" for e in report["enriched"]["entities"]), 1)
        signal = next(s for s in report["accepted_signals"] if s["name"] == "CIFAR-100")
        self.assertEqual(signal["matched_evidence"][0]["quote"], "CIFAR100")
        self.assertEqual(signal["source_path"], ["evaluated_benchmarks", 0])
        self.assertTrue(any(s["reason"] == "benchmark_dataset_type_unknown" for s in report["ignored_signals"]))

    def test_unknown_benchmark_needs_dataset_context_not_just_a_matching_word(self):
        self.paper.abstract = "We test the NewSet dataset. AnotherTask evaluates speed."
        record = self.catalog(evaluated_benchmarks=["NewSet (test)", "AnotherTask"])
        report = analyze_sources(self.paper, self.vocabulary, [record])
        self.assertEqual([e["name"] for e in report["added_entities"]], ["NewSet"])

    def test_source_metrics_are_not_misclassified_as_methods(self):
        self.paper.abstract = "We report FID and PSNR."
        report = analyze_sources(self.paper, self.vocabulary, [self.catalog(methods=[dict(name="FID"), dict(name="PSNR")])])
        self.assertEqual(report["added_entities"], [])
        self.assertEqual({s["reason"] for s in report["ignored_signals"]}, {"source_metric_or_generic_label_not_method"})

    def test_unknown_keywords_stay_untyped_but_task_suffix_can_be_tested(self):
        record = source("openalex", dict(id=self.paper.openalex_id, topics=[],keywords=[
            dict(display_name="StarNet"),dict(display_name="fine-grained image classification")]))
        report = analyze_sources(self.paper, self.vocabulary, [record])
        self.assertEqual([e["kind"] for e in report["added_entities"]], ["task"])
        self.assertTrue(any(i["reason"] == "keyword_type_unknown" for i in report["ignored_signals"]))

    def test_alias_conflicts_do_not_retype_a_known_dataset_as_method(self):
        self.paper.abstract = "Experiments on COCO."
        report = analyze_sources(self.paper, self.vocabulary, [self.catalog(methods=[dict(name="COCO")])])
        self.assertEqual(report["enriched"], report["baseline"])
        self.assertEqual(report["ignored_signals"][0]["reason"], "alias_type_or_identity_conflict")

    def test_source_identity_and_digest_are_checked(self):
        record = source("openalex", dict(id="https://openalex.org/W999",topics=[]))
        with self.assertRaisesRegex(ValueError, "another"):
            analyze_sources(self.paper,self.vocabulary,[record])
        record = self.catalog(methods=[])
        record["payload"]["title"] = "Different paper"
        with self.assertRaisesRegex(ValueError, "checksum"):
            analyze_sources(self.paper,self.vocabulary,[record])
        record["digest"] = fingerprint(record["payload"])
        with self.assertRaisesRegex(ValueError, "another"):
            analyze_sources(self.paper,self.vocabulary,[record])

    def test_title_only_match_is_insufficient(self):
        self.assertFalse(same_paper(self.paper,dict(title=self.paper.title,authors=["Someone Else"],published="2024-01-01")))
        self.assertTrue(same_paper(self.paper,dict(title=self.paper.title,authors=["Ada Example"],published="2023-01-01")))

    def test_longer_source_alias_never_erases_existing_baseline_mentions(self):
        self.paper.abstract="Real-time object detection is studied."
        record=source("openalex",dict(id=self.paper.openalex_id,topics=[],
            keywords=[dict(display_name="Real-time object detection")]))
        report=analyze_sources(self.paper,self.vocabulary,[record])
        before={i["candidate_id"] for i in report["baseline"]["entities"]}
        after={i["candidate_id"] for i in report["enriched"]["entities"]}
        self.assertTrue(before <= after)
        self.assertEqual(len(after)-len(before),len(report["added_entities"]))


class SourceCacheTests(unittest.TestCase):
    def test_credentials_are_not_cached_and_second_read_is_offline(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ",{"OPENALEX_API_KEY":"secret-test"}), patch("time.sleep"):
            session = Mock()
            session.get.return_value = Mock(ok=True,status_code=200,json=Mock(return_value={"id":"example"}))
            client = SourceClient(directory,session=session)
            first = client.read("openalex","https://api.openalex.org/works/W123",{"select":"id"})
            self.assertEqual(session.get.call_args.kwargs["params"]["api_key"],"secret-test")
            self.assertNotIn("secret-test",next(Path(directory).rglob("*.json")).read_text(encoding="utf-8"))
            offline = SourceClient(directory,session=Mock(),offline=True)
            self.assertEqual(offline.read("openalex","https://api.openalex.org/works/W123",{"select":"id"}),first)
            offline.session.get.assert_not_called()

    def test_missing_or_corrupt_cache_never_silently_uses_network(self):
        with tempfile.TemporaryDirectory() as directory:
            session=Mock()
            client=SourceClient(directory,session=session,offline=True)
            with self.assertRaises(SourceUnavailable):
                client.read("openalex","https://api.openalex.org/works/W123")
            session.get.assert_not_called()
            folder=Path(directory)/"openalex";folder.mkdir()
            file=folder/(fingerprint(["https://api.openalex.org/works/W123",{}])+".json")
            file.write_text("broken",encoding="utf-8")
            with self.assertRaises(SourceUnavailable):
                client.read("openalex","https://api.openalex.org/works/W123")
            self.assertEqual(file.read_text(encoding="utf-8"),"broken")


class AFieldCompatibilityTests(unittest.TestCase):
    def test_a_default_selection_is_unchanged_and_annotations_are_opt_in(self):
        work=dict(id="https://openalex.org/W123",publication_year=2024,
                  primary_location={"source":{"id":"https://openalex.org/S4210176548"}})
        for enabled in (False,True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory, patch("scripts.fetch_openalex_batch.requests.Session") as session, patch("scripts.fetch_openalex_batch.time.sleep"):
                session.return_value.get.return_value=Mock(ok=True,status_code=200,json=Mock(return_value={"meta":{"count":1},"results":[work]}))
                result=fetch_batch("CVPR",2024,Path(directory)/"batch.jsonl",with_annotations=enabled)
                selected=session.return_value.get.call_args.kwargs["params"]["select"]
                self.assertEqual(selected,FIELDS+(","+ANNOTATION_FIELDS if enabled else ""))
                self.assertEqual("requested_fields" in result,enabled)


if __name__ == "__main__":
    unittest.main()
