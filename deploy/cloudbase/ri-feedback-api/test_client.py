"""Small offline functional checks; no cloud requests or production data."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client import CloudClient, FeedbackError, LocalStore, WindowsProtection, run

ROOT = Path(__file__).resolve().parents[3]
TEMP = ROOT / '.cache/cloudbase/offline-checks'
TEMP.mkdir(parents=True, exist_ok=True)
PILOT, ADMIN = 'a' * 64, 'b' * 64
IDENTIFIER = '11111111-1111-4111-8111-111111111111'


class TestProtection:
    # Deterministic test substitute only. Production always uses Windows DPAPI.
    def protect(self, data):
        return b'test:' + data

    def unprotect(self, data):
        if not data.startswith(b'test:'):
            raise ValueError()
        return data[5:]


class Checks(unittest.TestCase):
    def test_persist_retry_readback_and_admin(self):
        calls = []
        response = {'id': IDENTIFIER, 'status': 'open', 'processing_note': '', 'state_revision': 0,
                    'created_at': '2026-11-27', 'updated_at': '2026-11-27'}

        def send(method, url, headers, body):
            calls.append((method, url, headers, body))
            if len(calls) == 1:
                raise FeedbackError('simulated timeout')
            if '/admin/' in url:
                self.assertEqual(headers['Authorization'], 'Bearer ' + ADMIN)
                if method == 'GET':
                    return {'feedback': [{**response, 'payload': {'message': 'test'}}]}
                update = json.loads(body)
                self.assertEqual(update['expected_revision'], 0)
                response.update(status=update['status'], processing_note=update['processing_note'], state_revision=1)
            else:
                self.assertEqual(headers['x-ri-pilot-token'], PILOT)
                if method == 'GET':
                    self.assertEqual(headers['Authorization'], 'Bearer ' + original['receipt_token'])
            return {'feedback': dict(response)}

        client = CloudClient(send=send)
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            with LocalStore(directory, TestProtection()) as store:
                item = store.draft('test', 'paper-1')
                original = dict(item['request'])
                self.assertEqual(calls, [])
                with self.assertRaises(FeedbackError):
                    store.send(client, item, PILOT)
            with LocalStore(directory, TestProtection()) as store:
                item = store.data['items'][0]
                self.assertEqual(item['request'], original)
                store.send(client, item, PILOT)
                self.assertEqual(calls[0][3], calls[1][3])
                rows = client.queue(ADMIN)
                client.update(rows[0], ADMIN, 'resolved', 'Done')
                store.refresh(client, item, PILOT)
            with LocalStore(directory, TestProtection()) as store:
                self.assertEqual(store.data['items'][0]['cloud']['processing_note'], 'Done')
                self.assertEqual(store.data['items'][0]['cloud']['state_revision'], 1)
                local = store.path.read_text()
                self.assertNotIn(ADMIN, local)
                self.assertNotIn(PILOT, local)

    def test_corrupt_file_and_second_window_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            with LocalStore(directory, TestProtection()) as first:
                with self.assertRaises(FeedbackError):
                    with LocalStore(directory, TestProtection()):
                        pass
                first.path.write_bytes(b'corrupt')
            with self.assertRaises(FeedbackError):
                with LocalStore(directory, TestProtection()):
                    pass
            self.assertEqual((Path(directory) / 'feedback.dpapi').read_bytes(), b'corrupt')
            self.assertFalse((Path(directory) / 'session.lock').exists())

    def test_invalid_draft_and_secret_never_call_transport(self):
        def forbidden(*args):
            self.fail('Unexpected cloud request')
        client = CloudClient(send=forbidden)
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            with LocalStore(directory, TestProtection()) as store:
                for message in ('', '中' * 800):
                    with self.assertRaises(FeedbackError):
                        store.draft(message)
                item = store.draft('valid')
                with self.assertRaises(FeedbackError):
                    store.send(client, item, 'not-a-token')
                with self.assertRaises(FeedbackError):
                    store.refresh(client, item, PILOT)
        for address in ('http://example.com', 'https://user:secret@example.com', 'https://example.com/?key=a'):
            with self.assertRaises(FeedbackError):
                CloudClient(address, forbidden)

    def test_console_draft_list_and_exit_are_offline(self):
        def forbidden(*args):
            self.fail('Unexpected cloud request')
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            with LocalStore(directory, TestProtection()) as store:
                with patch('builtins.input', side_effect=['2', 'offline draft', '', '1', '0']):
                    with contextlib.redirect_stdout(io.StringIO()):
                        run(store, CloudClient(send=forbidden))
                self.assertEqual(len(store.data['items']), 1)
                self.assertIsNone(store.data['items'][0]['cloud'])

    @unittest.skipUnless(os.name == 'nt' and '--windows-protection' in sys.argv,
                         'Run explicitly from the normal Windows user session with --windows-protection')
    def test_actual_windows_dpapi_roundtrip(self):
        protection = WindowsProtection()
        original = b'local receipt verification, no real credentials'
        protected = protection.protect(original)
        self.assertNotIn(original, protected)
        self.assertEqual(protection.unprotect(protected), original)


if __name__ == '__main__':
    sys.argv = [arg for arg in sys.argv if arg != '--windows-protection']
    unittest.main(verbosity=2)
