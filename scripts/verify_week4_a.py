"""Run real A worker + integrated B HTTP flow with temporary data and real papers."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

from app.ingest import openalex_work_row
from app.paths import PROJECT_ROOT, project_path


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('examples/cvpr_2024_full/cvpr_2024.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('reports/week4-a-integration'))
    parser.add_argument('--browser-executable', type=Path, help='Also verify withdrawal retry in a real browser')
    args = parser.parse_args()
    records = []
    with project_path(args.input).open() as source:
        for line in source:
            work = json.loads(line)
            if work.get('abstract_inverted_index'):
                records.append({'source': 'openalex', 'row': openalex_work_row(work, 'CVPR', 2024)})
            if len(records) == 30:
                break
    if len(records) != 30:
        raise ValueError('Need 30 real OpenAlex papers with abstracts')
    output = project_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    a_url, web = f'http://127.0.0.1:{port()}', f'http://127.0.0.1:{port()}'
    password, token = secrets.token_hex(18), secrets.token_hex(24)
    with tempfile.TemporaryDirectory(prefix='a-week4-http-') as temporary:
        root = Path(temporary)
        env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(root/'a.db'), 'ADMIN_TOKEN': token,
            'A_ADMIN_TOKEN': token, 'A_API_BASE_URL': a_url, 'LOCAL_DEMO': '0',
            'ADMIN_USERNAME': 'acceptance', 'ADMIN_PASSWORD': password, 'SESSION_SECRET': secrets.token_hex(40),
            'D_USER_STORE': str(root/'users.json'), 'B_BATCH_REGISTRY': str(root/'b/ledger.json'),
            'B_SOURCE_CACHE': str(root/'b/cache'), 'B_SOURCE_OFFLINE': 'true',
            'B_SOURCE_CORPUS': '', 'B_VOCABULARY_PATH': '',
            'ALLOWED_ORIGINS': web,
            'B_API_BASE_URL': web, 'B_ADMIN_USERNAME': 'acceptance', 'B_ADMIN_PASSWORD': password,
            'B_REVIEWS_DIR': str(root/'reviews'), 'A_REPORT_ROOT': str(root/'artifacts'), 'AUTO_GRAPH_SYNC': 'false'}
        children = []
        with (output/'services.log').open('w') as log:
            try:
                for command in ([sys.executable, '-m', 'uvicorn', 'app.api:app', '--port', a_url.rsplit(':', 1)[1]],
                    [sys.executable, '-m', 'uvicorn', 'server.api.main:create_app', '--factory', '--port', web.rsplit(':', 1)[1]],
                    [sys.executable, '-m', 'app.worker']):
                    children.append(subprocess.Popen(command, cwd=PROJECT_ROOT, env=env, stdout=log, stderr=log))
                with requests.Session() as a, requests.Session() as browser:
                    a.trust_env = browser.trust_env = False
                    a.headers['Authorization'] = 'Bearer ' + token
                    for base, health in ((a_url, '/health'), (web, '/api/health')):
                        for _ in range(300):
                            if any(child.poll() is not None for child in children):
                                raise RuntimeError('Service exited; see services.log')
                            try:
                                if a.get(base + health, timeout=1).ok:
                                    break
                            except requests.RequestException:
                                pass
                            time.sleep(.1)
                        else:
                            raise RuntimeError('Service startup timed out')
                    def request(http, method, url, body=None):
                        result = http.request(method, url, json=body, timeout=120)
                        result.raise_for_status()
                        return result.json()
                    login = request(browser, 'POST', web + '/api/admin/sessions',
                                    {'username': 'acceptance', 'password': password})
                    browser.headers['X-CSRF-Token'] = login['csrf_token']
                    def wait(identifier, kind):
                        for _ in range(600):
                            value = request(browser, 'GET', web + f'/api/admin/{kind}/{identifier}')
                            if value['status'] == 'failed':
                                raise RuntimeError(value['error'])
                            if value['status'] == 'succeeded':
                                return value
                            time.sleep(.1)
                        raise RuntimeError('Task timed out')
                    def ingest(key, rows):
                        created = request(a, 'POST', a_url + '/api/admin/formal/batches',
                            dict(batch_key=key, venue='CVPR', year=2024, records=rows))
                        for _ in range(300):
                            value = request(a, 'GET', a_url + f'/api/admin/formal/batches/{created["batch_id"]}')
                            if value['status'] == 'succeeded':
                                return value
                            if value['status'] == 'failed':
                                raise RuntimeError('Import failed')
                            time.sleep(.1)
                        raise RuntimeError('Import timed out')
                    def send(document, key):
                        for _ in range(300):
                            listing = request(browser, 'GET', web + '/api/admin/handoffs?page_size=100')
                            task = next((t for t in listing['items'] if t['batch_id']==document['batch_id']
                                         and t['batch_revision']==document['batch_revision']), None)
                            if task:
                                return wait(task['id'], 'handoffs')
                            time.sleep(.1)
                        raise RuntimeError('Automatic handoff was not created')
                    assert browser.post(web+'/api/admin/handoffs',json={}).status_code==405
                    first = ingest('week4-first', records[:20])
                    r1 = send(first, 'first-send')
                    assert r1['result']['b_paper_count'] == 20
                    same = send(first, 'repeat-send')
                    assert same['result']['b_paper_count'] == 20 and same['id'] == r1['id']
                    second = ingest('week4-second', records[10:])
                    r2 = send(second, 'second-send')
                    assert r2['result']['b_paper_count'] == 30
                    bsection = request(browser, 'GET', web + '/api/admin/report-inputs/B')
                    report = request(browser, 'POST', web + '/api/admin/reports',
                        dict(request_key='real-report', title='第四周真实论文与知识报告', sections=[bsection]))
                    completed = wait(report['id'], 'reports')
                    download = browser.get(web + f'/api/admin/reports/{report["id"]}/download', timeout=120)
                    download.raise_for_status()
                    assert download.headers['content-type'] == 'application/zip'
                    assert hashlib.sha256(download.content).hexdigest() == download.headers['x-content-sha256']
                    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
                        manifest = json.loads(bundle.read('manifest.json'))
                        assert manifest['paper_count'] == 30 and manifest['providers']['B'] == bsection['revision']
                        attachment = json.loads(bundle.read('b-report.json'))
                        assert attachment['format_version'] == 'knowledge-report/1'
                        assert attachment['scope']['knowledge_revision'] == bsection['revision']
                        assert json.loads(bundle.read('b-author-tags.json')) == attachment['author_tags']
                        assert json.loads(bundle.read('b-quality.json')) == attachment['quality']
                        assert attachment['quality']['accuracy']['precision'] is None
                        for f in manifest['files']:
                            assert hashlib.sha256(bundle.read(f['name'])).hexdigest() == f['sha256']
                    (output/'report.zip').write_bytes(download.content)
                    withdrawn = request(browser, 'POST', web + f'/api/admin/formal/batches/{second["batch_id"]}/withdraw',
                                        {'reason': 'Week 4 isolated HTTP acceptance'})
                    r3 = wait(withdrawn['b_notification']['id'], 'handoffs')
                    repeated_withdrawal = request(browser, 'POST', web + f'/api/admin/formal/batches/{second["batch_id"]}/withdraw',
                                                  {'reason': 'Repeat withdrawal'})
                    assert repeated_withdrawal['b_notification']['id'] == r3['id']
                    assert r3['result']['b_paper_count'] == 20
                    stable_download = browser.get(web + f'/api/admin/reports/{report["id"]}/download', timeout=60)
                    assert stable_download.content == download.content
                    current = request(browser, 'POST', web + '/api/admin/reports', {'request_key': 'current-after-withdrawal'})
                    assert wait(current['id'], 'reports')['result']['paper_count'] == 20
                    pipeline = request(browser, 'GET', web + f'/api/admin/handoffs/{r3["id"]}/pipeline')
                    assert pipeline['stages']['C']['status'] != 'succeeded'
                    # B's partial offline source enrichment must not hide readable knowledge.
                    assert pipeline['stages']['B']['status'] == 'succeeded'
                    assert pipeline['stages']['B']['results']['available']
                    previous_revision = bsection['revision']
                    stale = browser.get(web + '/api/admin/report-inputs/B', params={'expected_revision': previous_revision})
                    assert stale.status_code == 409
                    last = request(browser, 'POST', web + f'/api/admin/jobs/{first["batch_id"]}/withdraw',
                                   {'reason': 'Withdraw all isolated batches'})
                    r4 = wait(last['b_notification']['id'], 'handoffs')
                    assert r4['result']['b_paper_count'] == 0
                    empty_section = request(browser, 'GET', web + '/api/admin/report-inputs/B')
                    assert empty_section['paper_ids'] == []
                    assert empty_section['data']['quality']['counts']['papers'] == 0
                    empty_report = request(browser, 'POST', web + '/api/admin/reports',
                                           {'request_key': 'empty-report', 'sections': [empty_section]})
                    assert wait(empty_report['id'], 'reports')['result']['paper_count'] == 0
                    browser_verified = False
                    if args.browser_executable:
                        import sqlite3
                        from playwright.sync_api import sync_playwright, expect
                        # Seed one failed notification in this disposable DB to exercise
                        # the actual retry endpoint and idempotent B withdrawal from UI.
                        with sqlite3.connect(root/'a.db') as db:
                            db.execute("UPDATE a_workflow_tasks SET status='failed', stage='failed', error='Browser retry fixture', result_json=NULL WHERE id=?", (r4['id'],))
                        with sync_playwright() as playwright:
                            browser_ui = playwright.chromium.launch(headless=True, executable_path=str(args.browser_executable))
                            context = browser_ui.new_context(viewport={'width': 1440, 'height': 1000})
                            context.add_cookies([{'name': cookie.name, 'value': cookie.value, 'url': web} for cookie in browser.cookies])
                            page = context.new_page()
                            js_errors = []
                            page.on('pageerror', lambda exc: js_errors.append(str(exc)))
                            page.goto(web + '/admin/jobs?job_id=' + str(first['batch_id']))
                            expect(page.get_by_role('button', name='重试通知', exact=True)).to_be_visible(timeout=30000)
                            page.get_by_role('button', name='重试通知', exact=True).click()
                            expect(page.locator('.formal-controls').get_by_text('B 撤回通知：已确认', exact=False)).to_be_visible(timeout=60000)
                            page.reload()
                            expect(page.locator('.formal-controls').get_by_text('B 撤回通知：已确认', exact=False)).to_be_visible(timeout=30000)
                            page.goto(web + '/admin/handoffs?task_id=' + r4['id'])
                            expect(page.get_by_role('heading', name='自动交接与版本状态', exact=True)).to_be_visible(timeout=30000)
                            expect(page.get_by_role('button', name='一键交接给 B', exact=True)).to_have_count(0)
                            expect(page.get_by_role('heading', name='自动交接与对账', exact=True)).to_be_visible()
                            page.goto(web + '/admin/reports?task_id=' + report['id'])
                            expect(page.get_by_role('link', name='下载完整 ZIP', exact=True)).to_be_visible(timeout=30000)
                            with page.expect_download() as old_report_download:
                                page.get_by_role('link', name='下载完整 ZIP', exact=True).click()
                            assert Path(old_report_download.value.path()).read_bytes()==download.content
                            page.get_by_role('radio', name='仅 A：当前有效论文、来源和数据质量', exact=True).check()
                            page.get_by_role('button', name='创建报告任务', exact=True).click()
                            page.wait_for_url(lambda url: 'task_id=' in url and report['id'] not in url, timeout=30000)
                            ui_task_id=page.url.split('task_id=')[1].split('&')[0]
                            expect(page.get_by_role('link', name='下载完整 ZIP', exact=True)).to_have_attribute('href','/api/admin/reports/'+ui_task_id+'/download',timeout=60000)
                            assert request(browser,'GET',web+'/api/admin/reports/'+ui_task_id)['result']['paper_count']==0
                            assert not js_errors, js_errors
                            browser_verified = True
                            browser_ui.close()
                    result = dict(actual_http=True, real_papers=True, input_source=str(args.input),
                        b_paper_counts=[20, 30, 20, 0], withdrawal_browser_retry=browser_verified, workflow_center_browser=browser_verified, automatic_withdrawal_notification=True,
                        repeated_withdrawal_same_task=True, b_native_report_tags_quality=True, stale_knowledge_rejected=True, repeated_delivery='same automatic task', no_manual_handoff=True,
                        report_papers=30, post_withdrawal_report_papers=20, historical_report_unchanged=True,
                        manifest_checksums_verified=True, zip_header_verified=True, b_section_included=True,
                        c_publication='not_run', pipeline= pipeline)
                    (output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
                    print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                for child in children:
                    child.terminate()
                for child in children:
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()


if __name__ == '__main__':
    main()
