"""Load the supplemental pool as B's existing PaperInput objects."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def normalize_title(value):
    return re.sub(r'[^\w]+', ' ', value.casefold()).strip()


def load_papers(directory=None):
    from src.knowledge_builder.models import PaperInput

    root = Path(directory) if directory else Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Sample path is outside the pool')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Sample checksum mismatch: {name}')
    values = json.loads((root / 'papers.json').read_text(encoding='utf-8'))
    if len(values) != manifest['expected_count'] or Counter(p['venue'] for p in values) != manifest['venue_counts']:
        raise ValueError('Sample count mismatch')
    origins = json.loads((root / 'sources.json').read_text(encoding='utf-8'))
    if len(origins) != len(values):
        raise ValueError('Source count mismatch')
    source_map = {r['openalex_id']: r for r in origins}
    old = manifest['baseline_exclusion']
    ids, titles, dois = set(old['openalex_ids']), set(old['normalized_titles']), set(old['normalized_dois'])
    papers = []
    for value in values:
        if set(value) != set(manifest['b_input_schema']):
            raise ValueError('Unexpected B input fields')
        identifier, title = value['openalex_id'], normalize_title(value['title'])
        origin = source_map[identifier]
        doi = (origin.get('doi') or '').lower().removeprefix('https://doi.org/').removeprefix('http://doi.org/')
        if identifier in ids or title in titles or (doi and doi in dois):
            raise ValueError('Duplicate or original-development paper in pool')
        if (not identifier.startswith('https://openalex.org/W') or type(value['year']) is not int
                or not value['abstract'].strip() or not value['authorships'] or not value['source_url'].startswith('https://')):
            raise ValueError('Missing or invalid paper metadata')
        ids.add(identifier); titles.add(title)
        if doi:
            dois.add(doi)
        papers.append(PaperInput(**value))
    return papers


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    papers = load_papers()
    print(json.dumps({'papers': len(papers), 'venues': dict(Counter(p.venue for p in papers)),
                      'with_abstract': sum(bool(p.abstract) for p in papers)}, ensure_ascii=False))
