"""Control-window shutdown behavior without creating a GUI or services."""
from pathlib import Path
import queue
import unittest
from unittest.mock import Mock, patch

from controller_entry import Controller


class ControllerTests(unittest.TestCase):
    def controller(self):
        control = Controller.__new__(Controller)
        for name in ('root', 'process', 'status', 'note', 'open_button', 'exit_button'):
            setattr(control, name, Mock())
        control.process.poll.return_value = None
        control.process.pid = 12345
        control.state = Path('D:/fixture')
        control.messages = queue.Queue()
        control.stopping = control.stop_sent = control.ready = False
        control.error = ''
        return control

    def test_close_waits_for_owned_supervisor_and_does_not_kill_it(self):
        control = self.controller()
        control.close()
        self.assertTrue(control.stopping)
        control.root.destroy.assert_not_called()
        control.process.terminate.assert_not_called()
        with patch('controller_entry.request_stop', return_value=True) as stop:
            control.poll()
            stop.assert_called_once_with(control.state, 12345)
        control.process.poll.return_value = 0
        control.poll()
        control.root.destroy.assert_called_once()

    def test_stop_during_initialization_retries_until_signal_exists(self):
        control = self.controller()
        control.close()
        with patch('controller_entry.request_stop', side_effect=[False, True]) as stop:
            control.poll()
            self.assertFalse(control.stop_sent)
            control.poll()
            self.assertTrue(control.stop_sent)
            self.assertEqual(stop.call_count, 2)

    def test_failed_start_stays_visible_until_user_closes(self):
        control = self.controller()
        control.messages.put('ERROR: fixture failure')
        control.process.poll.return_value = 1
        control.poll()
        control.root.destroy.assert_not_called()
        control.note.set.assert_called_with('ERROR: fixture failure')
        control.close()
        control.root.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
