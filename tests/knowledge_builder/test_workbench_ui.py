"""可选 Streamlit 原型交互测试，存档只写临时目录。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ModuleNotFoundError:
    AppTest = None

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(
    AppTest is None, "Optional Streamlit prototype dependencies not installed"
)
class WorkbenchUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        override = patch.dict(
            "os.environ", {"KNOWLEDGE_WORKBENCH_DATA": str(self.data)}
        )
        override.start()
        self.addCleanup(override.stop)
        self.app = AppTest.from_file(
            ROOT / "prototypes/knowledge_builder/app.py", default_timeout=60
        ).run()

    def assert_clean(self):
        self.assertEqual(list(self.app.exception), [])

    def open_page(self, page):
        self.app.radio(key="page").set_value(page).run()
        self.assert_clean()

    def test_overview_uses_real_counts_and_does_not_create_decisions(self):
        self.assert_clean()
        self.assertEqual(
            [metric.value for metric in self.app.metric], ["20", "285", "341", "0"]
        )
        self.assertEqual(list(self.data.iterdir()), [])

    def test_paper_filters_handle_empty_results_and_combination(self):
        self.open_page("论文与候选")
        self.app.text_input(key="paper_query").set_value(
            "no-such-phrase-program-test"
        ).run()
        self.assert_clean()
        self.assertTrue(
            any("没有符合条件" in element.value for element in self.app.info)
        )
        self.app.text_input(key="paper_query").set_value("open-vocabulary")
        self.app.selectbox(key="paper_method").set_value("method:term:yolo-world").run()
        self.assert_clean()
        self.assertEqual(len(self.app.selectbox(key="browser_paper").options), 1)
        self.app.selectbox(key="vocabulary_choice").set_value("legacy").run()
        self.assert_clean()
        self.assertIsNone(self.app.selectbox(key="paper_method").value)

    def test_confirm_requires_name_reason_and_restores_on_new_page_session(self):
        self.open_page("候选核对")
        self.app.button(key="confirm_review").click().run()
        self.assert_clean()
        self.assertTrue(self.app.error)
        self.assertFalse((self.data / "reviews").exists())
        self.app.text_input(key="reviewer_name").set_value("ui-program-test")
        self.app.text_area(key="decision_reason").set_value(
            "Program test only; not human annotation"
        )
        self.app.button(key="confirm_review").click().run()
        self.assert_clean()
        self.assertTrue(self.app.button(key="confirm_review").disabled)
        archives = list((self.data / "reviews").glob("*.json"))
        self.assertEqual(len(archives), 1)
        original = json.loads(archives[0].read_text(encoding="utf-8"))
        self.assertEqual(len(original["payload"]["events"]), 1)
        reopened = AppTest.from_file(
            ROOT / "prototypes/knowledge_builder/app.py", default_timeout=60
        ).run()
        self.assertEqual(list(reopened.exception), [])
        self.assertEqual(reopened.metric[3].value, "0")  # 实体确认不会自动确认关系。
        self.assertEqual(
            reopened.session_state["workbench"].counts()["confirmed"]["entities"], 1
        )

    def test_relation_confirmation_is_disabled_until_endpoints_and_jump_works(self):
        self.open_page("候选核对")
        self.app.radio(key="review_collection").set_value("关系").run()
        self.assert_clean()
        self.assertTrue(self.app.button(key="confirm_review").disabled)
        self.assertTrue(self.app.button(key="correct_review").disabled)
        endpoint = next(
            button
            for button in self.app.button
            if button.key and button.key.startswith("endpoint_")
        )
        endpoint.click().run()
        self.assert_clean()
        self.assertEqual(self.app.radio(key="review_collection").value, "实体")

    def test_export_and_quality_buttons_write_real_checked_materials(self):
        self.open_page("导出与质量")
        self.app.button(key="save_export").click().run()
        self.assert_clean()
        folders = list((self.data / "exports").iterdir())
        self.assertEqual(len(folders), 1)
        confirmed = json.loads(
            (folders[0] / "confirmed.json").read_text(encoding="utf-8")
        )
        self.assertEqual(confirmed["papers"], [])
        self.app.button(key="prepare_validation").click().run()
        self.assert_clean()
        validations = list((self.data / "validation").iterdir())
        outcome = json.loads(
            (validations[0] / "evaluation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(outcome["status"], "awaiting_annotations")


if __name__ == "__main__":
    unittest.main()
