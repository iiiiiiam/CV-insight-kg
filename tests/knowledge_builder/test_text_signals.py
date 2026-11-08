"""Reusable wording, negative cases and unchanged legacy extraction contracts."""

import unittest

from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.source_enrichment import analyze_sources
from src.knowledge_builder.text_signals import explicit_signals


class TextSignalTests(unittest.TestCase):
    def paper(self, abstract, title="A vision study"):
        return PaperInput("https://openalex.org/W123", title, abstract, 2024, "CVPR", [],
                          "https://openalex.org/W123", "fixture")

    def test_introduced_named_model_does_not_need_a_dictionary_entry(self):
        paper = self.paper("In this paper, we introduce a novel dual-branch diffusion model named PanFusion to generate panoramas.")
        signals = explicit_signals(paper)
        self.assertEqual([(s["kind"], s["name"]) for s in signals], [("method", "PanFusion")])
        report = analyze_sources(paper, load_vocabulary(), [], fallback=True)
        candidate = next(c for c in report["enriched"]["entities"] if c["entity"]["name"] == "PanFusion")
        proof = candidate["evidence"][0]
        self.assertEqual(paper.abstract[proof["start"]:proof["end"]], "PanFusion")

    def test_new_direct_name_and_another_named_model_reuse_same_rule(self):
        for wording in ("We present CloudNet, a new model for clouds.",
                        "We propose a new framework called CloudNet for images."):
            with self.subTest(wording=wording):
                self.assertEqual([s["name"] for s in explicit_signals(self.paper(wording))], ["CloudNet"])

    def test_background_names_metrics_and_generic_introductions_are_not_methods(self):
        for wording in ("We compare PreviousNet with AnotherNet.",
                        "We introduce a novel method for images.",
                        "We propose an improved score and report PSNR."):
            self.assertEqual(explicit_signals(self.paper(wording)), [])

    def test_multiword_names_use_explicit_acronym_and_do_not_truncate(self):
        signals = explicit_signals(self.paper("We propose a pre-training method called Point cloud Diffusion pre-training (PointDif)."))
        self.assertEqual([s["name"] for s in signals], ["PointDif"])
        signals = explicit_signals(self.paper("We introduce a task called Referring Image Editing (RIE)."))
        self.assertEqual([(s["kind"], s["name"]) for s in signals], [("task", "Referring Image Editing")])

    def test_dataset_lists_named_sets_and_citations(self):
        for wording, expected in (
            ("We evaluate on ActivityNet Captions and YouCook2 datasets.", {"ActivityNet Captions", "YouCook2"}),
            ("We use datasets like YouCook2 [31] and ActivityNet [13].", {"YouCook2", "ActivityNet"}),
            ("Results on NewSet, OtherSet and ThirdSet datasets improve.", {"NewSet", "OtherSet", "ThirdSet"}),
            ("We release a dataset named FreshSet.", {"FreshSet"}),
            ("FreshSet dataset is used here.", {"FreshSet"}),
        ):
            with self.subTest(wording=wording):
                self.assertEqual({s["name"] for s in explicit_signals(self.paper(wording))}, expected)

    def test_generic_dataset_descriptions_and_unnamed_new_data_are_not_names(self):
        for wording in ("We test on three public datasets.", "We collect a new dataset.",
                        "We use standard DVC datasets.", "We report RGB and FPS.", "This dataset is public."):
            self.assertEqual(explicit_signals(self.paper(wording)), [])

    def test_old_extractor_does_not_silently_change(self):
        paper = self.paper("We present CloudNet, evaluated on FreshSet dataset.")
        result = extract_candidates(paper)
        self.assertNotIn("CloudNet", {e.entity.name for e in result.entities})
        report = analyze_sources(paper, load_vocabulary(), [], fallback=True)
        self.assertTrue({"CloudNet", "FreshSet"} <= {c["entity"]["name"] for c in report["enriched"]["entities"]})
