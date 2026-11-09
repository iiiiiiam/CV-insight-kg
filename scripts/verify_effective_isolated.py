"""Run actual effective-file integration against a disposable Neo4j Harness only."""
import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--java',required=True)
    parser.add_argument('--file',required=True)
    parser.add_argument('--port',type=int,default=17691)
    parser.add_argument('--report',default='docs/graph/effective-results.json')
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
        env=dict(os.environ,GRAPH_TEST_URI=f'bolt://127.0.0.1:{args.port}',GRAPH_TEST_PASSWORD='test-password',EFFECTIVE_TEST_FILE=str(Path(args.file).resolve()),EFFECTIVE_REPORT=str((root/args.report).resolve()))
        # Harness has no authentication; password is only the driver's test placeholder.
        return subprocess.run([sys.executable,'-m','pytest','tests/graph','-q','-p','no:cacheprovider','--tb=short'],cwd=root,env=env).returncode
    finally:
        process.terminate()
        process.wait(timeout=20)


if __name__=='__main__':raise SystemExit(main())
