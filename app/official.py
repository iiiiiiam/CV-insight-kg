"""Shared identity checks and evidence-preserving writes for official conference pages."""
import copy
import json
from sqlalchemy import select
from .models import Paper, PaperSource
from .ingest import normalize_title, normalize_doi, openalex_work_row, upsert_paper


def save_official(db, row, work, job, source):
    row = copy.deepcopy(row)
    previous = db.scalar(select(PaperSource).where(PaperSource.source == source, PaperSource.source_id == row['source_id']))
    matched = db.scalar(select(Paper).where(Paper.openalex_id == work['id'])) if work else None
    if previous and matched and previous.paper_id != matched.id:
        raise ValueError('Official source and OpenAlex point to different papers')
    existing = db.get(Paper, previous.paper_id) if previous else None
    if work and existing and existing.openalex_id and existing.openalex_id != work['id']:
        raise ValueError('Existing official paper has a different OpenAlex ID')
    row.setdefault('raw', {}).pop('paper_input', None)
    if not row.get('abstract') and previous and existing:
        old = json.loads(previous.raw_json)
        item = old.get('paper_input') if isinstance(old, dict) else None
        if isinstance(item, dict) and item.get('abstract') and item.get('openalex_id') == existing.openalex_id and item.get('year') == row['year'] and item.get('source_url') == row.get('source_url') and normalize_title(item.get('title','')) == normalize_title(row['title']):
            row['raw']['paper_input'] = item
            row['raw']['detail_evidence_preserved_at'] = old.get('detail_evidence_preserved_at') or previous.retrieved_at.isoformat()
            row['raw']['previous_detail_evidence'] = old.get('previous_detail_evidence') or old.get('official_evidence') or old.get('detail_html')

    if work:
        if normalize_title(work.get('display_name', '')) != normalize_title(row['title']) or work.get('publication_year') != row['year']:
            raise ValueError('Matched OpenAlex title or year differs from official evidence')
        if row.get('doi') and normalize_doi(work.get('doi')) != normalize_doi(row['doi']):
            raise ValueError('Matched OpenAlex DOI differs from official evidence')
        row['raw']['paper_input'] = {'openalex_id': work['id'], 'title': row['title'], 'abstract': row.get('abstract'),
            'year': row['year'], 'venue': row['venue'], 'authorships': [{'author': {'display_name': a}, 'institutions': []} for a in row.get('authors', [])],
            'source_url': row['source_url'], 'dataset_id': job.dataset_id or f'batch-{job.id}'}
    paper = upsert_paper(db, row, source, paper=matched, job=job)
    if work:
        upsert_paper(db, openalex_work_row(work, job.venue, job.year), 'openalex', paper=paper)
    paper.abstract = row.get('abstract') or paper.abstract
    return paper
