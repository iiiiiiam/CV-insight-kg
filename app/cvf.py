"""Official CVF metadata adapter; no PDF downloads or fuzzy venue searches."""
import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from .models import Source

BASE='https://openaccess.thecvf.com'


def paper_url(href,venue,year):
    url=urljoin(BASE,href);p=urlsplit(url)
    allowed=(f'/content/{venue}{year}/html/',f'/content_{venue}_{year}/html/')
    if p.scheme!='https' or p.netloc!='openaccess.thecvf.com' or not p.path.startswith(allowed) or not p.path.endswith(('_paper.html','_paperOriginal.html')) or p.query or p.fragment:
        raise ValueError('CVF paper URL is outside the requested conference/year')
    return url


class IndexParser(HTMLParser):
    def __init__(self,venue,year):
        super().__init__(convert_charrefs=True)
        self.venue=venue;self.year=year;self.rows=[];self.current=None;self.in_title=False;self.title=[];self.closed=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='dt':
            self.in_title='ptitle' in a.get('class','').split()
            if self.in_title:
                self.current=None;self.title=[]
        if self.in_title and tag=='a' and a.get('href'):
            url=paper_url(a['href'],self.venue,self.year)
            self.current={'source_id':f'cvf:{self.venue}:{self.year}:'+hashlib.sha256(url.encode()).hexdigest(),
                          'source_url':url,'venue':self.venue,'year':self.year,'authors':[]}
        if tag=='input' and a.get('name')=='query_author' and self.current and a.get('value'):
            self.current['authors'].append(a['value'])
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
    def handle_endtag(self,tag):
        if tag=='dt' and self.in_title:
            if not self.current:raise ValueError('CVF title has no paper link')
            self.current['title']=' '.join(''.join(self.title).split())
            if not self.current['title']:raise ValueError('CVF paper title is empty')
            self.rows.append(self.current);self.in_title=False
        if tag=='html':self.closed=True


def parse_index(html,venue,year):
    if venue not in ('CVPR','ICCV'):raise ValueError('CVF supports CVPR and ICCV')
    parser=IndexParser(venue,year);parser.feed(html);parser.close()
    rows=parser.rows
    if not parser.closed or not rows or len({r['source_id'] for r in rows})!=len(rows):
        raise ValueError('Incomplete, empty or duplicate CVF index')
    digest=hashlib.sha256(html.encode()).hexdigest()
    for row in rows:
        row['raw']={'index_url':f'{BASE}/{venue}{year}?day=all','index_sha256':digest,
                    'paper_url':row['source_url'],'title':row['title'],'authors':row['authors'].copy()}
    return rows


def fetch_index(venue,year,http,retries=3):
    for attempt in range(retries):
        try:
            response=http.get(f'{BASE}/{venue}{year}?day=all',timeout=60)
            response.raise_for_status()
            return parse_index(response.text,venue,year)
        except (requests.RequestException,ValueError):
            if attempt+1==retries:raise
    raise ValueError('CVF retries must be positive')


def fetch_detail(row,http):
    from .ingest import clean_title,normalize_title,normalize_doi
    url=paper_url(row['source_url'],row['venue'],row['year'])
    response=http.get(url,timeout=30);response.raise_for_status()
    soup=BeautifulSoup(response.text,'html.parser')
    def meta(name):
        return [m.get('content','').strip() for m in soup.select(f'meta[name="{name}"]')]
    titles=meta('citation_title');dates=meta('citation_publication_date')
    if not titles or normalize_title(titles[0])!=normalize_title(row['title']) or not dates or dates[0][:4]!=str(row['year']):
        raise ValueError('CVF detail metadata does not match index')
    abstract=soup.select_one('#abstract')
    if not abstract or not abstract.get_text(' ',strip=True):raise ValueError('CVF detail has no abstract')
    result=dict(row);result['title']=clean_title(titles[0]);result['abstract']=abstract.get_text(' ',strip=True)
    doi=meta('citation_doi')
    if doi: result['doi']=normalize_doi(doi[0])
    result['raw']={**row['raw'],'detail_html':response.text}
    return result
