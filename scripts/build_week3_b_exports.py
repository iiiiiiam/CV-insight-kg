"""Read-only B reference execution, isolated ledger and authentic effective exports."""
import sys
sys.dont_write_bytecode=True
import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--b-root',required=True);p.add_argument('--a-root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
b=Path(a.b_root).resolve();source=Path(a.a_root).resolve()/'examples/week3_handoff';out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(b))
from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.effective_export import build_effective_export,write_effective_export
for f in source.glob('*.json'):
 assert hashlib.sha256(f.read_bytes()).hexdigest()==f.with_suffix('.json.sha256').read_text().split()[0]
d1=json.loads((source/'01-first-batch.json').read_text(encoding='utf-8'));d2=json.loads((source/'02-second-batch.json').read_text(encoding='utf-8'))
r=BatchRegistry(out/'ledger.json');receipts=[]
def export(name):
 doc=build_effective_export(r.workspace(out/'feedback.json'));write_effective_export(doc,out/name);print(name,doc['counts']['papers'],flush=True)
receipts.append(r.ingest(d1));export('first-effective.json')
receipts.append(r.ingest(d2));export('merged-effective.json')
receipts.append(r.withdraw(d2['batch_code']));export('withdrawn-effective.json')
receipts.append(r.withdraw(d1['batch_code']));export('empty-effective.json')
(out/'receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
