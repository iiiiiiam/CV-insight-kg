"""Console lifecycle checks; no app services or runtime are started."""
from contextlib import nullcontext
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import console_ui


class ConsoleTests(unittest.TestCase):
    def test_failure_is_copied_to_log_and_pause_is_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with patch.object(console_ui, 'single_instance', return_value=nullcontext()), \
                    patch.object(console_ui, 'pause_on_failure') as pause, \
                    patch.object(console_ui.sys, 'stdout', output), \
                    patch.object(console_ui.sys, 'stderr', output):
                self.assertEqual(console_ui.run_console(lambda: print('fixture failure') or 1, directory), 1)
            text = next((Path(directory) / 'user-data/logs').glob('launcher-*.log')).read_text(encoding='utf-8')
            self.assertIn('fixture failure', text)
            self.assertIn('Exit code: 1', text)
            pause.assert_called_once_with(1)

    def test_only_errors_on_interactive_console_wait_for_enter(self):
        reader = Mock()
        stream = Mock()
        stream.isatty.return_value = True
        console_ui.pause_on_failure(0, stream, reader)
        reader.assert_not_called()
        console_ui.pause_on_failure(1, stream, reader)
        reader.assert_called_once()
        reader.reset_mock()
        stream.isatty.return_value = False
        console_ui.pause_on_failure(1, stream, reader)
        reader.assert_not_called()

    def test_lock_rejects_duplicate_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.lock'
            with console_ui.single_instance(path):
                with self.assertRaisesRegex(RuntimeError, 'already starting or running'):
                    with console_ui.single_instance(path):
                        self.fail('Duplicate entered')
            with console_ui.single_instance(path):
                pass


if __name__ == '__main__':
    unittest.main()
