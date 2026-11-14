"""Exercise A pages against a copied database and real API/worker; leave the source database unchanged."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse,parse_qs
import requests
from app.paths import PROJECT_ROOT,project_path


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1',0));return connection.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True,help='Existing demo DB, copied before any write')
    parser.add_argument('--formal-input',type=Path,help='Optional real a-formal-input/1 file for batch withdrawal checks')
    parser.add_argument('--browser-executable',type=Path)
    parser.add_argument('--output',type=Path,default=Path('reports/frontend-check'))
    args=parser.parse_args()
    from playwright.sync_api import sync_playwright,expect
    from server.configuration.settings import Settings
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT/'server/.env',override=False);settings=Settings.from_env()
    source=project_path(args.database)
    if not source.is_file():raise ValueError('Demo database does not exist')
    output=project_path(args.output);output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];bad=[];expected_errors=[]
    with tempfile.TemporaryDirectory(prefix='a-frontend-') as temporary:
        root=Path(temporary);target=root/'preview.db'
        with sqlite3.connect(f'{source.as_uri()}?mode=ro',uri=True) as original,sqlite3.connect(target) as copied:original.backup(copied)
        with sqlite3.connect(target) as copied:
            copied.execute("UPDATE jobs SET status='failed',active_key=NULL,error='Isolated browser copy: existing jobs paused' WHERE status IN ('queued','running')")
            initial_oa_ids={r[0] for r in copied.execute('SELECT openalex_id FROM papers WHERE openalex_id IS NOT NULL')}
        port,api_port=free_port(),free_port();base=f'http://127.0.0.1:{port}'
        with (output/'service.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','server.run_local','--demo','--skip-build','--demo-db',str(target),'--port',str(port),'--api-port',str(api_port)],cwd=PROJECT_ROOT,stdout=log,stderr=log,**({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}))
            try:
                http=requests.Session();http.trust_env=False
                for _ in range(200):
                    if server.poll() is not None:raise RuntimeError('Preview failed to start; see service.log')
                    try:
                        if http.get(base+'/api/health',timeout=.5).ok:break
                    except requests.RequestException:pass
                    time.sleep(.1)
                else:raise RuntimeError('Preview startup timed out')
                with sync_playwright() as playwright:
                    options={'headless':True}
                    if args.browser_executable:options['executable_path']=str(args.browser_executable)
                    browser=playwright.chromium.launch(**options)
                    page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:bad.append({'status':r.status,'url':r.url}) if '/api/' in r.url and r.status>=400 else None)
                    page.goto(base+'/preview');expect(page.locator('.latest-table tbody tr')).to_have_count(20,timeout=30000)
                    def api(path):
                        response=page.request.get(base+path);assert response.ok,(path,response.status,response.text());return response.json()
                    before=api('/api/admin/data-overview?days=14')['total_papers']
                    page.goto(base+'/admin/sources');expect(page.get_by_role('checkbox',name='openalex 启用',exact=True)).to_be_visible()
                    enabled=page.get_by_role('checkbox',name='openalex 启用',exact=True)
                    original=enabled.is_checked();enabled.set_checked(not original)
                    page.get_by_role('button',name='保存配置',exact=True).click();expect(page.get_by_text('配置已保存',exact=True)).to_be_visible()
                    page.reload();expect(enabled).to_be_checked(checked=not original)
                    enabled.set_checked(original);page.get_by_role('button',name='保存配置',exact=True).click();expect(page.get_by_text('配置已保存',exact=True)).to_be_visible()
                    page.get_by_role('button',name='重新读取',exact=True).click();expect(enabled).to_be_enabled()
                    page.get_by_role('link',name='← 返回数据概览',exact=True).click();expect(page.locator('.metric-card').first).to_be_visible()
                    page.goto(base+'/admin/quality');expect(page.get_by_role('button',name='导出质量报告',exact=True)).to_be_enabled(timeout=30000)
                    page.get_by_role('textbox',name='质量论文标题',exact=True).fill('no-such-paper-quality-check');expect(page.get_by_text('没有符合条件的缺失记录。',exact=True)).to_be_visible()
                    page.get_by_role('textbox',name='质量论文标题',exact=True).fill('')
                    page.get_by_role('combobox',name='缺失字段',exact=True).select_option('abstract')
                    page.get_by_role('combobox',name='缺失字段',exact=True).select_option('')
                    scope_control=page.get_by_role('combobox',name='覆盖会议年度',exact=True)
                    if scope_control.count():
                        for value in scope_control.locator('option').evaluate_all('(els)=>els.map(e=>e.value)'):scope_control.select_option(value)
                    with page.expect_download() as quality_download:page.get_by_role('button',name='导出质量报告',exact=True).click()
                    assert json.loads(Path(quality_download.value.path()).read_text())['total_papers']==before
                    page.get_by_role('button',name='刷新质量',exact=True).click();expect(page.get_by_role('button',name='导出质量报告',exact=True)).to_be_enabled(timeout=30000)
                    page.get_by_role('link',name='← 返回数据概览',exact=True).click()
                    page.goto(base+'/admin/datasets');expect(page.locator('.dataset-grid article').first).to_be_visible();page.get_by_role('link',name='← 返回数据概览',exact=True).click()
                    checks.append('source settings save/reload/restore, quality filters/report export/coverage switching, datasets return')
                    expect(page.locator('.latest-table tbody tr')).to_have_count(20,timeout=30000)

                    for days in (7,14,7,14):
                        page.get_by_role('button',name=f'{days} 天',exact=True).click()
                        expect(page.locator('.bar-column')).to_have_count(days,timeout=15000)
                    checks.append('7/14 days switch and fast repeated switching')
                    trend=api('/api/admin/data-overview?days=14')['trend'];date=next((v['date'] for v in trend if v['papers']>10),trend[-1]['date'])
                    page.locator(f'.bar-column[title^="{date}"]').click();expect(page.locator('.day-detail .day-paper').first).to_be_visible()
                    total=api('/api/admin/new-papers?view=additions&day='+date)['total']
                    if total>10:
                        page.locator('.day-pages').get_by_role('button',name='下一页',exact=True).click();expect(page.locator('.day-pages')).to_contain_text('第 2 页')
                    page.locator('.day-detail').get_by_role('button',name='收起',exact=True).click()
                    links=page.locator('.latest-table a');assert links.count()==20
                    assert all(urlparse(href).scheme in ('http','https') for href in links.evaluate_all('(els)=>els.map(e=>e.href)'))
                    href=links.first.get_attribute('href')
                    page.context.route(href,lambda route:route.fulfill(status=200,body='Paper homepage navigation verified'))
                    with page.expect_popup() as popup:links.first.click()
                    popup.value.wait_for_load_state();assert popup.value.url==href;popup.value.close()
                    checks.append('daily papers/pagination/collapse and 20 real homepage links')
                    expect(page.locator('.schedule-panel')).to_have_count(0)
                    page.screenshot(path=str(output/'01-overview.png'),full_page=True)
                    page.get_by_role('link',name='导入论文',exact=True).click();expect(page.locator('#reserve-count')).to_be_visible()
                    box=page.locator('.reserve-card').bounding_box();container=page.locator('.import-layout').bounding_box();assert abs(box['width']-container['width'])<2
                    button=page.get_by_role('button',name='导入下一批',exact=True)
                    for count in ('0','101'):
                        page.locator('#reserve-count').fill(count);expect(button).to_be_disabled()
                    page.locator('#reserve-count').fill('21');expect(button).to_be_enabled()
                    page.screenshot(path=str(output/'02-import.png'),full_page=True)
                    button.click();page.wait_for_url('**/admin/jobs?*')
                    job_id=int(parse_qs(urlparse(page.url).query)['job_id'][0])
                    expect(page.locator('.import-progress-card .progress-status.succeeded')).to_be_visible(timeout=30000)
                    expect(page.get_by_role('combobox',name='对比批次',exact=True)).to_have_value(str(job_id))
                    expect(page.locator('.batch-detail .paper-heading')).to_contain_text('21 篇')
                    page.locator('.batch-detail').get_by_role('button',name='下一页',exact=True).click();expect(page.locator('.batch-papers article')).to_have_count(1)
                    page.locator('.batch-detail').get_by_role('button',name='上一页',exact=True).click();expect(page.locator('.batch-papers article')).to_have_count(20)
                    search=page.get_by_role('textbox',name='搜索批次论文');search.fill('no-such-paper-acceptance')
                    page.locator('.batch-detail').get_by_role('button',name='搜索',exact=True).click();expect(page.locator('.batch-papers article')).to_have_count(0)
                    search.fill('');page.locator('.batch-detail').get_by_role('button',name='搜索',exact=True).click();expect(page.locator('.batch-papers article')).to_have_count(20)
                    record_panel=page.get_by_role('region',name='逐条处理记录')
                    expect(record_panel).to_be_visible()
                    page.get_by_role('combobox',name='处理记录状态',exact=True).select_option('')
                    expect(record_panel.locator('article')).to_have_count(10)
                    record_panel.get_by_role('button',name='下一页记录',exact=True).click();expect(record_panel).to_contain_text('第 2 /')
                    record_panel.get_by_role('button',name='上一页记录',exact=True).click();expect(record_panel).to_contain_text('第 1 /')
                    record_panel.get_by_role('button',name='刷新记录',exact=True).click()
                    page.get_by_role('combobox',name='处理记录状态',exact=True).select_option('failed');expect(record_panel).to_contain_text('该状态下没有处理记录。')
                    with page.expect_download() as download:page.get_by_role('button',name='导出论文',exact=True).click()
                    data=json.loads(Path(download.value.path()).read_text());assert data['batch_id']==job_id and data['exported_papers']==21
                    page.locator('.batch-detail').get_by_role('link',name='在论文页面查看 →',exact=True).click()
                    page.wait_for_url('**/research/raw-papers?batch_id=*');expect(page.locator('.paper-row').first).to_be_visible()
                    page.go_back();expect(page.locator('.batch-detail')).to_be_visible()
                    page.screenshot(path=str(output/'03-imported-batch.png'),full_page=True)
                    checks.append('real 21-paper import, 100% progress, newest batch comparison, pages/search/export')
                    page.get_by_role('link',name='← 返回论文导入',exact=True).click();expect(page.locator('#reserve-count')).to_be_visible()
                    page.get_by_role('link',name='← 返回数据概览',exact=True).click();expect(page.locator('.metric-card').first).to_contain_text(f'{before+21:,}')
                    expect(page.locator('.latest-table tbody tr')).to_have_count(20,timeout=30000)
                    checks.append('return to import and overview; database count +21 and newest papers refreshed')
                    page.get_by_role('link',name='批次对比',exact=True).click();expect(page.locator('.comparison-table')).to_be_visible()
                    expect(page.get_by_role('link',name='← 返回数据概览',exact=True)).to_be_visible()
                    compare_button=page.get_by_role('button',name='开始对比',exact=True)
                    expect(compare_button).to_be_enabled();compare_button.click();expect(page.locator('.comparison-table')).to_be_visible()
                    page.locator('.page-actions').get_by_role('button',name='刷新',exact=True).click();expect(page.locator('.comparison-table')).to_be_visible()
                    page.locator('.record-table tbody tr').first.get_by_role('button',name='查看详情',exact=True).click();expect(page.locator('.batch-detail')).to_be_visible()
                    records_table=page.locator('.record-table')
                    for label in ('采集来源','会议'):
                        control=page.get_by_label(label,exact=True);expect(control.locator('option').nth(1)).to_be_attached();values=control.locator('option').evaluate_all('(els)=>els.map(e=>e.value).filter(Boolean)')
                        control.select_option(values[0]);expect(records_table.locator('tbody tr').first).to_be_visible();control.select_option('')
                    checks.append('comparison return target and source/conference filters')
                    # Create another batch, then choose which one to withdraw.
                    page.goto(base+'/admin/imports')
                    page.locator('#reserve-count').fill('5')
                    page.get_by_role('button',name='导入下一批',exact=True).click()
                    page.wait_for_url('**/admin/jobs?*')
                    second_manual=int(parse_qs(urlparse(page.url).query)['job_id'][0])
                    expect(page.locator('.import-progress-card .progress-status.succeeded')).to_be_visible(timeout=30000)
                    selector=page.get_by_role('combobox',name='选择撤回批次',exact=True)
                    expect(selector).to_have_value(str(second_manual))
                    expect(page.locator('.withdrawal-summary')).to_contain_text('本批论文 5 篇')
                    selector.select_option(str(job_id))
                    expect(page.locator('.withdrawal-summary')).to_contain_text('本批论文 21 篇')
                    page.get_by_role('button',name='撤回此批次',exact=True).click()
                    expect(page.locator('.confirm-target')).to_contain_text(api(f'/api/admin/jobs/{job_id}')['display_code'])
                    selector.select_option(str(second_manual))
                    expect(page.locator('.withdrawal-summary')).to_contain_text('本批论文 5 篇')
                    expect(page.get_by_label('撤回原因',exact=True)).to_have_count(0)
                    expect(page.get_by_role('button',name='确认撤回',exact=True)).to_have_count(0)
                    checks.append('withdrawal selector switches 21/5-paper batches and clears previous confirmation')
                    # Roll back the actual manual import on the isolated DB copy.
                    page.goto(base+f'/admin/jobs?job_id={job_id}&from=imports')
                    withdraw=page.get_by_role('button',name='撤回此批次',exact=True)
                    expect(withdraw).to_be_enabled()
                    withdraw.click();page.get_by_role('button',name='取消',exact=True).click()
                    expect(withdraw).to_be_visible()
                    remaining=api('/api/admin/reserve')['available']
                    withdraw.click()
                    expect(page.get_by_role('button',name='确认撤回',exact=True)).to_be_disabled()
                    page.get_by_label('撤回原因',exact=True).fill('浏览器验收：撤回手动导入批次')
                    page.get_by_role('button',name='确认撤回',exact=True).click()
                    expect(page.locator('.withdrawn-state')).to_be_visible(timeout=15000)
                    activity=api('/api/admin/data-overview?days=14')
                    today=activity['trend'][-1]['date']
                    today_activity=api('/api/admin/new-papers?view=additions&day='+today)
                    event=next(v for v in today_activity['withdrawals'] if v['batch_id']==job_id)
                    assert event['removed_papers']==21
                    expect(page.locator('.batch-detail .paper-heading')).to_contain_text('21 篇')
                    expect(withdraw).to_have_count(0)
                    assert api('/api/admin/data-overview?days=14')['total_papers']==before+5
                    assert api(f'/api/admin/jobs/{second_manual}')['batch_state']=='active'
                    assert api('/api/admin/reserve')['available']==remaining+21
                    assert api(f'/api/admin/jobs/{job_id}/papers')['total']==21
                    with page.expect_download() as withdrawn_download:
                        page.get_by_role('button',name='导出论文',exact=True).click()
                    historical=json.loads(Path(withdrawn_download.value.path()).read_text())
                    assert historical['exported_papers']==21 and historical['state']=='withdrawn'
                    page.screenshot(path=str(output/'04-manual-withdrawn.png'),full_page=True)
                    page.get_by_role('link',name='← 返回论文导入',exact=True).click()
                    expect(page.locator('#reserve-count')).to_be_visible()
                    page.get_by_role('link',name='← 返回数据概览',exact=True).click()
                    expect(page.locator('.metric-card').first).to_contain_text(f'{before+5:,}')
                    page.goto(base+'/admin/imports')
                    selector=page.get_by_role('combobox',name='选择撤回批次',exact=True)
                    expect(selector.locator(f'option[value="{job_id}"]')).to_be_disabled()
                    selector.select_option(str(second_manual))
                    expect(page.locator('.withdrawal-summary')).to_contain_text('本批论文 5 篇')
                    page.get_by_role('button',name='撤回此批次',exact=True).click()
                    page.get_by_label('撤回原因',exact=True).fill('浏览器验收：从导入页撤回第二批')
                    page.get_by_role('button',name='确认撤回',exact=True).click()
                    expect(page.locator('.inline-success')).to_contain_text(f'M-{second_manual:06d} 已撤回')
                    assert api('/api/admin/data-overview?days=14')['total_papers']==before
                    page.get_by_role('link',name='← 返回数据概览',exact=True).click()
                    expect(page.locator('.metric-card').first).to_contain_text(f'{before:,}')
                    point=next(v for v in api('/api/admin/data-overview?days=14')['trend'] if v['date']==today)
                    marker=page.locator(f'.bar-column[title^="{today}"]')
                    expect(marker.locator('.withdraw-stack')).to_be_visible()
                    expect(marker.locator('.withdraw-value')).to_contain_text(str(point['withdrawn_papers']))
                    marker.click()
                    expect(page.get_by_role('region',name='当日撤回记录',exact=True)).to_contain_text(f'M-{job_id:06d}')
                    expect(page.get_by_role('region',name='当日撤回记录',exact=True)).to_contain_text('退出论文库 21 篇')
                    page.get_by_role('button',name='收起',exact=True).click()
                    checks.append('manual withdrawal cancel/confirm, counts restored, pool +21, historical papers/export and returns; chart negative bar and daily withdrawal details')
                    if args.formal_input:
                        raw=json.loads(project_path(args.formal_input).read_text());records=[r for r in raw['records'] if r['source']=='openalex' and r['row'].get('abstract')][:40]
                        assert len(records)==40
                        upstream=requests.Session();upstream.trust_env=False;upstream.headers['Authorization']='Bearer '+settings.a_admin_token
                        def ingest(key,values):
                            response=upstream.post(f'http://127.0.0.1:{api_port}/api/admin/formal/batches',json={'batch_key':key,'venue':raw['venue'],'year':raw['year'],'records':values},timeout=15);response.raise_for_status();identifier=response.json()['batch_id']
                            for _ in range(150):
                                result=upstream.get(f'http://127.0.0.1:{api_port}/api/admin/formal/batches/{identifier}',timeout=10).json()
                                if result['status']=='succeeded':return identifier
                                if result['status'] not in ('queued','running'):raise AssertionError(result)
                                time.sleep(.2)
                            raise AssertionError('Formal import timed out')
                        first=ingest('browser-first',records[:30]);second=ingest('browser-second',records[20:])
                        page.goto(base+f'/admin/jobs?job_id={second}');expect(page.locator('.formal-controls')).to_contain_text(f'A-{second:06d}')
                        expect(page.locator('.comparison-table')).to_be_visible();expect(page.get_by_role('combobox',name='对比批次',exact=True)).to_have_value(str(second))
                        expect(page.locator('.batch-detail')).to_contain_text('更新')
                        expect(page.locator('.receipt-panel')).to_contain_text('当前版本尚无下游回执')
                        page.get_by_role('button',name='刷新交接状态',exact=True).click()
                        page.get_by_role('button',name='撤回此批次',exact=True).click();page.get_by_role('button',name='取消',exact=True).click();expect(page.get_by_role('button',name='撤回此批次',exact=True)).to_be_visible()
                        page.get_by_role('button',name='撤回此批次',exact=True).click();page.get_by_label('撤回原因',exact=True).fill('独立前端验收：验证撤回后保留历史批次')
                        page.get_by_role('button',name='确认撤回',exact=True).click()
                        expect(page.locator('.withdrawn-state')).to_be_visible(timeout=15000)
                        expect(page.locator('.batch-detail .paper-heading')).to_contain_text('20 篇')
                        expect(page.locator('.batch-papers article')).to_have_count(20)
                        compare=api(f'/api/admin/batch-comparison?first={first}&second={second}');assert (compare['shared_papers'],compare['only_first'],compare['only_second'])==(10,20,10)
                        assert api('/api/admin/data-overview?days=14')['total_papers']==before+21+len({r['row']['source_id'] for r in records[:30]}-initial_oa_ids)
                        page.screenshot(path=str(output/'04-withdrawn-batch.png'),full_page=True)
                        checks.append('two real formal batches -> withdrawal -> shared papers retained -> frozen history 20 papers and overlap 10/20/10')
                        # Seed an explicitly failed test task; retry must use the real worker.
                        from app.models import database,Job,BatchLedger,JobRecord
                        from app.formal_batches import canonical,digest
                        factory=database('sqlite:///'+str(target));row=records[0]
                        with factory() as db:
                            failed=Job(venue=raw['venue'],year=raw['year'],source='openalex',kind='formal',dataset_id='browser-retry',status='failed',stage='failed',failed=1,attempted=1,error='Injected test failure')
                            db.add(failed);db.flush();retry_id=failed.id
                            db.add(BatchLedger(job_id=retry_id,batch_key='browser-retry',input_sha256=digest({'venue':raw['venue'],'year':raw['year'],'records':[row]})))
                            db.add(JobRecord(job_id=retry_id,source=row['source'],source_id=row['row']['source_id'],payload_json=canonical(row['row']),status='failed',error='Injected test failure'));db.commit()
                        factory.kw['bind'].dispose()
                        page.goto(base+f'/admin/jobs?job_id={retry_id}&view=errors')
                        expect(page.get_by_role('button',name='重试失败任务',exact=True)).to_be_visible()
                        page.get_by_role('button',name='重试失败任务',exact=True).click()
                        expect(page.locator('.import-progress-card .progress-status.succeeded')).to_be_visible(timeout=30000)
                        checks.append('failed task filter and real worker retry complete; paper list link and browser return')

                    # A recoverable upstream failure must be visible, with a working retry.
                    page.route('**/api/admin/data-overview?*',lambda route:route.fulfill(status=503,json={'error':{'message':'验收：暂时不可用'}}))
                    page.goto(base+'/admin/overview');expect(page.get_by_text('数据读取失败',exact=True)).to_be_visible()
                    expected_errors.extend([r for r in bad if r['status']==503]);page.unroute('**/api/admin/data-overview?*')
                    page.get_by_role('button',name='重新加载',exact=True).click();expect(page.locator('.latest-table tbody tr')).to_have_count(20,timeout=30000)
                    checks.append('503 error is shown and retry restores overview')
                    for path in ('/admin/overview','/admin/imports','/admin/jobs'):
                        page.set_viewport_size({'width':390,'height':844});page.goto(base+path)
                        expect(page.locator('.standard-page h1')).to_be_visible()
                        page.wait_for_timeout(700)
                        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),path
                    page.screenshot(path=str(output/'05-mobile.png'),full_page=True);checks.append('390px mobile: three A pages have no document overflow')
                    unexpected=[r for r in bad if r not in expected_errors]
                    assert not errors,errors;assert not unexpected,unexpected
                    browser.close()
                report={'checks':checks,'javascript_errors':errors,'unexpected_failed_requests':unexpected,'expected_error_requests':expected_errors,'source_database_modified':False,'formal_input_tested':bool(args.formal_input)}
                (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps(report,ensure_ascii=False,indent=2))
            finally:
                import signal
                # Stop the complete test process group, including API and worker.
                try:
                    if os.name=='nt':server.send_signal(signal.CTRL_BREAK_EVENT)
                    else:os.killpg(server.pid,signal.SIGINT)
                except ProcessLookupError:pass
                try:server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name=='nt':subprocess.run(['taskkill','/PID',str(server.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        else:os.killpg(server.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    server.wait()

if __name__=='__main__':main()
