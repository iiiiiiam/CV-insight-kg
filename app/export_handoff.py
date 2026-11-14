"""Create a checked, immutable PaperInput export for downstream processing."""
import argparse
import hashlib
import json
from pathlib import Path
from .data_overview import handoff
from .models import Job
from src.knowledge_builder.models import PaperInput


def export_batch(db, job, path):
    path = Path(path)
    if path.exists() or path.with_suffix(path.suffix+'.sha256').exists():
        raise ValueError('Export destination exists; choose a new filename')
    result = handoff(db, job)
    for item in result['items']:
        PaperInput(**item)
    body = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(body)
    digest = hashlib.sha256(body).hexdigest()
    path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n', encoding='utf-8')
    return {'batch_id': job.id, 'exported': result['exported_papers'], 'excluded': result['excluded_papers'], 'sha256': digest}


def main():
    from .db import SessionLocal
    parser = argparse.ArgumentParser()
    parser.add_argument('batch_id', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    with SessionLocal() as db:
        job = db.get(Job, args.batch_id)
        if job is None:
            parser.error('Batch not found')
        print(json.dumps(export_batch(db, job, args.output), ensure_ascii=False))

if __name__ == '__main__': main()
