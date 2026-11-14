"""Verify the actual handoff JSON files against an isolated B HTTP receiver."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--b-checkout',type=Path,required=True)
    parser.add_argument('--packet',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('reports/a-b-file-acceptance'))
    args=parser.parse_args();checkout=args.b_checkout.resolve();packet=args.packet.resolve()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    commit=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    refs=subprocess.check_output(['git','-C',str(checkout),'for-each-ref','--points-at','HEAD',
        '--format=%(refname:short)','refs/remotes/origin'],text=True).splitlines()
    branch=refs[0].removeprefix('origin/') if refs else 'detached checkout'
    documents=[];checksums={}
    for name in ('01-first-batch.json','02-second-batch.json'):
        body=(packet/name).read_bytes();digest=hashlib.sha256(body).hexdigest()
        assert digest==(packet/(name+'.sha256')).read_text().split()[0],name
        documents.append(json.loads(body));checksums[name]=digest
    first,second=documents
    ids=[{p['openalex_id'] for p in document['items']} for document in documents]
    assert (len(ids[0]),len(ids[1]),len(ids[0]&ids[1]),len(ids[1]-ids[0]))==(20,20,10,10)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    base=f'http://127.0.0.1:{port}';endpoint='/api/admin/knowledge/batches'
    with tempfile.TemporaryDirectory(prefix='a-b-files-') as temporary:
        root=Path(temporary);password=secrets.token_hex(16)
        env={**os.environ,'ADMIN_USERNAME':'file-acceptance','ADMIN_PASSWORD':password,
            'SESSION_SECRET':secrets.token_hex(40),'AUTO_GRAPH_SYNC':'false',
            'B_BATCH_REGISTRY':str(root/'b/ledger.json'),'B_REVIEWS_DIR':str(root/'b/reviews'),
            'B_SOURCE_CACHE':str(root/'b/cache'),'B_SOURCE_CORPUS':'','B_SOURCE_OFFLINE':'true'}
        with (output/'receiver.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','server.api.main:create_app','--factory',
                '--host','127.0.0.1','--port',str(port)],cwd=checkout,env=env,stdout=log,stderr=log)
            try:
                with requests.Session() as http:
                    http.trust_env=False
                    def request(method,path,**kwargs):
                        response=http.request(method,base+path,timeout=120,**kwargs);response.raise_for_status();return response.json()
                    for _ in range(200):
                        if process.poll() is not None:raise RuntimeError('B receiver exited; inspect receiver.log')
                        try:
                            if http.get(base+'/api/health',timeout=.5).ok:break
                        except requests.RequestException:pass
                        time.sleep(.1)
                    else:raise RuntimeError('B receiver startup timed out')
                    login=request('POST','/api/admin/sessions',json={'username':'file-acceptance','password':password})
                    http.headers['X-CSRF-Token']=login['csrf_token']
                    def status():return request('GET',endpoint)
                    def ingest(document):
                        value=request('POST',endpoint,json={'revision':status()['revision'],'document':document,'acknowledge_switch':True})
                        assert value['status'] in ('accepted','unchanged'),value
                        return value
                    def export():
                        for _ in range(200):
                            if not status()['source_enrichment']['running']:break
                            time.sleep(.1)
                        else:raise RuntimeError('B source processing did not finish')
                        return request('GET','/api/admin/knowledge/effective-export')
                    def inputs(document):return {p['input']['openalex_id']:p['input'] for p in document['papers']}
                    r1=ingest(first);one=status();assert one['paper_count']==20
                    e1=export();assert e1['counts']['papers']==20
                    replay=ingest(first);assert replay['status']=='unchanged'
                    assert status()['snapshot_revision']==one['snapshot_revision']
                    r2=ingest(second);two=status();assert two['paper_count']==30
                    e2=export();assert e2['counts']['papers']==30
                    union=inputs(e2);assert set(union)==ids[0]|ids[1]
                    path=endpoint+'/'+second['batch_code']+'/withdraw'
                    withdrawal=request('POST',path,json={'revision':status()['revision']})
                    assert (withdrawal['status'],withdrawal['removed'],withdrawal['retained'])==('withdrawn',10,10)
                    three=status();assert three['paper_count']==20
                    e3=export();assert e3['counts']['papers']==20 and inputs(e3)==inputs(e1)
                    assert e3['revision']!=e2['revision']
                    repeated=request('POST',path,json={'revision':three['revision']})
                    assert repeated['status']=='unchanged' and status()['snapshot_revision']==three['snapshot_revision']
                    for name,document in [('effective-before-withdrawal.json',e2),('effective-after-withdrawal.json',e3)]:
                        (output/name).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
                    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),
                        'b_branch':branch,'b_commit':commit,'actual_http_receiver':True,
                        'input_sha256':checksums,'counts':[20,30,20],'overlap':10,'second_only':10,
                        'first_receipt':r1,'second_receipt':r2,'withdrawal_receipt':withdrawal,
                        'same_batch_replay':'unchanged','repeated_withdrawal':'unchanged',
                        'stable_ids_and_first_input_restored':True,'effective_export_counts':[20,30,20],
                        'effective_revision_changed':True,'source_enrichment':'offline',
                        'c_d_publication':'not invoked','b_personal_environment_confirmation':'pending'}
                    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps(result,ensure_ascii=False,indent=2))
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
