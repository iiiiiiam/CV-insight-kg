"""Validate optional A-frozen OpenAlex annotations without changing PaperInput."""
from dataclasses import asdict
import json

from .enrichment_sources import normalized
from .extraction import fingerprint, load_vocabulary
from .models import PaperInput
from .source_enrichment import analyze_sources


def input_key(paper):
    value = asdict(paper)
    value.pop('dataset_id')
    return fingerprint(value)


def annotations(document, papers, vocabulary=None):
    rows = document.get('source_annotations', [])
    if not isinstance(rows, list):
        raise ValueError('source_annotations must be a list')
    by_id = {p.openalex_id: p for p in papers}
    result = {}
    for row in rows:
        identifier = row['paper_id']
        if identifier not in by_id or identifier in result:
            raise ValueError('Annotation paper is absent or repeated')
        paper, record = by_id[identifier], row['record']
        payload = record['payload']
        if (record['source'] != 'openalex' or payload.get('id') != identifier
            or payload.get('publication_year') != paper.year
            or normalized(payload.get('display_name') or '') != normalized(paper.title)
            or record['url'] != 'https://api.openalex.org/works/'+identifier.rsplit('/', 1)[-1]
            or 'topics' not in payload or 'keywords' not in payload
            or record['digest'] != fingerprint(payload)):
            raise ValueError('OpenAlex annotation identity or checksum differs from paper')
        analyze_sources(paper, vocabulary or load_vocabulary(), [record], fallback=True)
        result[identifier] = [record]
    return result


def registry_seeds(path, vocabulary):
    if not path.exists():
        return {}
    # Older batches have no annotations. Verify the wrapper without rebuilding
    # extraction results a second time on every ordinary knowledge-page read.
    wrapper=json.loads(path.read_text(encoding='utf-8'))
    payload=wrapper['payload']
    if wrapper['sha256']!=fingerprint(payload):
        raise ValueError('Upstream batch ledger checksum mismatch')
    if not any(b['document'].get('source_annotations') for b in payload['batches']):
        return {}
    from .batches import BatchRegistry, _snapshot
    state = BatchRegistry(path).read()
    batches = {b['batch_code']: b for b in state['batches'] if b['active']}
    records = {code: annotations(b['document'], [PaperInput(**p) for p in b['papers']], vocabulary)
               for code, b in batches.items() if b['document'].get('source_annotations')}
    seeds = {}
    for part in _snapshot(state)['papers']:
        paper = PaperInput(**part['input'])
        value = records.get(part['selected_batch'], {}).get(paper.openalex_id)
        if value:
            seeds[input_key(paper)] = value
    return seeds
