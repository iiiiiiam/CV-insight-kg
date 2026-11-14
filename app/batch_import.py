"""Checked file ingestion shared by the CLI and scheduled ECVA refresh."""
import hashlib
import json
from pathlib import Path
from sqlalchemy import select
from .models import Job, Source, now
from .pipeline import process_snapshot, save_snapshot


def checked_rows(path: Path, venue: str, year: int, source: str):
    manifest = json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    body = path.read_bytes()
    if (manifest.get('venue'), manifest.get('year'), manifest.get('source')) != (venue, year, source):
        raise ValueError('Batch scope mismatch')
    if hashlib.sha256(body).hexdigest() != manifest.get('sha256'):
        raise ValueError('Batch checksum mismatch; regenerate the batch manifest')
    values = [json.loads(line) for line in body.decode('utf-8').splitlines() if line.strip()]
    if not values or len(values) != manifest.get('count',manifest.get('expected_count')) or len(values) > 10000:
        raise ValueError('Batch count mismatch')
    rows = []
    for value in values:
        if source == 'openalex':
            from scripts.fetch_openalex_batch import SOURCES
            location = ((value.get('primary_location') or {}).get('source') or {}).get('id')
            if manifest.get('source_id') != SOURCES.get(venue) or location != 'https://openalex.org/' + SOURCES[venue] or value.get('publication_year') != year:
                raise ValueError('OpenAlex record scope mismatch')
            rows.append({'source_id': value['id'], 'raw': value, 'openalex_work': True})
        else:
            if (value.get('venue'), value.get('year')) != (venue, year):
                raise ValueError('ECVA record scope mismatch')
            rows.append(dict(value, skip_network=True))
    return rows


def import_file(db, path, venue, year, source):
    rows = checked_rows(path, venue, year, source)
    configured = db.scalar(select(Source).where(Source.name == source))
    if not configured or not configured.enabled:
        raise ValueError(f'{source} source is disabled')
    job = Job(venue=venue, year=year, source=source, kind='file', status='running',
              active_key=f'{venue}:{year}', started_at=now())
    db.add(job)
    try:
        db.flush()
        save_snapshot(db, job, rows, source)
        process_snapshot(db, job)
    except Exception:
        db.rollback()
        if job.id and db.get(Job,job.id) is not None:
            job.status='failed'; job.active_key=None; job.finished_at=now(); db.commit()
        raise
    return {'id':job.id,'venue':venue,'year':year,'status':job.status,
            'attempted':job.attempted,'succeeded':job.succeeded,'failed':job.failed,'skipped':job.skipped}


def queue_upload(db, content, manifest):
    """Validate a caller-supplied batch and queue only a content-addressed local file."""
    from .paths import configured_path
    if manifest.get('source') not in ('openalex', 'ecva') or manifest.get('venue') not in ('CVPR', 'ICCV', 'ECCV'):
        raise ValueError('Unsupported file source or conference')
    source, venue, year = manifest['source'], manifest['venue'], manifest.get('year')
    if not isinstance(year, int) or not 1980 <= year <= now().year:
        raise ValueError('Invalid conference year')
    if source == 'ecva' and (venue, year) != ('ECCV', 2024):
        raise ValueError('ECVA input must be ECCV 2024')
    if len(content.encode('utf-8')) > 30_000_000:
        raise ValueError('Data file exceeds the 30MB import limit')
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    if digest != manifest.get('sha256'):
        raise ValueError('File checksum differs from manifest')
    directory = configured_path('BATCH_DIR', 'data/raw') / 'uploads'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest + '.jsonl')
    if not path.exists():
        path.write_text(content, encoding='utf-8', newline='')
    manifest_path = path.with_suffix('.manifest.json')
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
        keys = ('source','venue','year','source_id','sha256')
        if any(previous.get(key) != manifest.get(key) for key in keys) or previous.get('count',previous.get('expected_count')) != manifest.get('count',manifest.get('expected_count')):
            raise ValueError('Same file already registered with a conflicting manifest scope')
    if not manifest_path.exists():
        manifest_path.write_text(canonical, encoding='utf-8')
    rows = checked_rows(path, venue, year, source)
    ids = [row['source_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source identifiers in uploaded batch')
    configured = db.scalar(select(Source).where(Source.name == source))
    if not configured or not configured.enabled:
        raise ValueError('Source is disabled')
    job = Job(venue=venue, year=year, source=source, kind='file', dataset_id='upload:'+digest,
              status='queued', active_key=f'{venue}:{year}')
    db.add(job)
    db.flush()
    save_snapshot(db, job, rows, source)
    return job


def process_upload(db, job):
    from .paths import configured_path
    digest = (job.dataset_id or '').removeprefix('upload:')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid uploaded batch identifier')
    path = configured_path('BATCH_DIR', 'data/raw') / 'uploads' / (digest+'.jsonl')
    rows = checked_rows(path, job.venue, job.year, job.source)
    save_snapshot(db, job, rows, job.source)
    process_snapshot(db, job)
