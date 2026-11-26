"""Exercise the small live online-import UI using an isolated copy of A's database."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import requests
from app.paths import PROJECT_ROOT,project_path


def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--database',type=Path,required=True)
 parser.add_argument('--browser-executable',type=Path,required=True)
 parser.add_argument('--output',type=Path,default=Path('reports/manual-online-browser'))
 args=parser.parse_args();output=project_path(args.output);output.mkdir(parents=True,exist_ok=True)
 from playwright.sync_api import sync_playwright,expect
 a_url,web=f'http://127.0.0.1:{port()}',f'http://127.0.0.1:{port()}'
 with tempfile.TemporaryDirectory(prefix='online-browser-') as directory:
  root=Path(directory);password,token=secrets.token_hex(18),secrets.token_hex(24)
  with sqlite3.connect(project_path(args.database).resolve().as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(root/'a.db') as copied:old.backup(copied)
  env={**os.environ,'DATABASE_URL':'sqlite:///'+str(root/'a.db'),'ADMIN_TOKEN':token,'A_ADMIN_TOKEN':token,
   'A_API_BASE_URL':a_url,'LOCAL_DEMO':'0','ADMIN_USERNAME':'acceptance','ADMIN_PASSWORD':password,
   'SESSION_SECRET':secrets.token_hex(40),'D_USER_STORE':str(root/'users.json'),'AUTO_GRAPH_SYNC':'false',
   'B_BATCH_REGISTRY':str(root/'b/ledger.json'),'B_SOURCE_CACHE':str(root/'cache'),'B_SOURCE_CORPUS':'',
   'B_SOURCE_OFFLINE':'true','A_B_TRANSPORT':'local','ALLOWED_ORIGINS':web,'A_AUTO_HANDOFF':'true'}
  children=[]
  with (output/'services.log').open('w') as log:
   try:
    for command in ([sys.executable,'-m','uvicorn','app.api:app','--port',a_url.rsplit(':',1)[1]],
       [sys.executable,'-m','uvicorn','server.api.main:create_app','--factory','--port',web.rsplit(':',1)[1]],
       [sys.executable,'-m','app.worker']):
     children.append(subprocess.Popen(command,cwd=PROJECT_ROOT,env=env,stdout=log,stderr=log))
    http=requests.Session();http.trust_env=False
    for base,path in ((a_url,'/health'),(web,'/api/health')):
     for _ in range(200):
      if any(c.poll() is not None for c in children):raise RuntimeError('Service exited; see services.log')
      try:
       if http.get(base+path,timeout=1).ok:break
      except requests.RequestException:pass
      time.sleep(.1)
     else:raise RuntimeError('Startup timed out')
    with sync_playwright() as p:
     browser=p.chromium.launch(headless=True,executable_path=str(args.browser_executable))
     page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];bad=[]
     page.on('pageerror',lambda e:errors.append(str(e)))
     page.on('response',lambda r:bad.append({'status':r.status,'url':r.url}) if '/api/' in r.url and r.status>=400 else None)
     login=page.request.post(web+'/api/admin/sessions',data={'username':'acceptance','password':password});assert login.ok
     def api(path):
      r=page.request.get(web+path);assert r.ok,r.text();return r.json()
     before=api('/api/admin/data-overview?days=14')['total_papers'];pool=api('/api/admin/reserve')['available']
     page.goto(web+'/admin/imports')
     expect(page.get_by_role('combobox',name='在线采集会议年份')).to_have_value('CVPR:2025',timeout=15000)
     page.get_by_role('button',name='采集并入库',exact=True).click()
     expect(page.locator('.online-state')).to_contain_text('已入库，后台已接收',timeout=120000)
     identifier=int(page.evaluate("localStorage.getItem('a-last-online-collection')"))
     value=api('/api/admin/online-collections/'+str(identifier))
     assert value['imported_count']==20 and value['background_task']['status']=='succeeded',value
     assert api('/api/admin/data-overview?days=14')['total_papers']==before+20
     assert api('/api/admin/reserve')['available']==pool
     papers=api(f'/api/admin/jobs/{identifier}/papers')['items'];assert len(papers)==20 and all(p['year']==2025 for p in papers)
     page.get_by_role('link',name='查看本批论文 →',exact=True).click()
     expect(page.locator('.batch-detail .paper-heading')).to_contain_text('20 篇',timeout=15000)
     page.get_by_role('link',name='← 返回论文导入',exact=True).click()
     expect(page.get_by_role('button',name='采集并入库',exact=True)).to_be_enabled(timeout=15000)
     page.reload();expect(page.locator('.online-state')).to_contain_text('后台已接收',timeout=15000)
     page.set_viewport_size({'width':390,'height':844})
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
     assert not errors,errors
     assert not bad,bad
     result={'actual_online_source':True,'conference':'CVPR','year':2025,'new_papers':20,
      'before':before,'after':before+20,'background_transport':'integrated_local','background_received':True,
      'pool_unchanged':True,'button_progress_return_reload_mobile':'passed','javascript_errors':errors,
      'unexpected_failed_requests':bad,'source_database_modified':False}
     (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False));browser.close()
   finally:
    for child in children:child.terminate()
    for child in children:
     try:child.wait(timeout=10)
     except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':main()
