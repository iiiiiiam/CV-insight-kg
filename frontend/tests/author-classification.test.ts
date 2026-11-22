import assert from 'node:assert/strict'
import test from 'node:test'
import {classifyAuthorProfile} from '../src/services/author-classification.ts'
import type {AuthorKnowledgeTag} from '../src/services/knowledge.ts'

function tag(kind:AuthorKnowledgeTag['kind'],papers:string[]):AuthorKnowledgeTag{
  return {tag_id:`tag-${kind}`,kind,entity_key:kind,names:[kind],supporting_paper_count:papers.length,
    supports:papers.map(paper_id=>({paper_id,input_fingerprint:'fingerprint',witnesses:{}}))}
}

test('author classification builds an explainable four-part profile code',()=>{
  const result=classifyAuthorProfile({
    paperCount:6,institutionCount:3,
    years:[{year:2021,paper_count:1},{year:2022,paper_count:2},{year:2024,paper_count:3}],
    topics:[{id:'detection',name:'目标检测',paper_count:4,share:4/6}],
    knowledgeTags:[tag('method',['p1','p2','p3','p4']),tag('topic',['p1']),tag('task',['p2'])],
  })
  assert.equal(result.code,'F-M-C-N')
  assert.equal(result.complete,true)
  assert.deepEqual(result.dimensions.map(item=>item.label),['方向聚焦','方法驱动','持续活跃','多机构关联'])
  assert.match(result.dimensions[0]!.evidence,/目标检测/)
})

test('author classification falls back to descriptive labels when evidence is insufficient',()=>{
  const result=classifyAuthorProfile({
    paperCount:2,institutionCount:0,years:[{year:2024,paper_count:2}],topics:[],knowledgeTags:undefined,
  })
  assert.equal(result.code,null)
  assert.equal(result.complete,false)
  assert.ok(result.descriptors.includes('论文样本较少'))
  assert.ok(result.descriptors.includes('知识驱动待 B 标签就绪'))
  assert.ok(result.descriptors.includes('阶段集中'))
})

test('author classification uses balanced knowledge when no tag kind dominates',()=>{
  const result=classifyAuthorProfile({
    paperCount:4,institutionCount:1,years:[{year:2023,paper_count:2},{year:2024,paper_count:2}],
    topics:[{id:'vision',name:'视觉',paper_count:2,share:.5}],
    knowledgeTags:[tag('method',['p1','p2']),tag('task',['p2','p3'])],
  })
  assert.equal(result.code,'X-B-S-O')
  assert.equal(result.dimensions[1]!.label,'知识均衡')
})
