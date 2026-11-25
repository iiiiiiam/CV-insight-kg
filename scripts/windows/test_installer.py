"""Installer input and stop-entry checks, without building or starting services."""
import json
from pathlib import Path
import tempfile
import unittest

from build_installer import validate_package
from control import StopSignal, request_stop


class InstallerTests(unittest.TestCase):
    def test_used_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for relative in ('ResearchInsight.exe', 'runtime/java/bin/java.exe', 'runtime/neo4j/bin/neo4j.bat',
                             'ResearchInsightControl/ResearchInsightControl.exe'):
                target = home / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            (home / 'build-manifest.json').write_text(json.dumps({
                'built_at': 'fixture', 'launcher_capabilities': ['stop-entry-v1', 'desktop-control-v1']}))
            self.assertEqual(validate_package(home)['built_at'], 'fixture')
            (home / 'user-data').mkdir()
            with self.assertRaisesRegex(ValueError, 'runtime state'):
                validate_package(home)

    def test_stop_targets_only_selected_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            signal = StopSignal(state)
            try:
                request_stop(state / 'other')
                signal.check()
                request_stop(state)
                with self.assertRaises(KeyboardInterrupt):
                    signal.check()
            finally:
                signal.close()
            self.assertEqual(request_stop(state), 0)


if __name__ == '__main__':
    unittest.main()
