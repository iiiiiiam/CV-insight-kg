"""Resolve saved publisher/official landing pages without inventing paper URLs."""
import json
from urllib.parse import urlsplit, urlunsplit, quote


def safe_web_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value.strip())
        if url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password:
            if url.hostname in ('doi.org', 'dx.doi.org'):
                return urlunsplit(('https', 'doi.org', url.path, url.query, url.fragment))
            return value.strip()
    except ValueError:
        pass
    return None


def paper_homepage(paper, sources):
    for source in sources:
        if source.source in ('cvf', 'ecva'):
            value = safe_web_url(source.source_url)
            if value:
                return value
    for source in sources:
        if source.source != 'openalex':
            continue
        try:
            work = json.loads(source.raw_json)
            for location in ('primary_location', 'best_oa_location'):
                value = safe_web_url((work.get(location) or {}).get('landing_page_url'))
                if value:
                    return value
        except (ValueError, AttributeError, TypeError):
            continue
    if paper.doi:
        return 'https://doi.org/' + quote(paper.doi, safe='/():;._-')
    value = safe_web_url(paper.source_url)
    if value and urlsplit(value).hostname not in ('openalex.org', 'api.openalex.org', 'dblp.org'):
        return value
    return None
