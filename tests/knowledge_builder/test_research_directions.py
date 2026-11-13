"""Direction selection is bounded and explains its evidence without graph writes."""

import unittest
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.research_directions import classify_directions
from src.knowledge_builder.extraction import fingerprint


class ResearchDirectionTests(unittest.TestCase):
    def paper(self, title, abstract=""):
        return PaperInput("https://openalex.org/W1", title, abstract, 2024, "CVPR", [],
                          "https://openalex.org/W1", "fixture")

    def record(self, source, **payload):
        return dict(source=source, payload=payload, digest=fingerprint(payload), url="https://example.test/data")

    def test_title_works_without_external_sources_and_has_exact_quote(self):
        paper = self.paper("A Unified Framework for Semantic Segmentation")
        result = classify_directions(paper, [])
        self.assertEqual([r["name"] for r in result], ["图像分割"])
        proof = result[0]["mapped_from"][0]
        self.assertEqual(paper.title[proof["start"]:proof["end"]], proof["quote"])

    def test_keywords_and_abstract_can_fill_missing_catalog(self):
        result = classify_directions(self.paper("A New Framework", "We address visual question answering."),
            [self.record("openalex", keywords=[dict(display_name="visual question answering")])])
        self.assertEqual(result[0]["name"], "视觉语言理解")

    def test_catalog_tags_alone_are_not_a_long_direction_list(self):
        result = classify_directions(self.paper("A New Framework"), [self.record("paperswithcode",
            tasks=[dict(name=n) for n in ("Object Detection", "Image segmentation", "Image generation")])])
        self.assertEqual([r["name"] for r in result], ["其他"])
        self.assertEqual(result[0]["mapped_from"], [])

    def test_default_single_direction_even_when_sources_have_many_supported_tags(self):
        paper = self.paper("A General Model", "We study object detection, image segmentation and image generation.")
        result = classify_directions(paper, [self.record("paperswithcode", tasks=[dict(name=n)
            for n in ("Object Detection", "Image segmentation", "Image generation")])])
        self.assertEqual(len(result), 1)

    def test_two_clear_title_tasks_are_allowed(self):
        paper = self.paper("Image Generation and Image Restoration", "We unify image generation and image restoration.")
        result = classify_directions(paper, [])
        self.assertEqual({r["name"] for r in result}, {"图像与视频生成", "图像与视频恢复"})
        self.assertEqual([r["selection"] for r in result], ["primary", "additional"])

    def test_hard_cap_three_and_deterministic_source_order(self):
        paper = self.paper("Image Generation, Image Editing, Image Restoration and Image Classification")
        a = self.record("paperswithcode", tasks=[dict(name=n) for n in
            ("Image generation", "Image editing", "Image Restoration", "Image Classification")])
        b = self.record("openalex", keywords=[dict(display_name="Image generation")])
        result = classify_directions(paper, [a, b])
        self.assertEqual(len(result), 3)
        self.assertEqual(result, classify_directions(paper, [b, a]))

    def test_diffusion_and_transformer_alone_do_not_imply_generation(self):
        result = classify_directions(self.paper("Diffusion Transformers for Feature Learning"), [])
        self.assertEqual(result[0]["name"], "其他")

    def test_other_is_mutually_exclusive_with_real_direction(self):
        result = classify_directions(self.paper("Object Detection"), [])
        self.assertNotIn("其他", [r["name"] for r in result])
