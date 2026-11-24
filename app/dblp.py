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


SPARQL_URL = 'https://sparql.dblp.org/sparql'


def fetch_sparql(venue,year,session=None,retries=3,page_size=500):
    """Read the official DBLP KG by exact proceedings page, retaining ordered signatures."""
    from .ingest import VENUES,normalize_doi
    if venue not in ('CVPR','ICCV') or type(year)is not int or not 1980<=year<=2100:raise ValueError('Invalid SPARQL conference/year')
    if not 1<=page_size<=1000 or retries<1:raise ValueError('Invalid SPARQL pagination configuration')
    session=session or requests.Session();slug=VENUES[venue]
    toc=f'https://dblp.org/db/conf/{slug}/{slug}{year}'
    prefix='PREFIX d: <https://dblp.org/rdf/schema#> '
    scope=f'?pub a d:Inproceedings; d:listedOnTocPage <{toc}>; d:title ?title.'
    def request(query):
        for attempt in range(retries):
            try:
                response=session.get(SPARQL_URL,params={'query':query,'format':'json'},timeout=90,headers={'Accept':'application/sparql-results+json'})
                response.raise_for_status();return response.json()['results']['bindings']
            except (requests.RequestException,ValueError,KeyError):
                if attempt+1==retries:raise
                time.sleep(min(2**attempt,8))
    count_query=prefix+f'SELECT (COUNT(DISTINCT ?pub) AS ?count) WHERE {{{scope}}}'
    expected=int(request(count_query)[0]['count']['value'])
    if expected<=0:raise ValueError('DBLP has no records for the exact proceedings page')
    results=[];seen=set()
    for offset in range(0,expected,page_size):
        query=prefix+f'''SELECT ?pub ?title ?doi ?author ?ordinal ?authorId WHERE {{
          {{ SELECT DISTINCT ?pub ?title ?doi WHERE {{ {scope} OPTIONAL {{?pub d:doi ?doi}} }} ORDER BY ?pub LIMIT {page_size} OFFSET {offset} }}
          OPTIONAL {{?pub d:hasSignature ?signature. ?signature d:signatureDblpName ?author; d:signatureOrdinal ?ordinal. OPTIONAL {{?signature d:signatureCreator ?authorId}}}}
        }} ORDER BY ?pub ?ordinal'''
        values=request(query);page={}
        for binding in values:
            publication=binding['pub']['value']
            if not publication.startswith(f'https://dblp.org/rec/conf/{slug}/'):raise ValueError('Unexpected publication in DBLP scope')
            title=binding['title']['value'];doi=binding.get('doi',{}).get('value')
            item=page.setdefault(publication,{'title':title,'doi':doi,'authors':{}})
            if (title,doi)!=(item['title'],item['doi']):raise ValueError('Ambiguous title/DOI in DBLP result')
            if 'author' in binding:
                ordinal=int(binding['ordinal']['value']);signature={'name':binding['author']['value'],'id':binding.get('authorId',{}).get('value'),'position':ordinal}
                if ordinal in item['authors'] and item['authors'][ordinal]!=signature:raise ValueError('Conflicting DBLP author signatures')
                item['authors'][ordinal]=signature
        if len(page)!=min(page_size,expected-offset):raise ValueError('DBLP SPARQL pagination count changed')
        for publication,item in page.items():
            if publication in seen:raise ValueError('Duplicate DBLP publication across pages')
            seen.add(publication);authors=[item['authors'][i] for i in sorted(item['authors'])]
            key=publication.removeprefix('https://dblp.org/rec/')
            results.append({'source_id':key,'dblp_key':key,'title':item['title'],'doi':normalize_doi(item['doi']),'venue':venue,'year':year,
                'authors':[a['name'] for a in authors],'source_url':publication,
                'raw':{'provider':'dblp_sparql','endpoint':SPARQL_URL,'toc':toc,'publication':publication,'title':item['title'],'doi':item['doi'],'authorships':authors}})
        print(f'DBLP {venue} {year}: fetched {len(results)}/{expected}',flush=True)
    if len(results)!=expected or int(request(count_query)[0]['count']['value'])!=expected:raise ValueError('DBLP changed during collection; retry in a new snapshot')
    return results
