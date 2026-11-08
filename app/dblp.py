"""DBLP official search API client and explicit upstream access diagnostics."""
from __future__ import annotations
import time
import requests

SEARCH_URL = 'https://dblp.org/search/publ/api'


class DblpAccessError(ValueError):
    pass


def check_access(response):
    if response.status_code == 202 or ('text/html' in response.headers.get('Content-Type','') and
            any(s in response.text[:5000].lower() for s in ('not a bot', 'anubis', 'captcha', 'challenge'))):
        raise DblpAccessError('DBLP_ACCESS_CHALLENGE: upstream requires browser verification; no bibliographic data received')
    response.raise_for_status()


def search_row(info, venue, year):
    from .ingest import VENUES, clean_title, normalize_doi
    key = info.get('key','')
    if not key.startswith('conf/'+VENUES[venue]+'/') or str(info.get('year')) != str(year):
        raise ValueError('DBLP search returned a record outside the requested scope')
    if info.get('type') != 'Conference and Workshop Papers':
        return None
    title = clean_title(info.get('title',''))
    if not title:
        raise ValueError('DBLP search record has no title')
    authors = (info.get('authors') or {}).get('author',[])
    if isinstance(authors,(dict,str)):
        authors = [authors]
    authors = [a.get('text','') if isinstance(a,dict) else a for a in authors]
    ee = info.get('ee',[])
    if isinstance(ee,str): ee=[ee]
    doi = info.get('doi') or next((e for e in ee if isinstance(e,str) and 'doi.org/' in e),None)
    return {'source_id':key,'dblp_key':key,'title':title,'year':year,'venue':venue,
            'authors':[a for a in authors if a], 'doi':normalize_doi(doi),
            'source_url':'https://dblp.org/rec/'+key,
            'raw':{'dblp_search_info':info,'query_scope':{'venue':venue,'year':year}}}


def fetch_search(venue, year, session, retries=3, page_size=1000):
    """Use the exact table-of-contents query, validating every pagination boundary."""
    from .ingest import VENUES, TIMEOUT
    if retries < 1 or not 1 <= page_size <= 1000:
        raise ValueError('Invalid DBLP pagination configuration')
    slug=VENUES[venue]
    query=f'toc:db/conf/{slug}/{slug}{year}.bht:'
    offset=0; total=None; seen=set(); rows=[]
    while total is None or offset < total:
        for attempt in range(retries):
            try:
                response=session.get(SEARCH_URL,params={'q':query,'format':'json','h':page_size,'f':offset},
                                     timeout=TIMEOUT,headers={'User-Agent':'tupu-research-ingest/0.4 (metadata only)'})
                check_access(response)
                payload=response.json()
                break
            except DblpAccessError:
                raise
            except (requests.RequestException,ValueError):
                if attempt+1==retries: raise
                time.sleep(min(2**attempt,8))
        hits=payload['result']['hits']
        actual_total=int(hits['@total'])
        if actual_total < 0: raise ValueError('Negative DBLP result count')
        if total is None: total=actual_total
        if actual_total != total or int(hits.get('@first',offset)) != offset:
            raise ValueError('DBLP pagination changed during download')
        page=hits.get('hit',[])
        if isinstance(page,dict): page=[page]
        if len(page)>page_size or int(hits.get('@sent',len(page)))!=len(page):
            raise ValueError('DBLP page length mismatch')
        if not page and offset<total: raise ValueError('DBLP returned an incomplete batch')
        for hit in page:
            key=hit['info']['key']
            if key in seen: raise ValueError('Duplicate DBLP key during pagination')
            seen.add(key)
            row=search_row(hit['info'],venue,year)
            if row is not None: rows.append(row)
        offset+=len(page)
        if offset>total: raise ValueError('DBLP returned more records than announced')
        if offset<total: time.sleep(1)
    if not rows: raise ValueError('No DBLP conference papers for the requested table of contents')
    return rows
