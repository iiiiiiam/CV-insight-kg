"""Disposable preview and regression against the provided effective file, no Docker access."""
import subprocess,os,sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from src.graph_query.repository import GraphRepository
from src.graph_query.effective_source import FileEffectiveSource
java=sys.argv[1];source=sys.argv[2]
harness=subprocess.Popen([java,'-Dgraph.test.port=17693','-cp','target/classes;target/dependency/*','GraphHarness'],cwd=root/'tests/graph/harness',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
 for line in harness.stdout:
  print(line.strip(),flush=True)
  if 'READY' in line:break
 else:raise RuntimeError('Isolated engine did not start')
 env=dict(os.environ,GRAPH_TEST_URI='bolt://127.0.0.1:17693',GRAPH_TEST_PASSWORD='unused',EFFECTIVE_TEST_FILE=str(Path(source).resolve()),EFFECTIVE_REPORT=str(root/'docs/graph/visualization-regression.json'))
 status=subprocess.run([sys.executable,'-m','pytest','tests/graph','-q','-p','no:cacheprovider','--tb=short'],cwd=root,env=env).returncode
 if status:raise RuntimeError('Regression failed')
 repo=GraphRepository(env['GRAPH_TEST_URI'],'neo4j','unused');repo.initialize();doc=FileEffectiveSource(source).load();b=repo.ingest_effective(doc)['id'];repo.publish(b,repo.batch(b)['active_batch_id']);repo.close()
 env.update(NEO4J_URI=env['GRAPH_TEST_URI'],NEO4J_USER='neo4j',NEO4J_PASSWORD='unused')
 print('Isolated preview http://127.0.0.1:18002/research/analytics',flush=True)
 subprocess.run([sys.executable,'-m','uvicorn','src.graph_query.api:app','--host','127.0.0.1','--port','18002'],cwd=root,env=env)
finally:harness.terminate();harness.wait(timeout=20)
