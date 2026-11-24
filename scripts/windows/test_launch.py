"""Supervisor checks with fake processes/HTTP: no services are started."""
import io
from pathlib import Path
import signal
import unittest
from unittest.mock import Mock, patch

import launch


class SupervisorTests(unittest.TestCase):
    def test_neo4j_html_is_a_valid_http_ready_response(self):
        supervisor = launch.Supervisor({}, Path('.'))
        with patch.object(launch, 'urlopen', return_value=io.BytesIO(b'<html>Neo4j</html>')):
            self.assertEqual(supervisor.wait('http://127.0.0.1:7474/'), {})

    def test_sync_error_is_not_accepted_as_ready(self):
        supervisor = launch.Supervisor({}, Path('.'))
        with patch.object(launch, 'urlopen', return_value=io.BytesIO(
                b'{"status":"ok","graph_sync":{"state":"error"}}')), \
                patch.object(Path, 'write_text'):
            with self.assertRaisesRegex(RuntimeError, 'synchronization failed'):
                supervisor.wait('http://127.0.0.1:8001/api/health', synced=True)

    def test_stop_only_owned_live_processes_in_reverse_order(self):
        supervisor = launch.Supervisor({}, Path('.'))
        order = []
        for name in ('C', 'A', 'D'):
            child = Mock()
            child.poll.return_value = None
            child.send_signal.side_effect = lambda event, name=name: order.append(name)
            supervisor.children.append((name, child))
        with patch.object(signal, 'CTRL_BREAK_EVENT', 1, create=True), \
                patch.object(signal, 'signal'), patch.object(launch.subprocess, 'run') as kill:
            supervisor.stop()
        self.assertEqual(order, ['D', 'A', 'C'])
        kill.assert_not_called()

    def test_neo4j_stop_uses_dedicated_console_helper_not_break(self):
        supervisor = launch.Supervisor({}, Path('.'))
        child = Mock(pid=12345)
        child.poll.return_value = None
        supervisor.children.append(('neo4j', child))
        with patch.object(signal, 'signal'), \
                patch.object(launch.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(launch.subprocess, 'run', return_value=Mock(returncode=0)) as helper:
            supervisor.stop()
        child.send_signal.assert_not_called()
        child.wait.assert_called_once_with(timeout=60)
        self.assertEqual(helper.call_args.args[0][-1], '12345')
        self.assertTrue(helper.call_args.args[0][1].endswith('console_stop.py'))


if __name__ == '__main__':
    unittest.main()
