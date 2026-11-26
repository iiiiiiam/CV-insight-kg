"""Exercise schedule controls against real HTTP services and frozen real paper inputs."""
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

import requests

from app.paths import PROJECT_ROOT, project_path


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def fixture_scheduler(root):
    """Only the network collector is replaced; DB, scheduler, worker and API are real."""
    from unittest.mock import patch
    from app.db import SessionLocal, seed_sources
    from app.scheduler import ensure_default, recover_scheduler, heartbeat, tick
    from app.worker_lock import worker_lock
    records = json.loads((root/'records.json').read_text())
    def collect(venue, year, directory, **kwargs):
        assert kwargs['require_all_sources']
        if (root/'phase.txt').read_text() == 'fail':
            raise OSError('Browser verification: temporary source failure')
        (directory/'formal-input.json').write_text(json.dumps(dict(format_version='a-formal-input/1',
            venue=venue, year=year, records=records)))
    with worker_lock(SessionLocal, role='scheduler') as check:
        seed_sources(); ensure_default(SessionLocal); recover_scheduler(SessionLocal)
        with patch('app.scheduler.freeze_baseline'), patch('app.scheduler.load_baseline'):
            while True:
                heartbeat(SessionLocal)
                tick(SessionLocal, collector=collect, owner_check=check)
                time.sleep(.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-scheduler', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--browser-executable', type=Path)
    parser.add_argument('--output', type=Path, default=Path('reports/schedule-browser'))
    args = parser.parse_args()
    if args.fixture_scheduler:
        fixture_scheduler(args.fixture_scheduler)
        return
    from playwright.sync_api import sync_playwright, expect
    from app.ingest import openalex_work_row
    output = project_path(args.output); output.mkdir(parents=True, exist_ok=True)
    records = []
    with (PROJECT_ROOT/'examples/cvpr_2024_full/cvpr_2024.jsonl').open() as source:
        for line in source:
            work = json.loads(line)
            if work.get('abstract_inverted_index'):
                records.append({'source': 'openalex', 'row': openalex_work_row(work, 'CVPR', 2024)})
            if len(records) == 3:
                break
    assert len(records) == 3
    a_port, web_port = free_port(), free_port()
    a_url, web = f'http://127.0.0.1:{a_port}', f'http://127.0.0.1:{web_port}'
    checks, errors, bad, expected_errors = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='schedule-browser-') as temporary:
        root = Path(temporary)
        (root/'records.json').write_text(json.dumps(records))
        (root/'phase.txt').write_text('fail')
        baseline = root/'baseline/cvpr_2024'; baseline.mkdir(parents=True)
        for name in ('baseline.html', 'baseline.json'):
            (baseline/name).write_text('Browser-only isolated baseline fixture')
        password, token = secrets.token_hex(18), secrets.token_hex(24)
        env = {**os.environ, 'DATABASE_URL': 'sqlite:///'+str(root/'a.db'), 'ADMIN_TOKEN': token,
            'A_API_BASE_URL': a_url, 'A_ADMIN_TOKEN': token, 'LOCAL_DEMO': '0',
            'ADMIN_USERNAME': 'verification', 'ADMIN_PASSWORD': password, 'SESSION_SECRET': secrets.token_hex(40),
            'D_USER_STORE': str(root/'users.json'), 'B_BATCH_REGISTRY': str(root/'b/ledger.json'),
            'ALLOWED_ORIGINS': web,
            'B_SOURCE_CORPUS': '', 'B_SOURCE_OFFLINE': 'true', 'B_VOCABULARY_PATH': '',
            'AUTO_GRAPH_SYNC': 'false', 'A_COLLECTION_ROOT': str(root/'baseline'),
            'A_SCHEDULE_ROOT': str(root/'captures')}
        children = []
        with (output/'services.log').open('w') as log:
            def spawn(command):
                child = subprocess.Popen(command, cwd=PROJECT_ROOT, env=env, stdout=log, stderr=log)
                children.append(child)
                return child
            try:
                spawn([sys.executable, '-m', 'uvicorn', 'app.api:app', '--port', str(a_port)])
                spawn([sys.executable, '-m', 'uvicorn', 'server.api.main:create_app', '--factory', '--port', str(web_port)])
                spawn([sys.executable, '-m', 'app.worker'])
                fixture_command = [sys.executable, '-m', 'scripts.verify_schedule_frontend', '--fixture-scheduler', str(root)]
                scheduler = spawn(fixture_command)
                with requests.Session() as http:
                    http.trust_env = False
                    for base, health in ((a_url, '/health'), (web, '/api/health')):
                        for _ in range(200):
                            if any(p.poll() is not None for p in children):
                                raise RuntimeError('Service exited; see services.log')
                            try:
                                if http.get(base+health, timeout=.5).ok:
                                    break
                            except requests.RequestException:
                                pass
                            time.sleep(.1)
                        else:
                            raise RuntimeError('Service startup timed out')
                with sync_playwright() as pw:
                    options = {'headless': True}
                    if args.browser_executable:
                        options['executable_path'] = str(args.browser_executable)
                    browser = pw.chromium.launch(**options)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                    session = context.request.post(web+'/api/admin/sessions', data={'username': 'verification', 'password': password})
                    assert session.ok
                    page = context.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    def response(r):
                        if '/api/' in r.url and r.status >= 400:
                            target = expected_errors if r.status == 503 and r.url.endswith('/api/admin/formal/schedules') else bad
                            target.append({'status': r.status, 'url': r.url})
                    page.on('response', response)
                    def api(path):
                        r = page.request.get(web+path)
                        assert r.ok, (path, r.status)
                        return r.json()
                    def wait_run(identifier, state):
                        for _ in range(200):
                            value = api('/api/admin/formal/schedules')
                            found = next((r for r in value['runs'] if r['run_id'] == identifier), None)
                            if found and found['status'] == state:
                                return found
                            time.sleep(.1)
                        raise RuntimeError(f'Run {identifier} never reached {state}')
                    page.goto(web+'/admin/sources')
                    panel = page.get_by_role('region', name='定时采集与入库', exact=True)
                    expect(panel.get_by_text('调度服务已连接', exact=True)).to_be_visible(timeout=20000)
                    time_field = panel.get_by_label('每日执行时间', exact=True)
                    selected_time = (datetime.now(ZoneInfo('Asia/Shanghai'))+timedelta(hours=2)).strftime('%H:%M')
                    time_field.fill(selected_time)
                    panel.get_by_label('采集 CVPR:2024', exact=True).check()
                    for scope in ('CVPR:2023', 'CVPR:2025', 'ICCV:2021', 'ICCV:2023', 'ICCV:2025'):
                        panel.get_by_label('采集 '+scope, exact=True).uncheck()
                    panel.get_by_label('采集最多尝试次数', exact=True).fill('1')
                    panel.get_by_label('采集重试间隔', exact=True).fill('1')
                    panel.get_by_label('启用每日定时采集', exact=True).check()
                    panel.get_by_role('button', name='保存定时计划', exact=True).click()
                    expect(panel.get_by_text('定时计划已启用，将按保存的时间执行。', exact=True)).to_be_visible()
                    saved = api('/api/admin/formal/schedules')['schedules'][0]
                    assert saved['enabled'] and saved['scopes'] == ['CVPR:2024'] and saved['time'] == selected_time
                    checks.append('save time/timezone/scopes/retry settings and enable daily schedule')
                    dirty = '23:15' if selected_time != '23:15' else '01:23'
                    time_field.fill(dirty)
                    with page.expect_response(lambda r: r.url.endswith('/api/admin/formal/schedules') and r.request.method == 'GET'):
                        pass
                    expect(time_field).to_have_value(dirty)
                    panel.get_by_role('button', name='重新读取计划', exact=True).click()
                    expect(time_field).to_have_value(selected_time)
                    checks.append('background polling preserves unsaved edits; explicit reload restores saved plan')
                    panel.get_by_role('button', name='执行一次', exact=True).click()
                    for _ in range(100):
                        runs = api('/api/admin/formal/schedules')['runs']
                        if runs:
                            break
                        time.sleep(.1)
                    identifier = runs[0]['run_id']
                    wait_run(identifier, 'failed')
                    expect(panel.get_by_role('button', name=f'重试运行 #{identifier}', exact=True)).to_be_visible(timeout=15000)
                    (root/'phase.txt').write_text('success')
                    panel.get_by_role('button', name=f'重试运行 #{identifier}', exact=True).click()
                    completed = wait_run(identifier, 'succeeded')
                    assert completed['tasks'][0]['attempts'] == 2 and completed['tasks'][0]['retry_round'] == 1
                    panel.get_by_role('button', name='刷新运行记录', exact=True).click()
                    link = panel.get_by_role('link', name=re.compile(r'查看 A-'))
                    expect(link).to_be_visible(timeout=15000)
                    link.click()
                    expect(page.get_by_role('link', name='← 返回来源配置', exact=True)).to_be_visible()
                    page.get_by_role('link', name='查看本批论文 →', exact=True).click()
                    expect(page.get_by_role('link', name='← 返回来源配置', exact=True)).to_be_visible()
                    page.get_by_role('link', name='← 返回来源配置', exact=True).click()
                    expect(panel).to_be_visible()
                    assert api('/api/admin/data-overview')['total_papers'] == 3
                    checks.append('real failure, same-run manual retry, automatic A batch, detail and return links')
                    panel.get_by_label('启用每日定时采集', exact=True).uncheck()
                    panel.get_by_role('button', name='保存定时计划', exact=True).click()
                    expect(panel.get_by_text('每日计划未启用。', exact=False)).to_be_visible()
                    panel.get_by_role('button', name='执行一次', exact=True).click()
                    for _ in range(100):
                        latest = api('/api/admin/formal/schedules')['runs'][0]
                        if latest['run_id'] != identifier:
                            break
                        time.sleep(.1)
                    unchanged = wait_run(latest['run_id'], 'unchanged')
                    assert unchanged['tasks'][0]['unchanged_records'] == 3
                    assert len(api('/api/admin/jobs')) == 1
                    checks.append('pause future triggers; one-off execution still works and unchanged papers create no batch')
                    scheduler.terminate(); scheduler.wait(timeout=10)
                    scheduler = spawn(fixture_command)
                    page.reload()
                    expect(time_field).to_have_value(selected_time, timeout=15000)
                    assert not api('/api/admin/formal/schedules')['schedules'][0]['enabled']
                    checks.append('scheduler restart preserves saved plan and completed run without repeated import')
                    page.route('**/api/admin/formal/schedules', lambda route: route.fulfill(status=503, json={'error': {'message': '验证：暂时无法读取计划'}}))
                    panel.get_by_role('button', name='刷新运行记录', exact=True).click()
                    expect(panel.get_by_text('验证：暂时无法读取计划', exact=True)).to_be_visible()
                    page.unroute('**/api/admin/formal/schedules')
                    panel.get_by_role('button', name='刷新运行记录', exact=True).click()
                    expect(panel.get_by_text('验证：暂时无法读取计划', exact=True)).to_have_count(0)
                    checks.append('read failure is visible and refresh recovers')
                    panel.get_by_role('link', name=re.compile(r'查看 A-')).click()
                    page.get_by_role('button', name='撤回此批次', exact=True).click()
                    page.get_by_label('撤回原因', exact=True).fill('Browser verification: withdraw scheduled batch')
                    page.get_by_role('button', name='确认撤回', exact=True).click()
                    expect(page.locator('.withdrawn-state')).to_be_visible()
                    assert api('/api/admin/data-overview')['total_papers'] == 0
                    page.get_by_role('link', name='← 返回来源配置', exact=True).click()
                    expect(panel.get_by_text('已完成 · 批次已撤回', exact=True)).to_be_visible(timeout=15000)
                    checks.append('scheduled batch withdrawal updates current count and leaves run history visible')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                    checks.append('390px schedule form and run history have no horizontal overflow')
                    browser.close()
                assert not errors, errors
                assert not bad, bad
                result = dict(checks=checks, javascript_errors=errors, unexpected_failed_requests=bad,
                    expected_error_requests=expected_errors, real_paper_count=3,
                    collection_transport='frozen_real_openalex_fixture', live_source_network='not_tested',
                    original_user_database_modified=False)
                (output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                for child in children:
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__ == '__main__':
    main()
