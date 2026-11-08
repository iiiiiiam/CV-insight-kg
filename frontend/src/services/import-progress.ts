import type {JobInfo} from './admin.ts'

export function batchCode(job:Pick<JobInfo,'id'> & {batch_code?:string}){
  return job.batch_code||`BATCH-${String(job.id).padStart(6,'0')}`
}
export function importProgress(job:JobInfo){
  const total=Math.max(0,job.progress?.total??job.paper_count??0)
  const succeeded=job.progress?.succeeded??job.succeeded
  const failed=job.progress?.failed??job.failed
  const skipped=job.progress?.skipped??0
  const processed=Math.max(0,succeeded+failed+skipped)
  return {total,processed,succeeded,failed,skipped,
    percent:total?Math.min(100,Math.round(processed/total*100)):0,
    active:['queued','running'].includes(job.status),
    label:({queued:'等待处理',running:'正在导入',succeeded:'已完成',partial:'部分完成',failed:'导入失败'} as Record<string,string>)[job.status]??job.status}
}
