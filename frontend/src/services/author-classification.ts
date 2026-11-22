import type {AuthorKnowledgeTag} from './knowledge.ts'

export interface AuthorClassificationInput {
  paperCount:number
  years:Array<{year:number;paper_count:number}>
  topics:Array<{id:string;name:string;paper_count:number;share?:number}>
  institutionCount:number
  knowledgeTags?:AuthorKnowledgeTag[]|null
}

export interface AuthorProfileDimension {
  code:string
  label:string
  evidence:string
}

export interface AuthorProfileClassification {
  code:string|null
  title:string
  summary:string
  dimensions:AuthorProfileDimension[]
  descriptors:string[]
  complete:boolean
}

const driverMeta={
  topic:{code:'R',label:'主题导向',noun:'主题'},
  method:{code:'M',label:'方法驱动',noun:'方法'},
  task:{code:'T',label:'任务驱动',noun:'任务'},
  dataset:{code:'D',label:'数据驱动',noun:'数据集'},
} as const

function driverDimension(tags:AuthorKnowledgeTag[]|null|undefined):AuthorProfileDimension|null{
  if(!tags?.length)return null
  const papers=new Map<AuthorKnowledgeTag['kind'],Set<string>>(
    (Object.keys(driverMeta) as AuthorKnowledgeTag['kind'][]).map(kind=>[kind,new Set<string>()]),
  )
  for(const tag of tags)for(const support of tag.supports)papers.get(tag.kind)?.add(support.paper_id)
  const scores=(Object.keys(driverMeta) as AuthorKnowledgeTag['kind'][]).map(kind=>({kind,count:papers.get(kind)?.size??0}))
  const total=scores.reduce((sum,item)=>sum+item.count,0)
  if(!total)return null
  const ordered=[...scores].sort((a,b)=>b.count-a.count||a.kind.localeCompare(b.kind))
  const first=ordered[0]!,second=ordered[1]!
  if(first.count===second.count||first.count/total<.4){
    const evidence=scores.filter(item=>item.count).map(item=>`${driverMeta[item.kind].noun} ${item.count} 篇`).join('、')
    return {code:'B',label:'知识均衡',evidence:`各类知识支持较均衡（${evidence}）`}
  }
  const meta=driverMeta[first.kind]
  return {code:meta.code,label:meta.label,evidence:`${first.count} 篇论文提供${meta.noun}类标签支持`}
}

export function classifyAuthorProfile(input:AuthorClassificationInput):AuthorProfileClassification{
  const dimensions:AuthorProfileDimension[]=[]
  const descriptors:string[]=[]
  const topTopic=[...input.topics].sort((a,b)=>b.paper_count-a.paper_count)[0]
  if(input.paperCount>=3&&topTopic){
    const share=Math.min(1,Math.max(0,topTopic.share??topTopic.paper_count/input.paperCount))
    const focused=share>=.6
    dimensions.push({code:focused?'F':'X',label:focused?'方向聚焦':'多向交叉',
      evidence:`最高主题“${topTopic.name}”覆盖约 ${Math.round(share*100)}% 的关联论文`})
  }else descriptors.push(input.paperCount<3?'论文样本较少':'暂无主题分布')

  const driver=driverDimension(input.knowledgeTags)
  if(driver)dimensions.push(driver)
  else descriptors.push(input.knowledgeTags===undefined?'知识驱动待 B 标签就绪':'知识标签样本不足')

  const years=[...new Set(input.years.filter(item=>item.year>0&&item.paper_count>0).map(item=>item.year))].sort((a,b)=>a-b)
  if(years.length){
    const continuous=years.length>=3&&years.at(-1)!-years[0]!>=2
    dimensions.push({code:continuous?'C':'S',label:continuous?'持续活跃':'阶段集中',
      evidence:continuous?`论文分布于 ${years[0]}—${years.at(-1)} 年的 ${years.length} 个年份`:`论文集中于 ${years.length} 个年份`})
  }else descriptors.push('年份证据不足')

  const networked=input.institutionCount>=2
  dimensions.push({code:networked?'N':'O',label:networked?'多机构关联':'机构关联集中',
    evidence:input.institutionCount?`当前批次关联 ${input.institutionCount} 个有论文证据的机构`:'当前批次没有可核对的机构关联'})

  for(const item of dimensions)descriptors.push(item.label)
  const complete=input.paperCount>=3&&dimensions.length===4
  const code=complete?dimensions.map(item=>item.code).join('-'):null
  const title=complete?`${dimensions.map(item=>item.label.replace('方向','').replace('多向','多向')).join(' · ')}型`:'描述型研究画像'
  return {
    code,title,complete,dimensions,descriptors:[...new Set(descriptors)],
    summary:complete?'四段画像码只概括当前发布批次中的论文证据。':'当前证据不足以形成完整画像码，已保留能够核对的描述标签。',
  }
}
