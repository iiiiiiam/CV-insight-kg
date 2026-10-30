"""质量盘点、标注与评分测试；人工答案仅为程序构造测试数据。"""

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.knowledge_builder.assessment import (
    build_evaluation_manifest,
    build_quality_report,
    validate_evaluation_manifest,
)
from src.knowledge_builder.assessment_io import demo_markdown, write_assessment
from src.knowledge_builder.evaluation import (
    build_annotation_template,
    score_annotations,
)
from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.models import PaperInput

ROOT = Path(__file__).resolve().parents[1]


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.paper = PaperInput(
            "test:paper",
            "YOLO COCO",
            None,
            2024,
            "CVPR",
            [],
            "test:source",
            "test-only",
        )
        self.result = extract_candidates(self.paper)

    def completed(self, gold):
        annotations = build_annotation_template([self.paper])
        annotations["cases"][0].update(
            {
                "annotation_status": "completed",
                "annotator": "program-test",
                "completed_at": "2026-10-31T10:00:00+08:00",
                "gold_entities": gold,
            }
        )
        return annotations

    def test_existing_development_papers_cannot_be_presented_as_unseen_test(self):
        manifest = build_evaluation_manifest([self.paper])
        self.assertEqual(
            manifest["splits"], {"development": [self.paper.openalex_id], "test": []}
        )
        self.assertFalse(manifest["test_ready"])
        validate_evaluation_manifest(manifest, [self.paper])
        manifest["splits"]["test"] = [self.paper.openalex_id]
        with self.assertRaisesRegex(ValueError, "independent test"):
            validate_evaluation_manifest(manifest, [self.paper])

    def test_quality_reports_missing_categories_without_claiming_accuracy(self):
        quality = build_quality_report([self.paper], [self.result])
        self.assertEqual(
            quality["papers_with_category"],
            {"method": 1, "dataset": 1, "task": 0, "topic": 0},
        )
        self.assertIn("task", quality["per_paper"][0]["missing_text_categories"])
        self.assertEqual(quality["papers_without_abstract"], [self.paper.openalex_id])
        self.assertIsNone(quality["precision"])
        self.assertEqual(quality["review_counts"]["confirmed"]["entities"], 0)

    def test_unannotated_template_has_no_predicted_answers_and_no_scores(self):
        template = build_annotation_template([self.paper])
        self.assertIsNone(template["cases"][0]["gold_entities"])
        self.assertIsNone(template["cases"][0]["annotator"])
        outcome = score_annotations(template, [self.paper], [self.result])
        self.assertEqual(outcome["status"], "awaiting_annotations")
        self.assertEqual(outcome["completed_cases"], 0)
        self.assertIsNone(outcome["precision"])
        self.assertIsNone(outcome["false_negative"])

    def test_exact_span_scoring_counts_correct_extra_and_missed_mentions(self):
        # 构造参考：YOLO 正确，COCO 预测被排除，同时将同段文字标为另一个未预测的任务。
        gold = [
            {
                "kind": "method",
                "canonical_name": "yolo",
                "field": "title",
                "start": 0,
                "end": 4,
                "quote": "YOLO",
            },
            {
                "kind": "task",
                "canonical_name": "Test task",
                "field": "title",
                "start": 5,
                "end": 9,
                "quote": "COCO",
            },
        ]
        outcome = score_annotations(self.completed(gold), [self.paper], [self.result])
        self.assertEqual(
            (
                outcome["true_positive"],
                outcome["false_positive"],
                outcome["false_negative"],
            ),
            (1, 1, 1),
        )
        self.assertEqual(outcome["precision"], 0.5)
        self.assertEqual(outcome["recall"], 0.5)
        self.assertEqual(outcome["f1"], 0.5)
        self.assertEqual(outcome["status"], "development_scored")

    def test_completed_empty_gold_differs_from_unannotated(self):
        outcome = score_annotations(self.completed([]), [self.paper], [self.result])
        self.assertEqual(outcome["status"], "development_scored")
        self.assertEqual(outcome["precision"], 0)
        self.assertIsNone(outcome["recall"])
        self.assertEqual(outcome["false_positive"], 2)

    def test_partial_annotations_do_not_silently_score_only_completed_subset(self):
        other = deepcopy(self.paper)
        other.openalex_id = "test:other"
        annotations = self.completed([])
        annotations["cases"].extend(build_annotation_template([other])["cases"])
        outcome = score_annotations(
            annotations, [self.paper, other], [self.result, extract_candidates(other)]
        )
        self.assertEqual(outcome["completed_cases"], 1)
        self.assertEqual(outcome["incomplete_papers"], [other.openalex_id])
        self.assertIsNone(outcome["precision"])

    def test_bad_gold_source_duplicate_span_and_missing_annotator_rejected(self):
        gold = {
            "kind": "method",
            "canonical_name": "YOLO",
            "field": "title",
            "start": 0,
            "end": 4,
            "quote": "YOLO",
        }
        for change in (
            "quote",
            "offset",
            "duplicate",
            "annotator",
            "source",
            "time",
            "scope",
        ):
            annotation = self.completed([deepcopy(gold)])
            case = annotation["cases"][0]
            if change == "quote":
                case["gold_entities"][0]["quote"] = "invented"
            elif change == "offset":
                case["gold_entities"][0]["start"] = True
            elif change == "duplicate":
                case["gold_entities"].append(deepcopy(gold))
            elif change == "annotator":
                case["annotator"] = ""
            elif change == "source":
                case["input_fingerprint"] = "wrong"
            elif change == "time":
                case["completed_at"] = "2026-10-31T10:00:00"
            else:
                annotation["scope"] = "independent_test"
            with self.subTest(change=change), self.assertRaises(ValueError):
                score_annotations(annotation, [self.paper], [self.result])

    def test_unannotated_cannot_contain_fake_gold_or_duplicate_source(self):
        template = build_annotation_template([self.paper])
        template["cases"][0]["gold_entities"] = []
        with self.assertRaises(ValueError):
            score_annotations(template, [self.paper], [self.result])
        template = build_annotation_template([self.paper])
        template["cases"].append(deepcopy(template["cases"][0]))
        with self.assertRaises(ValueError):
            score_annotations(template, [self.paper], [self.result])

    def test_materials_do_not_overwrite_or_leave_partial_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation"
            documents = {"quality.json": {"precision": None}, "demo.md": "# Example"}
            write_assessment(path, documents)
            self.assertEqual(
                json.loads((path / "quality.json").read_text(encoding="utf-8")),
                {"precision": None},
            )
            with self.assertRaises(FileExistsError):
                write_assessment(path, documents)
            with patch(
                "src.knowledge_builder.assessment_io.os.rename",
                side_effect=OSError("test"),
            ):
                with self.assertRaises(OSError):
                    write_assessment(Path(directory) / "failed", documents)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            with self.assertRaises(ValueError):
                write_assessment(Path(directory) / "unsafe", {"../outside": "bad"})

    def test_real_sample_manifest_template_and_packet_are_traceable_not_frozen_gold(
        self,
    ):
        papers = load_openalex_sample(ROOT / "examples/week1_baseline.json")
        manifest = json.loads(
            (ROOT / "examples/b_evaluation_manifest.json").read_text(encoding="utf-8")
        )
        validate_evaluation_manifest(manifest, papers)
        template = build_annotation_template(papers)
        self.assertEqual(len(template["cases"]), 5)
        self.assertTrue(
            all(case["gold_entities"] is None for case in template["cases"])
        )
        results = [extract_candidates(paper) for paper in papers]
        packet = demo_markdown(papers, results)
        self.assertTrue(
            all(
                paper.title in packet and paper.abstract in packet
                for paper in papers[:5]
            )
        )

    def test_cli_generates_runnable_validation_packet_with_no_human_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation"
            command = [
                sys.executable,
                "-m",
                "scripts.prepare_b_validation",
                "--reviews-dir",
                str(Path(directory) / "no-reviews"),
                "--output",
                str(path),
            ]
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            evaluation = json.loads(
                (path / "evaluation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evaluation["status"], "awaiting_annotations")
            self.assertIsNone(evaluation["precision"])
            self.assertEqual(len(list(path.iterdir())), 7)


if __name__ == "__main__":
    unittest.main()
