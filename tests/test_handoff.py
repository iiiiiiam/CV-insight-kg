import tempfile
import unittest
import importlib.util
import shutil
from pathlib import Path

from scripts.init_project import initialize
from app.paths import PROJECT_ROOT


class HandoffTests(unittest.TestCase):
    def test_setup_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(initialize(root))
            settings = (root / ".env").read_text()
            self.assertIn("OPENALEX_API_KEY=", settings)
            self.assertNotIn("ADMIN_TOKEN", settings)
            self.assertNotIn("replace-", settings)
            self.assertNotIn("MYSQL_PASSWORD", settings)
            self.assertFalse(initialize(root))
            self.assertEqual((root / ".env").read_text(), settings)

    def test_paths_follow_a_renamed_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Another Team Checkout"
            (root / "app").mkdir(parents=True)
            shutil.copyfile(PROJECT_ROOT / "app" / "paths.py", root / "app" / "paths.py")
            spec = importlib.util.spec_from_file_location("renamed_checkout_paths", root / "app" / "paths.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.PROJECT_ROOT, root)
            self.assertEqual(module.project_path("data/raw"), root / "data" / "raw")
            self.assertEqual(module.project_path(Path(directory)), Path(directory))
