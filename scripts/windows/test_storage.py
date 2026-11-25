"""External storage checks without starting Java or application services."""
from pathlib import Path
import tempfile
import unittest

from storage import state_directory, prepare_neo4j_config


class StorageTests(unittest.TestCase):
    def test_portable_default_and_explicit_absolute_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertEqual(state_directory(home), home / 'user-data')
            self.assertEqual(state_directory(home, str(home / 'separate')), home / 'separate')
            with self.assertRaisesRegex(RuntimeError, 'absolute'):
                state_directory(home, 'relative-data')

    def test_external_config_keeps_runtime_unchanged_and_preserves_customizations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            neo, state = root / 'runtime/neo4j', root / 'state'
            (neo / 'conf').mkdir(parents=True)
            original = 'server.directories.data=data\nserver.memory.heap.max_size=512m\n'
            (neo / 'conf/neo4j.conf').write_text(original, encoding='utf-8')
            (neo / 'conf/server-logs.xml').write_text('fixture', encoding='utf-8')
            conf = prepare_neo4j_config(neo, state)
            result = (conf / 'neo4j.conf').read_text(encoding='utf-8')
            self.assertIn(f'server.directories.data={(state / "neo4j/data").as_posix()}', result)
            self.assertEqual(result.count('server.directories.data='), 1)
            self.assertIn('server.memory.heap.max_size=512m', result)
            self.assertEqual((neo / 'conf/neo4j.conf').read_text(encoding='utf-8'), original)
            self.assertEqual((conf / 'server-logs.xml').read_text(), 'fixture')
            (conf / 'neo4j.conf').write_text('custom settings', encoding='utf-8')
            prepare_neo4j_config(neo, state)
            self.assertEqual((conf / 'neo4j.conf').read_text(), 'custom settings')


if __name__ == '__main__':
    unittest.main()
