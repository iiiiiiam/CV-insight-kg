"""ECCV 2024 official index, verified detail evidence and resumable refresh."""
import re
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from .models import Source
from .ingest import normalize_title
from .pipeline import save_snapshot, process_snapshot
from scripts.parse_ecva_batch import BASE, parse_index


def fetch_detail(row, http):
    url = row['source_url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.ecva.net' or not re.fullmatch(r'/papers/eccv_2024/papers_ECCV/html/\d+_ECCV_2024_paper.php', parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('ECVA paper URL is outside the requested conference')
    response = http.get(url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    title, abstract = soup.select_one('#papertitle'), soup.select_one('#abstract')
    if not title or normalize_title(title.get_text(' ', strip=True)) != normalize_title(row['title']):
        raise ValueError('ECVA detail title differs from directory')
    if not abstract or not abstract.get_text(' ', strip=True):
        raise ValueError('ECVA detail has no abstract')
    return {**row, 'abstract': abstract.get_text(' ', strip=True),
            'raw': {**row.get('raw', {}), 'detail_html': response.text}, '_detail_complete': True}


def match_openalex(row, http, retries=3):
    if not row.get('doi'):
        return None
    from .ingest import fetch_openalex
    result = fetch_openalex(row['doi'], http, retries=retries)
    return result['raw'] if result else None


def run_ecva_job(db, job, http=None):
    source = db.scalar(select(Source).where(Source.name == 'ecva'))
    if job.venue != 'ECCV' or job.year != 2024 or not source or not source.enabled:
        raise ValueError('ECVA is available for enabled ECCV 2024 refreshes')
    http = http or requests.Session()
    for attempt in range(source.max_retries):
        try:
            response = http.get(BASE+'papers.php', timeout=30)
            response.raise_for_status()
            rows = parse_index(response.text)
            break
        except (requests.RequestException, ValueError):
            if attempt + 1 == source.max_retries:
                raise
    if job.dataset_id and job.dataset_id.startswith('ecva:'):
        _, start, count = job.dataset_id.split(':')
        rows = rows[int(start)-1:] if count == 'all' else rows[int(start)-1:int(start)-1+int(count)]
    if not rows:
        raise ValueError('Requested ECVA range has no papers')
    save_snapshot(db, job, rows, 'ecva')
    process_snapshot(db, job, http)
