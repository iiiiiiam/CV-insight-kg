"""Run actual effective-file integration against a disposable Neo4j Harness only."""
import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import secrets


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--java',required=True)
    parser.add_argument('--file',required=True)
    parser.add_argument('--port',type=int,default=17691)
    parser.add_argument('--tests',nargs='+',default=['tests/graph'])
    parser.add_argument('--report',default='docs/graph/effective-results.json')
    parser.add_argument('--exports',help='Existing A→B offline exports directory; never reads/writes the live B ledger')
    parser.add_argument('--junit',help='Small test-results XML, outside the reference directories')
    parser.add_argument('--a-reference',help='Read-only A reference for its pure report-section validation guard')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    harness=root/'tests/graph/harness'
    process=subprocess.Popen([args.java,f'-Dgraph.test.port={args.port}','-cp','target/classes;target/dependency/*','GraphHarness'],cwd=harness,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    lines=queue.Queue()
    def read():
        for line in process.stdout:lines.put(line)
        lines.put(None)
    threading.Thread(target=read,daemon=True).start()
    try:
        while True:
            line=lines.get(timeout=60)
            if line is None:raise RuntimeError('Isolated Neo4j failed to start')
            if 'READY' in line:print(line.strip(),flush=True);break
        env=dict(os.environ,GRAPH_TEST_URI=f'bolt://127.0.0.1:{args.port}',GRAPH_TEST_PASSWORD=secrets.token_urlsafe(32),EFFECTIVE_TEST_FILE=str(Path(args.file).resolve()),EFFECTIVE_REPORT=str((root/args.report).resolve()))
        if args.exports:
            exports=str(Path(args.exports).resolve())
            env.update(WEEK3_EXPORTS=exports,WEEK4_EXPORTS=exports,
                       WEEK3_REPORT=str(Path(exports)/'c-week3-regression.json'),
                       WEEK4_REPORT=str(Path(exports)/'c-week4-results.json'))
        if args.a_reference:env['WEEK4_A_REFERENCE']=str(Path(args.a_reference).resolve())
        # Harness has no authentication; password is only the driver's test placeholder.
        command=[sys.executable,'-m','pytest',*args.tests,'-q','-p','no:cacheprovider','--tb=short']
        if args.junit:command.append('--junitxml='+str(Path(args.junit).resolve()))
        return subprocess.run(command,cwd=root,env=env).returncode
    finally:
        process.terminate()
        process.wait(timeout=20)


if __name__=='__main__':raise SystemExit(main())
