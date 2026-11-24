"""Packaging invariants, no installation, builds, databases or services."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server.process_command import module_command
from portable import load_credentials
from build_portable import extract_runtime, RULE_RESOURCES
from types import SimpleNamespace
from native import neo4j_command, redacted_output


class PortableTests(unittest.TestCase):
    def test_packaged_rule_data_can_compute_b_version_for_both_modes(self):
        import src.knowledge_builder.effective_export as effective
        source = Path(effective.__file__).parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (*RULE_RESOURCES, 'vocabulary_cv.json'):
                (root / name).write_bytes((source / name).read_bytes())
            with patch.object(effective, '__file__', str(root / 'effective_export.py')):
                for records in (None, {}):
                    self.assertEqual(len(effective._rule_fingerprint(SimpleNamespace(source_records=records))), 64)

    def test_native_command_keeps_space_and_unicode_path_as_one_argument(self):
        home = Path('C:/portable folder/便携测试/runtime/neo4j')
        command = neo4j_command(home, 'dbms', 'set-initial-password', 'fixture-secret', admin=True)
        self.assertNotIn('cmd.exe', command)
        self.assertEqual(command[0], str(home.parent / 'java/bin/java.exe'))
        self.assertEqual(command[2], str(home / 'lib/*'))
        self.assertEqual(command[3], f'-Dbasedir={home}')
        self.assertEqual(command[4], 'org.neo4j.server.startup.Neo4jAdminCommand')
        self.assertEqual(command[-3:], ['dbms', 'set-initial-password', 'fixture-secret'])

    def test_server_command_uses_same_unmodified_directory(self):
        home = Path('C:/portable folder/便携测试/runtime/neo4j')
        command = neo4j_command(home, 'console')
        self.assertEqual(command[3], f'-Dbasedir={home}')
        self.assertEqual(command[-2:], ['org.neo4j.server.startup.Neo4jCommand', 'console'])

    def test_initialization_diagnostics_redact_credentials(self):
        text = redacted_output(b'failure example-secret: code 1', {'NEO4J_PASSWORD': 'example-secret'})
        self.assertNotIn('example-secret', text)
        self.assertIn('code 1', text)

    def test_frozen_worker_command_does_not_invoke_python_m(self):
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(module_command('app.worker'),
                             [sys.executable, '--internal-module', 'app.worker'])

    def test_source_worker_command_is_unchanged(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(module_command('app.worker'), [sys.executable, '-m', 'app.worker'])

    def test_credentials_are_generated_once_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            first = load_credentials(path)
            self.assertEqual(first, load_credentials(path))
            self.assertNotEqual(first['ADMIN_PASSWORD'], first['NEO4J_PASSWORD'])

    def test_invalid_credentials_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            path.write_text(json.dumps({'ADMIN_PASSWORD': 'short'}))
            original = path.read_bytes()
            with self.assertRaises(RuntimeError):
                load_credentials(path)
            self.assertEqual(original, path.read_bytes())

    def test_neo4j_archive_never_copies_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'neo.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for relative in ('bin/neo4j.bat', 'conf/neo4j.conf', 'LICENSE.txt',
                                 'data/dbms/auth.ini', 'logs/debug.log', 'run/neo4j.pid'):
                    bundle.writestr('neo4j/' + relative, 'fixture')
            extract_runtime(archive, root / 'out', neo4j=True)
            self.assertTrue((root / 'out/bin/neo4j.bat').exists())
            self.assertTrue((root / 'out/LICENSE.txt').exists())
            self.assertFalse((root / 'out/data').exists())
            self.assertFalse((root / 'out/logs').exists())
            self.assertFalse((root / 'out/run').exists())

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'bad.zip', 'w') as bundle:
                bundle.writestr('runtime/../../escape.txt', 'fixture')
            with self.assertRaises(ValueError):
                extract_runtime(root / 'bad.zip', root / 'out')
            self.assertFalse((root / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
