"""词表开发参考验证，不把开发参考当成独立人工标注。"""

import json
import unittest
from dataclasses import asdict
from pathlib import Path

from src.knowledge_builder.extraction import (
    extract_candidates,
    fingerprint,
    load_vocabulary,
)
from src.knowledge_builder.input_adapter import load_openalex_sample

ROOT = Path(__file__).resolve().parents[2]


class VocabularyTests(unittest.TestCase):
    def test_new_terms_and_aliases_have_traceable_real_input_examples(self):
        vocabulary = load_vocabulary()
        old = load_vocabulary(ROOT / "examples/knowledge_builder/vocabulary_v0.1.json")
        sources = json.loads(
            (ROOT / "docs/knowledge_builder/vocabulary_sources.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(sources["vocabulary_fingerprint"], fingerprint(vocabulary))
        by_key = {(term["kind"], term["key"]): term for term in vocabulary["terms"]}
        old_keys = {(term["kind"], term["key"]) for term in old["terms"]}
        self.assertEqual(
            {(row["kind"], row["key"]) for row in sources["terms"]},
            set(by_key) - old_keys,
        )
        papers = {
            paper.openalex_id: paper
            for paper in load_openalex_sample(ROOT / "examples/week1_baseline.json")
        }
        for row in sources["terms"]:
            term = by_key[row["kind"], row["key"]]
            self.assertEqual(
                {e["alias"] for e in row["examples"]}, set(term["aliases"])
            )
            for evidence in row["examples"]:
                paper = papers[evidence["paper_id"]]
                text = getattr(paper, evidence["field"])
                self.assertEqual(
                    text[evidence["start"] : evidence["end"]], evidence["quote"]
                )
                self.assertEqual(
                    evidence["quote"].casefold(), evidence["alias"].casefold()
                )
                self.assertEqual(
                    evidence["input_fingerprint"], fingerprint(asdict(paper))
                )

    def test_specific_model_names_and_datasets_are_separate_and_generic_words_not_guessed(
        self,
    ):
        papers = load_openalex_sample(ROOT / "examples/week1_baseline.json")
        second = extract_candidates(papers[1])
        names = {c.entity.name for c in second.entities}
        self.assertIn("YOLO-World", names)
        self.assertIn("YOLO", names)
        self.assertIn("LVIS", names)
        cat_paper = extract_candidates(papers[16])
        teacher = next(
            c for c in cat_paper.entities if c.entity.name == "Class-Aware Teacher"
        )
        self.assertTrue(
            all(e.quote.casefold() == "class-aware teacher" for e in teacher.evidence)
        )

    def test_original_vocabulary_remains_usable_without_changing_its_terms(self):
        papers = load_openalex_sample(ROOT / "examples/week1_baseline.json")
        old = load_vocabulary(ROOT / "examples/knowledge_builder/vocabulary_v0.1.json")
        self.assertEqual(old["version"], "cv-terms/0.1")
        results = [extract_candidates(paper, old) for paper in papers]
        self.assertEqual(sum(len(r.entities) for r in results), 238)
        self.assertEqual(sum(len(r.relations) for r in results), 294)


if __name__ == "__main__":
    unittest.main()
