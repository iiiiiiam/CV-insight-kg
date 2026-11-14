"""Start A, its worker and the shared frontend locally; never invokes Docker."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='Use an isolated persistent demo DB and local preview login')
    parser.add_argument('--port',type=int,default=8001)
    parser.add_argument('--api-port',type=int,default=8000)
    parser.add_argument('--demo-db',type=Path,help='Optional persistent demo database path')
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--cvpr-jsonl',type=Path,help='Optional full CVPR input when creating a new demo database')
    parser.add_argument('--preview-paper-limit',type=int,default=420,help='Maximum initial preview papers; remaining records stay in the supplementary library')
    parser.add_argument('--reserve-db',type=Path,help='Restore all supplementary candidates when creating a new preview')
    args=parser.parse_args()
    for port in (args.port,args.api_port):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:listener.bind(('127.0.0.1',port))
            except OSError:parser.error(f'Port {port} is already in use; choose another port')
    if not args.skip_build:
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if not npm:parser.error('Node.js/npm is required to build the frontend')
        if not (ROOT/'frontend/node_modules').exists():
            subprocess.run([npm,'ci'],cwd=ROOT/'frontend',check=True,shell=os.name=='nt')
        subprocess.run([npm,'run','build'],cwd=ROOT/'frontend',check=True,shell=os.name=='nt')
    if not (ROOT/'frontend/dist/index.html').exists():parser.error('Frontend build is missing')
    from server.init_local import initialize
    from server.configuration.settings import Settings
    from server.api.main import create_app
    from fastapi import Request,HTTPException
    from fastapi.responses import RedirectResponse
    from dataclasses import replace
    import requests
    import uvicorn
    initialize()
    settings=Settings.from_env()
    if not settings.a_admin_token:parser.error('A_ADMIN_TOKEN is missing from server/.env')
    local=ROOT/'server/.local';local.mkdir(exist_ok=True)
    if args.demo:
        target=args.demo_db.resolve() if args.demo_db else local/'a-demo.db'
        if not target.exists():
            from app.demo import create_demo
            create_demo(target,args.cvpr_jsonl,paper_limit=args.preview_paper_limit,reserve_db=args.reserve_db)
        database_url='sqlite:///'+str(target)
    else:
        database_url=os.getenv('D_A_DATABASE_URL') or os.getenv('DATABASE_URL') or 'sqlite:///'+str(local/'a.db')
    settings=replace(settings,a_base_url=f'http://127.0.0.1:{args.api_port}',origins=(f'http://localhost:{args.port}',f'http://127.0.0.1:{args.port}'))
    env={**os.environ,'DATABASE_URL':database_url,'LOCAL_DEMO':'0','ADMIN_TOKEN':settings.a_admin_token}
    children=[]
    try:
        api=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(args.api_port)],cwd=ROOT,env=env)
        children.append(api)
        with requests.Session() as http:
            http.trust_env=False
            for _ in range(100):
                if api.poll() is not None:raise RuntimeError('A API exited during startup')
                try:
                    response=http.get(settings.a_base_url+'/health',timeout=.3)
                    if response.status_code==200:break
                except requests.RequestException:pass
                time.sleep(.1)
            else:raise RuntimeError('A API did not become ready')
        children.append(subprocess.Popen([sys.executable,'-m','app.worker'],cwd=ROOT,env=env))
        app=create_app(settings)
        @app.middleware('http')
        async def latest_frontend(request,call_next):
            response=await call_next(request)
            if response.headers.get('content-type','').startswith('text/html'):
                response.headers['Cache-Control']='no-store'
            return response
        if args.demo:
            @app.get('/preview',include_in_schema=False)
            @app.get('/__round2_preview',include_in_schema=False)
            async def preview(request:Request):
                if not request.client or request.client.host not in ('127.0.0.1','::1'):raise HTTPException(404)
                request.app.state.auth.login(request,settings.username,settings.password)
                target=request.query_params.get('next','/admin/overview?preview=clean-v2')
                parsed=urlsplit(target)
                if parsed.scheme or parsed.netloc or parsed.path not in ('/admin/overview','/admin/jobs','/admin/imports') or any(ord(c)<32 for c in target):
                    target='/admin/overview?preview=clean-v2'
                return RedirectResponse(target,status_code=303)
            app.router.routes.insert(0,app.router.routes.pop())
            app.router.routes.insert(0,app.router.routes.pop())
        suffix='/preview' if args.demo else '/admin/login'
        print(f'Local interface: http://localhost:{args.port}{suffix}',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=args.port)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()

if __name__=='__main__':main()
