"""Officially scoped DBLP/OpenAlex collection and immutable CVF coverage baselines."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
import requests
from .ingest import fetch_dblp,openalex_work_row,normalize_title
from .cvf import parse_index
from .paper_quality import is_front_matter
from .formal_batches import canonical,digest
from .pipeline import safe_error
from scripts.fetch_openalex_batch import fetch_batch


class CollectionIncomplete(ValueError):
    def __init__(self,failures):
        self.failures=failures
        super().__init__('Incomplete official source collection: '+canonical(failures))


def write_bytes(path,body):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',prefix='.freeze-',dir=path.parent,delete=False) as f:
            temporary=Path(f.name);f.write(body);f.flush();os.fsync(f.fileno())
        os.link(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return hashlib.sha256(body).hexdigest()


def write_json(path,value):
    return write_bytes(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())


def freeze_baseline(venue,year,directory,http=None):
    directory=Path(directory);path=directory/'baseline.json'
    if path.exists():return load_baseline(path,venue,year)
    html=directory/'baseline.html';url=f'https://openaccess.thecvf.com/{venue}{year}?day=all'
    raw=None
    if html.exists():
        try:
            raw=html.read_bytes();parse_index(raw.decode('utf-8'),venue,year)
        except (ValueError,UnicodeError):
            # Preserve an uncommitted partial HTML capture and obtain a clean one.
            html.rename(html.with_name('baseline.incomplete-'+uuid.uuid4().hex+'.html'));raw=None
    if raw is None:
        http=http or requests.Session();response=http.get(url,timeout=90);response.raise_for_status();raw=response.content
        parse_index(raw.decode('utf-8'),venue,year)
        try:write_bytes(html,raw)
        except FileExistsError:raw=html.read_bytes()
    rows=parse_index(raw.decode('utf-8'),venue,year)
    baseline={'format_version':'a-coverage-baseline/1','venue':venue,'year':year,'source_url':url,
        'retrieved_at':datetime.fromtimestamp(html.stat().st_mtime,timezone.utc).isoformat(),'html_sha256':hashlib.sha256(raw).hexdigest(),
        'expected_count':len(rows),'papers':[{'title':r['title'],'source_url':r['source_url']} for r in rows]}
    baseline['revision']=digest(baseline)
    try:write_json(path,baseline)
    except FileExistsError:return load_baseline(path,venue,year)
    return baseline


def load_baseline(path,venue=None,year=None):
    path=Path(path);value=json.loads(path.read_text(encoding='utf-8'));revision=value.pop('revision')
    if digest(value)!=revision or value.get('format_version')!='a-coverage-baseline/1':raise ValueError('Frozen baseline checksum/version mismatch')
    value['revision']=revision
    if venue is not None and (value['venue'],value['year'])!=(venue,year):raise ValueError('Frozen baseline scope mismatch')
    if len(value['papers'])!=value['expected_count'] or not value['papers']:raise ValueError('Frozen baseline count mismatch')
    if hashlib.sha256(path.with_name('baseline.html').read_bytes()).hexdigest()!=value['html_sha256']:raise ValueError('Frozen HTML checksum mismatch')
    return value


def coverage_report(baseline,records,failures=()):
    by_source={}
    for r in records:
        by_source.setdefault(r['source'],Counter())[normalize_title(r['row']['title'])]+=1
    counts=Counter({title:max(values[title] for values in by_source.values()) for values in by_source.values() for title in values})
    missing=[];occurrences=Counter()
    for entry in baseline['papers']:
        title=normalize_title(entry['title']);occurrences[title]+=1
        if counts[title]<occurrences[title]:
            missing.append({**entry,'reason':'no_exact_normalized_title_match; source absence or title variation requires review','source_failures':list(failures)})
    expected=baseline['expected_count'];matched=expected-len(missing)
    return {'format_version':'a-coverage-report/1','venue':baseline['venue'],'year':baseline['year'],
        'baseline_revision':baseline['revision'],'baseline_source_url':baseline['source_url'],'baseline_expected_papers':expected,
        'matched_papers':matched,'coverage_ratio':round(matched/expected,6),'missing':missing,
        'unmatched_source_titles':sorted({r['row']['title'] for r in records if normalize_title(r['row']['title']) not in occurrences}),
        'source_counts':dict(Counter(r['source'] for r in records)),
        'missing_fields':{field:[{'source':r['source'],'source_id':r['row']['source_id']} for r in records if not r['row'].get(field)] for field in ('abstract','doi','authors')},
        'source_failures':list(failures)}


def collect_scope(venue,year,directory,*,with_annotations=False,require_all_sources=False,source_options=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    options=source_options or {}
    oa=options.get('openalex',{});dblp=options.get('dblp',{})
    baseline=freeze_baseline(venue,year,directory)
    records=[];failures=[];filtered=[]
    oa_file=directory/'openalex.jsonl'
    try:
        if oa_file.exists():
            manifest=json.loads(oa_file.with_suffix('.manifest.json').read_text())
            if (manifest.get('venue'),manifest.get('year'),manifest.get('source'))!=(venue,year,'openalex') or hashlib.sha256(oa_file.read_bytes()).hexdigest()!=manifest.get('sha256'):raise ValueError('Cached OpenAlex checksum/scope mismatch')
            if bool(manifest.get('requested_fields'))!=with_annotations:raise ValueError('Use another directory for a different annotation mode')
        else:manifest=fetch_batch(venue,year,oa_file,with_annotations=with_annotations,page_size=min(100,oa.get('page_size',100)),retries=oa.get('max_retries',5))
        values=[json.loads(line) for line in oa_file.read_text(encoding='utf-8').splitlines() if line.strip()]
        if len(values)!=manifest['count']:raise ValueError('Cached OpenAlex count mismatch')
        for work in values:
            try:
                row=openalex_work_row(work,venue,year)
                if is_front_matter(row):filtered.append({'source':'openalex','source_id':work['id'],'reason':'proceedings_front_matter'});continue
                records.append({'source':'openalex','row':row})
            except (ValueError,KeyError,TypeError) as exc:filtered.append({'source':'openalex','source_id':work.get('id'),'reason':safe_error(exc)})
    except (requests.RequestException,ValueError,RuntimeError) as exc:failures.append({'source':'openalex','reason':safe_error(exc)})
    dblp_path=directory/'dblp.json'
    try:
        if dblp_path.exists():
            saved=json.loads(dblp_path.read_text());checksum=saved.pop('sha256')
            if digest(saved)!=checksum or (saved['venue'],saved['year'])!=(venue,year):raise ValueError('DBLP snapshot scope/checksum mismatch')
            rows=saved['rows']
        else:
            from .dblp import fetch_sparql
            rows=fetch_sparql(venue,year,retries=dblp.get('max_retries',2),page_size=dblp.get('page_size',500))
            saved={'venue':venue,'year':year,'rows':rows};saved['sha256']=digest(saved);write_json(dblp_path,saved)
        records.extend({'source':'dblp','row':row} for row in rows if not is_front_matter(row))
    except (requests.RequestException,ValueError,KeyError) as exc:failures.append({'source':'dblp','reason':safe_error(exc)})
    if require_all_sources and failures:raise CollectionIncomplete(failures)
    if not records:raise ValueError('No verified formal records collected: '+canonical(failures))
    report=coverage_report(baseline,records,failures);report['filtered_records']=filtered
    payload={'format_version':'a-formal-input/1','venue':venue,'year':year,'baseline_revision':baseline['revision'],'records':records}
    output=directory/'formal-input.json';report_path=directory/'coverage.json'
    if output.exists():
        if json.loads(output.read_text())!=payload:raise ValueError('Formal input is frozen; use a new directory for changed data')
    else:write_json(output,payload)
    if not report_path.exists():write_json(report_path,report)
    return {'venue':venue,'year':year,'input':str(output),'records':len(records),'matched':report['matched_papers'],'expected':report['baseline_expected_papers'],'coverage':report['coverage_ratio'],'source_failures':failures}


def main():
    parser=argparse.ArgumentParser(description='Collect official conference scopes with frozen coverage denominators')
    parser.add_argument('scopes',nargs='+',help='Explicit scope such as CVPR:2025')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--with-annotations',action='store_true');parser.add_argument('--review-coverage',action='store_true')
    args=parser.parse_args();results=[]
    for scope in args.scopes:
        venue,year=scope.upper().split(':');result=collect_scope(venue,int(year),args.output/f'{venue.lower()}_{year}',with_annotations=args.with_annotations);results.append(result)
        if args.review_coverage:
            result['reviewed_coverage']=review_coverage_links(args.output/f'{venue.lower()}_{year}')
            result['missing_review']=review_missing_titles(args.output/f'{venue.lower()}_{year}')
        print(canonical(result),flush=True)
    print(json.dumps(results,ensure_ascii=False,indent=2))



def review_coverage_links(directory):
    """Freeze DBLP's official document links to distinguish title spelling differences from missing papers."""
    from .dblp import SPARQL_URL
    from urllib.parse import urlsplit,unquote
    directory=Path(directory);baseline=load_baseline(directory/'baseline.json');path=directory/'dblp-document-links.json'
    if path.exists():
        saved=json.loads(path.read_text());checksum=saved.pop('revision')
        if digest(saved)!=checksum or saved['baseline_revision']!=baseline['revision']:raise ValueError('Coverage link snapshot checksum/scope mismatch')
        saved['revision']=checksum
    else:
        venue,year=baseline['venue'],baseline['year'];slug=venue.lower()
        query=f'''PREFIX d: <https://dblp.org/rdf/schema#>
        SELECT DISTINCT ?pub ?url WHERE {{?pub a d:Inproceedings; d:listedOnTocPage <https://dblp.org/db/conf/{slug}/{slug}{year}>; d:documentPage ?url.
        FILTER(STRSTARTS(STR(?url),"https://openaccess.thecvf.com/") || STRSTARTS(STR(?url),"http://openaccess.thecvf.com/"))}} ORDER BY ?pub ?url'''
        for attempt in range(3):
            try:
                response=requests.get(SPARQL_URL,params={'query':query,'format':'json'},timeout=90);response.raise_for_status()
                bindings=response.json()['results']['bindings'];break
            except (requests.RequestException,ValueError,KeyError):
                if attempt==2:raise
                import time
                time.sleep(2**attempt)
        saved={'format_version':'a-coverage-links/1','endpoint':SPARQL_URL,'baseline_revision':baseline['revision'],
            'retrieved_at':datetime.now(timezone.utc).isoformat(),'links':[{'source_id':v['pub']['value'].removeprefix('https://dblp.org/rec/'),'url':v['url']['value']} for v in bindings]}
        saved['revision']=digest(saved);write_json(path,saved)
    payload=json.loads((directory/'formal-input.json').read_text());original=json.loads((directory/'coverage.json').read_text())
    def url_key(url):
        parsed=urlsplit(url);return parsed.hostname,unquote(parsed.path)
    actual_ids={r['row']['source_id'] for r in payload['records'] if r['source']=='dblp'}
    official_links={url_key(entry['url']) for entry in saved['links'] if entry['source_id'] in actual_ids}
    title_counts={}
    for row in payload['records']:title_counts.setdefault(row['source'],Counter())[normalize_title(row['row']['title'])]+=1
    titles={key:max(c[key] for c in title_counts.values()) for counts in title_counts.values() for key in counts}
    occurrences=Counter();missing=[];by_link=0;by_title=0
    for paper in baseline['papers']:
        title=normalize_title(paper['title']);occurrences[title]+=1
        if url_key(paper['source_url']) in official_links:by_link+=1
        elif occurrences[title]<=titles.get(title,0):by_title+=1
        else:missing.append({**paper,'reason':'no_official_document_link_or_exact_normalized_title_in_collected_sources','source_failures':original['source_failures']})
    result={**original,'coverage_basis':'frozen_official_document_links_or_exact_normalized_titles',
        'document_link_revision':saved['revision'],'matched_by_document_link':by_link,'matched_by_title':by_title,
        'matched_papers':by_link+by_title,'coverage_ratio':round((by_link+by_title)/baseline['expected_count'],6),'missing':missing}
    output=directory/'coverage-reviewed.json'
    if not output.exists():write_json(output,result)
    return {key:result[key] for key in ('venue','year','baseline_expected_papers','matched_papers','matched_by_document_link','coverage_ratio')}


def review_missing_titles(directory):
    """Offer evidence for manual review without counting fuzzy matches as coverage."""
    from difflib import get_close_matches,SequenceMatcher
    directory=Path(directory)
    report=json.loads((directory/'coverage-reviewed.json').read_text())
    payload=json.loads((directory/'formal-input.json').read_text())
    lookup={}
    for record in payload['records']:lookup.setdefault(normalize_title(record['row']['title']),[]).append(record)
    findings=[]
    for paper in report['missing']:
        title=normalize_title(paper['title']);nearest=get_close_matches(title,list(lookup),n=1,cutoff=.82)
        candidates=[]
        if nearest:
            for record in lookup[nearest[0]]:
                row=record['row'];candidates.append({'title':row['title'],'source':record['source'],'source_id':row['source_id'],'source_url':row.get('source_url'),'doi':row.get('doi'),'similarity':round(SequenceMatcher(None,title,nearest[0]).ratio(),4)})
        findings.append({**paper,'reason':'possible_title_variant_requires_manual_review' if candidates else 'no_close_record_in_frozen_sources_requires_manual_review','candidates':candidates,'counted_as_covered':False})
    value={'format_version':'a-missing-review/1','baseline_revision':report['baseline_revision'],'source_input_sha256':hashlib.sha256((directory/'formal-input.json').read_bytes()).hexdigest(),'venue':report['venue'],'year':report['year'],'unmatched_count':len(findings),'items':findings}
    value['revision']=digest(value)
    path=directory/'missing-review.json'
    if not path.exists():write_json(path,value)
    return {'venue':value['venue'],'year':value['year'],'unmatched':len(findings),'possible_title_variants':sum(bool(row['candidates']) for row in findings)}


if __name__=='__main__':main()
