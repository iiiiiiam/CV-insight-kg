"""Small integration checks with real local routes/storage and fake cloud transport."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import os
import unittest
from unittest.mock import patch

from tests.knowledge_builder.test_feedback_api import FeedbackAPITests, SERVER_READY

if SERVER_READY:
    from fastapi.testclient import TestClient
    from server.api.main import create_app

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / '.cache/cloudbase/integration-checks'
TEMP.mkdir(parents=True, exist_ok=True)


@unittest.skipUnless(SERVER_READY, 'Server dependencies required')
class CloudIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(FeedbackAPITests.setUpClass.__func__)
    reading = FeedbackAPITests.reading
    submit = FeedbackAPITests.submit
    login = FeedbackAPITests.login

    def setUp(self):
        # Existing fixture uses TemporaryDirectory; keep all test files on project D drive.
        self.enterContext(patch('tempfile.tempdir', str(TEMP)))
        FeedbackAPITests.setUp(self)
        self.calls = []
        self.remote = dict(id='11111111-1111-4111-8111-111111111111', status='open',
                           processing_note='', state_revision=0, created_at='now', updated_at='now')
        self.enterContext(patch('server.application.cloud_feedback.send_request', side_effect=self.transport))
        self.settings = replace(self.settings,
            cloud_feedback_url='https://offline.example/feedback', cloud_feedback_pilot_token='a' * 64,
            cloud_feedback_admin_token='b' * 64, cloud_feedback_store=str(self.store_path.parent / 'cloud.db'))
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        self.owner = 'c' * 64

    def transport(self, method, url, headers, body, **kwargs):
        if getattr(self, 'offline', False):
            from server.application.cloud_feedback import CloudFeedbackError
            raise CloudFeedbackError('offline')
        self.calls.append((method, url, headers, body))
        if url.endswith('/sessions'):
            if body != {'username': 'team-admin', 'password': 'valid-team-password'}:
                from server.application.cloud_feedback import CloudFeedbackError
                raise CloudFeedbackError('unauthorized')
            return {'access_token': 'ri1.offline.signature', 'expires_at': int(time.time())+3600,
                    'role':getattr(self,'team_role','admin'),'username':'team-admin'}
        if url.endswith('/admin/accounts'):
            account=dict(username='colleague',role='admin',enabled=True,revision=0,created_at='now',updated_at='now')
            return {'accounts':[account],'current_username':'team-admin'} if method=='GET' else {'account':account}
        if url.endswith('/account/password'):
            return {'account':dict(username='team-admin',role='admin',enabled=True,revision=1,created_at='now',updated_at='now')}
        if url.endswith('/admin/requests'):
            return {'feedback': [{**self.remote, 'payload': getattr(self,'remote_payload',{'message':'test'})}]}
        if method == 'PATCH':
            if body['expected_revision'] != self.remote['state_revision']:
                from server.application.cloud_feedback import CloudFeedbackError
                raise CloudFeedbackError('conflict')
            self.remote.update(status=body['status'], processing_note=body['processing_note'],
                               state_revision=self.remote['state_revision'] + 1)
        return {'feedback': dict(self.remote), 'duplicate': False}

    def test_cloud_completed_local_open_does_not_swallow_new_submission(self):
        first=self.submit(owner_token=self.owner).json()
        self.remote.update(status='resolved',processing_note='old reply',state_revision=1)
        refreshed=self.client.post('/api/knowledge/feedback/'+first['id']+'/cloud/refresh',
                                   json={'owner_token':self.owner})
        self.assertEqual(refreshed.status_code,200,refreshed.text)
        self.assertEqual(self.client.get('/api/knowledge/feedback/'+first['id']).json()['status'],'open')
        view=self.reading()
        candidate=next(item for item in view['entities'] if item['content'].get('name')=='LVIS')
        # Fake cloud assigns a different ID to the new feedback, as the real service does.
        self.remote.update(id='22222222-2222-4222-8222-222222222222',status='open',processing_note='',state_revision=0)
        count=len(self.calls)
        response=self.client.post('/api/knowledge/feedback',json=dict(paper_id=self.paper.openalex_id,
            revision=view['revision'],candidate_id=candidate['candidate_id'],message='new verification',owner_token=self.owner))
        self.assertEqual(response.status_code,201,response.text)
        second=response.json()
        self.assertFalse(second['duplicate'])
        self.assertNotEqual(second['id'],first['id'])
        self.assertEqual(second['message'],'new verification')
        self.assertEqual(second['cloud']['delivery'],'sent')
        self.assertEqual(len(self.calls),count+1)
        # Other owners' cached completions cannot bypass the current owner's deduplication.
        again=self.client.post('/api/knowledge/feedback',json=dict(paper_id=self.paper.openalex_id,
            revision=view['revision'],candidate_id=candidate['candidate_id'],message='new verification',owner_token=self.owner)).json()
        self.assertTrue(again['duplicate'])
        self.assertEqual(again['id'],second['id'])

    def test_guest_status_and_duplicate_keep_original_message(self):
        submitted=self.submit(owner_token=self.owner)
        self.assertEqual(submitted.status_code,201,submitted.text)
        first=submitted.json()
        view=self.reading()
        candidate=next(item for item in view['entities'] if item['content'].get('name')=='LVIS')
        second=self.client.post('/api/knowledge/feedback',json=dict(paper_id=self.paper.openalex_id,
            revision=view['revision'],candidate_id=candidate['candidate_id'],
            message='different description on same pending item',owner_token=self.owner))
        self.assertEqual(second.status_code,201,second.text)
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(second.json()['id'],first['id'])
        self.assertEqual(second.json()['message'],first['message'])
        count=len(self.calls)
        status=self.client.get('/api/knowledge/feedback/'+first['id'],headers={'X-Feedback-Owner':self.owner})
        self.assertEqual(status.status_code,200,status.text)
        self.assertEqual(status.json()['cloud']['delivery'],'sent')
        self.assertEqual(len(self.calls),count)

    def test_remote_feedback_uses_original_knowledge_rules(self):
        view=self.reading()
        candidate=next(item for item in view['entities'] if item['content'].get('name')=='LVIS')
        self.remote_payload=dict(message='remote correction',paper_id=self.paper.openalex_id,
            knowledge_revision=view['revision'],candidate_id=candidate['candidate_id'])
        headers=self.login()
        response=self.client.post('/api/admin/knowledge/feedback/team-refresh',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        queue=response.json();record=queue['requests'][0]
        self.assertTrue(record['cloud']['can_apply'])
        response=self.client.post('/api/admin/knowledge/feedback/'+record['id'],headers=headers,
            json=dict(revision=queue['revision'],cloud_revision=0,action='rename',
                      name='LVIS remote',reason='remote verified'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reply_delivery'],'sent')

    def test_unified_decision_and_reply_retry(self):
        submitted=self.submit(owner_token=self.owner).json()
        headers=self.login()
        queue=self.client.get('/api/admin/knowledge/feedback').json()
        self.assertEqual(len(queue['requests']),1)
        record=queue['requests'][0]
        self.assertTrue(record['id'].startswith('cloud:'))
        count=len(self.calls)
        self.client.get('/api/admin/knowledge/feedback')
        self.assertEqual(len(self.calls),count)
        self.offline=True
        response=self.client.post('/api/admin/knowledge/feedback/'+record['id'],headers=headers,
            json=dict(revision=queue['revision'],cloud_revision=0,action='rename',
                      name='LVIS unified',reason='已核对并修正名称'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reply_delivery'],'pending')
        saved=self.client.get('/api/admin/knowledge/feedback').json()
        self.assertEqual(saved['requests'][0]['resolution']['reason'],'已核对并修正名称')
        self.offline=False
        response=self.client.post('/api/admin/knowledge/feedback/'+record['id']+'/reply-retry',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reply_delivery'],'sent')
        final=self.client.get('/api/admin/knowledge/feedback').json()
        self.assertEqual(len(final['requests']),1)
        self.assertEqual(final['requests'][0]['cloud']['reply'],'已核对并修正名称')
        self.assertEqual(final['requests'][0]['resolution'],saved['requests'][0]['resolution'])
        reopened=self.client.post('/api/admin/knowledge/feedback/'+record['id']+'/reopen',headers=headers,
            json=dict(revision=final['revision'],cloud_revision=final['requests'][0]['cloud']['revision']))
        self.assertEqual(reopened.status_code,200,reopened.text)
        current=self.client.get('/api/admin/knowledge/feedback').json()['requests'][0]
        self.assertEqual(current['status'],'open')
        self.assertIsNone(current['resolution'])
        self.assertEqual(len(current['processing_history']),1)


    def test_submit_cached_status_manual_delivery_and_reply(self):
        result = self.submit(owner_token=self.owner)
        self.assertEqual(result.status_code, 201)
        identifier = result.json()['id']
        path = '/api/knowledge/feedback/' + identifier
        self.assertEqual(result.json()['cloud']['delivery'], 'sent')
        cached = self.client.get(path, headers={'X-Feedback-Owner': self.owner}).json()
        self.assertEqual(cached['cloud']['delivery'], 'sent')
        self.assertEqual(len(self.calls), 1)  # Submit auto-delivers once; reads are cache-only.
        self.assertEqual(self.client.post(path + '/cloud/send', json={'owner_token': 'd'*64}).status_code, 404)
        self.assertEqual(len(self.calls), 1)
        delivered = self.client.post(path + '/cloud/send', json={'owner_token': self.owner})
        self.assertEqual(delivered.status_code, 200)
        first_request = self.calls[-1][3]
        self.client.post(path + '/cloud/send', json={'owner_token': self.owner})
        self.assertEqual(self.calls[-1][3], first_request)
        self.assertNotIn('receipt_token', str(delivered.json()))
        self.assertNotIn('cloud', self.client.get(path).json())
        count = len(self.calls)
        self.client.get(path, headers={'X-Feedback-Owner': self.owner})
        self.assertEqual(len(self.calls), count)
        admin_headers = self.login()
        queue = self.client.post('/api/admin/knowledge/cloud-feedback/refresh', headers=admin_headers)
        self.assertEqual(queue.status_code, 200)
        remote_id = queue.json()['requests'][0]['id']
        reply = self.client.post('/api/admin/knowledge/cloud-feedback/' + remote_id + '/reply',
            headers=admin_headers, json=dict(status='resolved', processing_note='已收到', expected_revision=0))
        self.assertEqual(reply.status_code, 200)
        refreshed = self.client.post(path + '/cloud/refresh', json={'owner_token': self.owner})
        self.assertEqual(refreshed.json()['feedback']['processing_note'], '已收到')
        # Cloud processing is not a local knowledge decision.
        self.assertEqual(self.client.get(path).json()['status'], 'open')
        self.assertEqual(self.client.get('/api/admin/knowledge/feedback').json()['requests'][0]['resolution'], None)

    def test_admin_checks_and_no_automatic_cloud_calls(self):
        path = '/api/admin/knowledge/cloud-feedback/refresh'
        self.assertEqual(self.client.post(path).status_code, 401)
        self.login()
        self.assertEqual(self.client.post(path).status_code, 403)
        config = self.client.get('/api/admin/knowledge/cloud-feedback/config')
        self.assertTrue(config.json()['enabled'])
        self.assertTrue(config.json()['team_enabled'])
        self.assertFalse(config.json()['account_management'])
        self.assertNotIn(self.settings.cloud_feedback_admin_token, config.text)
        self.assertEqual(self.calls, [])

    def test_cloud_failure_keeps_local_feedback_and_request_identity(self):
        from server.application.cloud_feedback import CloudFeedbackError
        self.offline = True
        result = self.submit(owner_token=self.owner).json()
        self.assertEqual(result['cloud']['delivery'], 'pending')
        self.assertIn('cloud_error', result)
        self.offline = False
        path = '/api/knowledge/feedback/' + result['id']
        with patch('server.application.cloud_feedback.send_request', side_effect=CloudFeedbackError('offline')):
            # Create a new router so the fake transport is captured, as on restart.
            with TestClient(create_app(self.settings)) as client:
                failed = client.post(path + '/cloud/send', json={'owner_token': self.owner})
                self.assertEqual(failed.status_code, 503)
                self.assertEqual(client.get(path).json()['status'], 'open')
        sent = self.client.post(path + '/cloud/send', json={'owner_token': self.owner})
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(self.calls[-1][3]['local_feedback_id'], result['id'])

    def test_withdrawn_feedback_not_newly_sent(self):
        result = self.submit(owner_token=self.owner).json()
        path = '/api/knowledge/feedback/' + result['id']
        self.assertEqual(self.client.post(path + '/withdraw', json={'owner_token': self.owner}).status_code, 200)
        self.assertEqual(self.client.post(path + '/cloud/send', json={'owner_token': self.owner}).status_code, 409)
        self.assertEqual(len(self.calls), 1)  # No re-send after local withdrawal.

    def test_team_login_unavailable_is_not_bad_password_or_failure_count(self):
        from server.application.cloud_feedback import CloudFeedbackError
        settings=replace(self.settings,cloud_feedback_admin_token='',cloud_feedback_pilot_token='')
        app=create_app(settings)
        with TestClient(app) as client:
            with patch('server.application.cloud_feedback.send_request',side_effect=CloudFeedbackError('timeout',503)) as transport:
                for _ in range(6):
                    response=client.post('/api/admin/sessions',json={'username':'team-admin','password':'valid-team-password'})
                    self.assertEqual(response.status_code,503,response.text)
                self.assertEqual(transport.call_args.kwargs['timeout'],12)
                self.assertEqual(sum(len(value) for value in app.state.auth.failures.values()),0)
            response=client.post('/api/admin/sessions',json={'username':'team-admin','password':'valid-team-password'})
            self.assertEqual(response.status_code,200,response.text)

    def test_team_bad_password_still_401_and_rate_limit_stays_429(self):
        from server.application.cloud_feedback import CloudFeedbackError
        settings=replace(self.settings,cloud_feedback_admin_token='',cloud_feedback_pilot_token='')
        app=create_app(settings)
        with TestClient(app) as client:
            with patch('server.application.cloud_feedback.send_request',side_effect=CloudFeedbackError('rate limited',429)):
                response=client.post('/api/admin/sessions',json={'username':'team-admin','password':'wrong'})
                self.assertEqual(response.status_code,429,response.text)
                self.assertEqual(sum(len(value) for value in app.state.auth.failures.values()),0)
            with patch('server.application.cloud_feedback.send_request',side_effect=CloudFeedbackError('unauthorized',401)):
                response=client.post('/api/admin/sessions',json={'username':'team-admin','password':'wrong'})
                self.assertEqual(response.status_code,401,response.text)
                self.assertEqual(sum(len(value) for value in app.state.auth.failures.values()),1)

    def test_cloud_admin_uses_existing_login_and_no_shared_secrets(self):
        settings = replace(self.settings, cloud_feedback_pilot_token='', cloud_feedback_admin_token='',
                           cloud_feedback_store=None)
        with TestClient(create_app(settings)) as client:
            logged = client.post('/api/admin/sessions', json={'username':'team-admin', 'password':'valid-team-password'})
            self.assertEqual(logged.status_code, 200)
            self.assertNotIn('ri1.offline.signature', logged.text)
            csrf = {'X-CSRF-Token': logged.json()['csrf_token']}
            config = client.get('/api/admin/knowledge/cloud-feedback/config').json()
            self.assertTrue(config['team_enabled'])
            queue = client.post('/api/admin/knowledge/cloud-feedback/refresh', headers=csrf)
            self.assertEqual(queue.status_code, 200)
            self.assertEqual(self.calls[-1][2]['Authorization'], 'Bearer ri1.offline.signature')
            self.assertNotIn('x-ri-pilot-token', self.calls[0][2])
            self.assertEqual(client.delete('/api/session', headers=csrf).status_code, 204)
            self.assertEqual(client.post('/api/admin/knowledge/cloud-feedback/refresh', headers=csrf).status_code, 401)
        self.offline = True
        with TestClient(create_app(settings)) as client:
            # Local administrator still logs in while cloud is offline, but gains no team rights.
            logged = client.post('/api/admin/sessions', json={'username':settings.username,'password':settings.password})
            self.assertEqual(logged.status_code, 200)
            self.assertFalse(client.get('/api/admin/knowledge/cloud-feedback/config').json()['team_enabled'])

    def test_startup_defaults_need_no_cloud_keys_or_store_configuration(self):
        from server.configuration.settings import Settings, DEFAULT_CLOUD_FEEDBACK_URL
        from server.application.cloud_feedback import CloudFeedback
        with patch.dict(os.environ, {'ADMIN_PASSWORD':'offline-password', 'SESSION_SECRET':'s'*48}, clear=True), \
                patch('server.configuration.settings.load_dotenv'):
            settings = Settings.from_env()
        self.assertEqual(settings.cloud_feedback_url, DEFAULT_CLOUD_FEEDBACK_URL)
        self.assertEqual(settings.cloud_feedback_pilot_token, '')
        self.assertEqual(settings.cloud_feedback_admin_token, '')
        self.assertTrue(CloudFeedback(settings).path.endswith('cloud-feedback.db'))

    def test_account_management_requires_team_owner_and_csrf(self):
        settings=replace(self.settings,cloud_feedback_admin_token='',cloud_feedback_pilot_token='')
        body={'username':'colleague','password':'initial-password-123','role':'admin'}
        path='/api/admin/knowledge/cloud-feedback/accounts/create'
        with TestClient(create_app(settings)) as client:
            self.assertEqual(client.post(path,json=body).status_code,401)
            logged=client.post('/api/admin/sessions',json={'username':'team-admin','password':'valid-team-password'})
            csrf={'X-CSRF-Token':logged.json()['csrf_token']}
            self.assertEqual(client.post(path,json=body,headers=csrf).status_code,403)
        self.team_role='owner'
        with TestClient(create_app(settings)) as client:
            logged=client.post('/api/admin/sessions',json={'username':'team-admin','password':'valid-team-password'})
            csrf={'X-CSRF-Token':logged.json()['csrf_token']}
            self.assertTrue(client.get('/api/admin/knowledge/cloud-feedback/config').json()['account_management'])
            self.assertEqual(client.post(path,json=body).status_code,403)
            added=client.post(path,json=body,headers=csrf)
            self.assertEqual(added.status_code,200)
            self.assertNotIn(body['password'],added.text)
            self.assertEqual(self.calls[-1][2]['Authorization'],'Bearer ri1.offline.signature')
            changed=client.post('/api/admin/knowledge/cloud-feedback/password',headers=csrf,
                json={'current_password':'valid-team-password','new_password':'new-password-123'})
            self.assertEqual(changed.status_code,200)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(CloudIntegrationTests)


if __name__ == '__main__':
    unittest.main(verbosity=2)
