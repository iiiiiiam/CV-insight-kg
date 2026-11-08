"""B 输入适配测试；沿用团队 unittest 运行方式。"""

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.ingest import decode_abstract
from src.knowledge_builder.input_adapter import (
    adapt_openalex_work,
    load_openalex_sample,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InputAdapterTests(unittest.TestCase):
    def setUp(self):
        self.work = {
            "id": "https://openalex.org/W_TEST",
            "display_name": "A title with punctuation.",
            "publication_year": 2024,
            "doi": None,
            "abstract_inverted_index": {"detection": [1], "Object": [0, 2]},
            "authorships": [
                {
                    "author": {"id": "author:test", "display_name": "Test Author"},
                    "institutions": [
                        {"id": "institution:test", "display_name": "Test Lab"}
                    ],
                    "raw_affiliation_strings": ["Test Lab"],
                }
            ],
            "primary_location": {"source": {"id": "https://openalex.org/S_TEST"}},
        }

    def adapt(self, work):
        return adapt_openalex_work(work, venue="CVPR", dataset_id="test-only")

    def write_sample(self, directory, rows):
        root = Path(directory)
        body = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
        (root / "papers.jsonl").write_bytes(body)
        manifest = {
            "source": "openalex",
            "source_id": "S_TEST",
            "dataset_id": "test-only",
            "venue": "CVPR",
            "year": 2024,
            "filename": "papers.jsonl",
            "expected_count": len(rows),
            "sha256": hashlib.sha256(body).hexdigest(),
            "papers": [
                {
                    "openalex_id": row["id"],
                    "title": row["display_name"],
                    "year": row["publication_year"],
                    "doi": row.get("doi"),
                }
                for row in rows
            ],
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_restores_abstract_in_position_order_and_preserves_title(self):
        paper = self.adapt(self.work)
        self.assertEqual(paper.abstract, "Object detection Object")
        self.assertEqual(paper.title, self.work["display_name"])
        self.assertEqual(paper.openalex_id, self.work["id"])
        self.assertEqual(paper.source_url, self.work["id"])
        self.assertEqual(paper.dataset_id, "test-only")

    def test_author_institution_links_are_preserved_without_sharing_mutable_data(self):
        original = deepcopy(self.work)
        paper = self.adapt(self.work)
        self.assertEqual(paper.authorships, self.work["authorships"])
        paper.authorships[0]["institutions"][0]["display_name"] = "Edited"
        self.assertEqual(self.work, original)

    def test_missing_abstract_remains_none(self):
        for index in (None, {}, {"empty": []}):
            with self.subTest(index=index):
                self.work["abstract_inverted_index"] = index
                self.assertIsNone(self.adapt(self.work).abstract)
        del self.work["abstract_inverted_index"]
        self.assertIsNone(self.adapt(self.work).abstract)

    def test_invalid_abstract_positions_are_rejected(self):
        for index in ({"a": [-1]}, {"a": [0], "b": [0]}, {"a": [2]}, {"a": ["0"]}):
            with self.subTest(index=index):
                self.work["abstract_inverted_index"] = index
                with self.assertRaises(ValueError):
                    self.adapt(self.work)

    def test_missing_required_metadata_is_rejected(self):
        for key in ("id", "display_name", "publication_year"):
            with self.subTest(key=key):
                work = deepcopy(self.work)
                del work[key]
                with self.assertRaises(ValueError):
                    self.adapt(work)

    def test_tampered_sample_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_sample(directory, [self.work])
            with (path.parent / "papers.jsonl").open("ab") as handle:
                handle.write(b" ")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_openalex_sample(path)

    def test_rehashed_record_with_changed_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_sample(directory, [self.work])
            changed = deepcopy(self.work)
            changed["publication_year"] = 2023
            body = (json.dumps(changed) + "\n").encode("utf-8")
            (path.parent / "papers.jsonl").write_bytes(body)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["sha256"] = hashlib.sha256(body).hexdigest()
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "baseline"):
                load_openalex_sample(path)

    def test_duplicate_and_missing_papers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_sample(directory, [self.work, self.work])
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_openalex_sample(path)
            path = self.write_sample(directory, [self.work])
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["expected_count"] = 2
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "count"):
                load_openalex_sample(path)

    def test_real_twenty_papers_match_a_and_input_files_are_unchanged(self):
        examples = PROJECT_ROOT / "examples"
        manifest_path = examples / "week1_baseline.json"
        sample_path = examples / "cvpr_2024_seed.jsonl"
        before = (manifest_path.read_bytes(), sample_path.read_bytes())
        papers = load_openalex_sample(manifest_path)
        works = [
            json.loads(line)
            for line in before[1].decode("utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(papers), 20)
        for paper, work in zip(papers, works, strict=True):
            self.assertEqual(paper.openalex_id, work["id"])
            self.assertEqual(paper.title, work["display_name"])
            self.assertEqual(paper.authorships, work["authorships"])
            self.assertEqual(
                paper.abstract, decode_abstract(work["abstract_inverted_index"])
            )
            self.assertTrue(paper.abstract)
            self.assertEqual(paper.year, 2024)
            self.assertEqual(paper.venue, "CVPR")
        self.assertEqual(before, (manifest_path.read_bytes(), sample_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
