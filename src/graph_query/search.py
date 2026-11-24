"""Batch-wide AND across dimensions, OR within each dimension."""
import json
import re
from pathlib import Path
TERMS=json.loads(Path(__file__).with_name('search_aliases.json').read_text(encoding='utf-8'))['terms']
def fold(value):return re.sub(r"\s+", " ", str(value).strip()).casefold()
def normalize(filters):
 out={}
 for key,value in filters.items():
  if value is None or value=='' or value==[]:continue
  if key=='q':out[key]=value;continue
  values=value if isinstance(value,list) else [value]
  if key=='year':out[key]=values;continue
  tokens={fold(v) for v in values}
  for term in TERMS:
   if term['kind']==key and tokens.intersection(fold(a) for a in [term['name'],*term.get('aliases',[])]):
    tokens.update([fold(term['name']),fold(term['kind']+':term:'+term['key'])])
  out[key]=sorted(tokens)
 return out

def where(filters):
 clauses=["p.batch_id=$batch", "p.kind='paper'"]
 if filters.get('q'):clauses.append('toLower(p.name) CONTAINS toLower($q)')
 if filters.get('year'):clauses.append('p.year IN $year')
 if filters.get('author_id'):clauses.append("EXISTS { MATCH (p)-[:CV_LINK {kind:'has_author'}]->(a:CVEntity {batch_id:$batch,kind:'author'}) WHERE toLower(a.id) IN $author_id OR toLower(a.source_id) IN $author_id }")
 if filters.get('direction'):clauses.append('any(v IN coalesce(p.direction_tokens,[]) WHERE v IN $direction)')
 for kind in ('author','institution','topic','method','task','dataset','venue'):
  if not filters.get(kind):continue
  route="(p)-[:CV_LINK {kind:'has_author'}]->(:CVEntity)-[aff:CV_LINK {kind:'affiliated_with'}]->" if kind=='institution' else '(p)-[:CV_LINK]->'
  match=f"EXISTS {{ MATCH {route}(f:CVEntity {{batch_id:$batch,kind:'{kind}'}}) WHERE (toLower(f.id) IN ${kind} OR toLower(f.source_id) IN ${kind} OR toLower(f.name) IN ${kind} OR any(v IN coalesce(f.search_tokens,[]) WHERE v IN ${kind}))"
  if kind=='institution':match+=' AND p.id IN aff.paper_ids'
  clauses.append(match+' }')
 return ' AND '.join(clauses)

def metadata(node, batch=None):
 if node.get('kind')!='paper':return node
 part=node.get('effective_partition');raw=part['input'] if part else {}
 authors=[{'id': 'author:'+a['author']['id'] if a.get('author',{}).get('id') else None,'source_id':a.get('author',{}).get('id'),'name':a.get('author',{}).get('display_name')} for a in raw.get('authorships',[])]
 node.update(openalex_id=raw.get('openalex_id',node.get('source_id')),sources=[{'url':raw['source_url'],'source_id':raw['openalex_id']}] if raw else [],venue=raw.get('venue'),authors=authors,author_names=[a['name'] for a in authors],citation_count=None,source_updated_at=None,knowledge_exported_at=node.get('updated_at') if part else None,graph_published_at=(batch or {}).get('published_at'),data_revision=(batch or {}).get('source_revision'),source_url=raw.get('source_url',node.get('source_url')),metadata=raw,field_notes={'citation_count':'not supplied by PaperInput/effective','source_updated_at':'not supplied; graph import/export time is not source update time','updated_at':'legacy import/export compatibility field, not paper source update time'})
 return node
