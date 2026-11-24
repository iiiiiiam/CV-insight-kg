"""构造数据仅测试程序；真实样本测试不充当人工评估。"""

import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

from src.knowledge_builder.extraction import (
    candidate_id,
    extract_candidates,
    load_vocabulary,
    validate_evidence,
    validate_result,
)
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import PaperInput

ROOT = Path(__file__).resolve().parents[1]


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.paper = PaperInput(
            "test:paper",
            "RT-DETR and YOLOs for Object Detection",
            "RT-DETR compares YOLO on MS COCO. COCO and Objects365.",
            2024,
            "CVPR",
            [
                {
                    "author": {"id": "test:a1", "display_name": "Same Name"},
                    "institutions": [{"id": "test:i1", "display_name": "Lab One"}],
                },
                {
                    "author": {"id": "test:a2", "display_name": "Same Name"},
                    "institutions": [{"id": "test:i2", "display_name": "Lab Two"}],
                },
            ],
            "test:source",
            "test-only",
        )

    def test_aliases_merge_and_retain_exact_evidence(self):
        result = extract_candidates(self.paper)
        by_key = {c.entity.key: c for c in result.entities}
        self.assertNotIn("method:term:detr", by_key)
        self.assertEqual(len(by_key["method:term:rt-detr"].evidence), 2)
        self.assertEqual(
            [e.quote for e in by_key["dataset:term:coco"].evidence], ["MS COCO", "COCO"]
        )
        self.assertEqual(by_key["method:term:yolo"].evidence[0].quote, "YOLOs")
        for candidate in result.entities:
            for evidence in candidate.evidence:
                validate_evidence(self.paper, evidence)
        for key in ("method:term:rt-detr", "dataset:term:coco"):
            self.assertEqual(sum(r.target == key for r in result.relations), 1)

    def test_word_boundaries_and_case_insensitive_matching(self):
        self.paper.title = "myYOLO YOLO-World cocoons DETRish rt-detr OBJECT DETECTION"
        self.paper.abstract = None
        names = {c.entity.name for c in extract_candidates(self.paper).entities}
        self.assertIn("RT-DETR", names)
        self.assertIn("Object Detection", names)
        self.assertNotIn("YOLO", names)
        self.assertNotIn("COCO", names)
        self.assertNotIn("DETR", names)

    def test_same_name_authors_keep_distinct_ids_and_correct_institutions(self):
        result = extract_candidates(self.paper)
        pairs = {
            (r.source, r.target)
            for r in result.relations
            if r.kind == "affiliated_with"
        }
        self.assertEqual(
            pairs,
            {
                ("author:test:a1", "institution:test:i1"),
                ("author:test:a2", "institution:test:i2"),
            },
        )
        for relation in result.relations:
            if relation.kind == "affiliated_with":
                self.assertEqual(len({e.path[1] for e in relation.evidence}), 1)

    def test_missing_ids_are_local_and_missing_information_is_reported(self):
        self.paper.abstract = None
        for authorship in self.paper.authorships:
            del authorship["author"]["id"]
        self.paper.authorships.append({"author": None, "institutions": []})
        result = extract_candidates(self.paper)
        authors = [c.entity for c in result.entities if c.entity.kind == "author"]
        self.assertEqual(len({a.key for a in authors}), 2)
        self.assertTrue(all(a.source_id is None for a in authors))
        self.assertIn("Missing abstract", result.diagnostics)
        self.assertTrue(any("Missing author name" in d for d in result.diagnostics))
        self.assertFalse(
            any(e.field == "abstract" for c in result.entities for e in c.evidence)
        )

    def test_deterministic_and_does_not_mutate_input(self):
        before = deepcopy(asdict(self.paper))
        one = extract_candidates(self.paper)
        two = extract_candidates(self.paper)
        self.assertEqual(one, two)
        self.assertEqual(before, asdict(self.paper))
        self.assertTrue(
            all(c.status == "pending" for c in one.entities + one.relations)
        )
        self.assertTrue(
            all(
                r.kind.startswith("mentions_")
                for r in one.relations
                if ":term:" in r.target
            )
        )

    def test_invalid_text_and_metadata_evidence_are_rejected(self):
        result = extract_candidates(self.paper)
        text = next(
            e for c in result.entities for e in c.evidence if e.field == "title"
        )
        metadata = result.entities[0].evidence[0]
        bad_proofs = [
            replace(text, quote="invented"),
            replace(text, start=-1),
            replace(text, end=999),
            replace(text, start=True),
            replace(metadata, path=("authorships", -1)),
            replace(metadata, path=("absent",)),
            replace(metadata, quote="wrong"),
        ]
        for proof in bad_proofs:
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                validate_evidence(self.paper, proof)
        self.paper.year = 2025
        with self.assertRaises(ValueError):
            validate_evidence(self.paper, text)

    def test_invalid_relation_endpoints_direction_status_and_duplicates(self):
        original = extract_candidates(self.paper)
        for change in ("endpoint", "direction", "status", "duplicate"):
            result = deepcopy(original)
            if change == "endpoint":
                result.relations[0].target = "missing"
            elif change == "direction":
                r = result.relations[0]
                r.source, r.target = r.target, r.source
            elif change == "status":
                result.entities[0].status = "confirmed"
            else:
                result.relations.append(deepcopy(result.relations[0]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_result(self.paper, result)

    def test_vocabulary_changes_are_traceable_and_conflicts_rejected(self):
        vocabulary = load_vocabulary()
        one = extract_candidates(self.paper, vocabulary)
        vocabulary["terms"][0]["name"] = "Edited topic label"
        two = extract_candidates(self.paper, vocabulary)
        self.assertNotEqual(one.vocabulary_fingerprint, two.vocabulary_fingerprint)
        self.assertEqual(one.input_fingerprint, two.input_fingerprint)
        vocabulary["terms"][0]["aliases"].append("yolo")
        with self.assertRaisesRegex(ValueError, "alias"):
            extract_candidates(self.paper, vocabulary)

    def test_affiliation_cannot_connect_different_authorship_records(self):
        result = extract_candidates(self.paper)
        links = [r for r in result.relations if r.kind == "affiliated_with"]
        # 两段证据分别存在于原输入，但不能用来拼凑错误的作者—机构关系。
        links[0].target = links[1].target
        links[0].candidate_id = candidate_id(
            self.paper.openalex_id,
            "relation",
            links[0].source,
            links[0].kind,
            links[0].target,
        )
        links[0].evidence = [e for e in links[0].evidence if e.path[2] == "author"] + [
            e for e in links[1].evidence if e.path[2] == "institutions"
        ]
        with self.assertRaisesRegex(ValueError, "same authorship"):
            validate_result(self.paper, result)

    def test_unicode_offsets_use_python_characters(self):
        self.paper.title = "研究：Object Detection"
        result = extract_candidates(self.paper)
        proof = next(c for c in result.entities if c.entity.kind == "task").evidence[0]
        self.assertEqual(proof.start, 3)
        self.assertEqual(self.paper.title[proof.start : proof.end], proof.quote)

    def test_real_twenty_papers_have_valid_pending_candidates(self):
        paths = [
            ROOT / "examples" / name
            for name in ("week1_baseline.json", "cvpr_2024_seed.jsonl")
        ]
        before = [p.read_bytes() for p in paths]
        papers = load_openalex_sample(paths[0])
        for paper in papers:
            result = extract_candidates(paper)
            validate_result(paper, result)
            self.assertTrue(result.entities)
            self.assertTrue(result.relations)
            self.assertTrue(
                all(c.status == "pending" for c in result.entities + result.relations)
            )
        first = extract_candidates(papers[0])
        task = next(
            c for c in first.entities if c.entity.key == "task:term:object-detection"
        )
        self.assertTrue(
            any(
                e.field == "title"
                and (e.start, e.end, e.quote) == (30, 46, "Object Detection")
                for e in task.evidence
            )
        )
        self.assertEqual(before, [p.read_bytes() for p in paths])


if __name__ == "__main__":
    unittest.main()
