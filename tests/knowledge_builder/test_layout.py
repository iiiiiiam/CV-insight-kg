"""工程重构后的入口和旧数据位置兼容验证。"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.knowledge_builder.paths import default_review_directory, workspace_data

ROOT = Path(__file__).resolve().parents[2]


class LayoutTests(unittest.TestCase):
    def test_functional_command_modules_are_importable_and_help_does_not_start_services(
        self,
    ):
        for command in ("preview", "review", "export", "prepare_validation"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.knowledge_builder." + command,
                        "--help",
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_default_directory_is_functional_and_old_records_remain_discoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                default_review_directory(root), workspace_data(root) / "reviews"
            )
            legacy = root / "data" / "b_reviews"
            legacy.mkdir(parents=True)
            (legacy / "existing.json").write_text("{}", encoding="utf-8")
            self.assertEqual(default_review_directory(root), legacy)
            current = workspace_data(root) / "reviews"
            current.mkdir(parents=True)
            (current / "other.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Both current and legacy"):
                default_review_directory(root)


if __name__ == "__main__":
    unittest.main()
