import test from 'node:test'
import assert from 'node:assert/strict'
import {batchCode,importProgress} from '../src/services/import-progress.ts'
import type {JobInfo} from '../src/services/admin.ts'
const job=(status:string,succeeded=0,failed=0,skipped=0)=>({id:47,status,succeeded,failed,progress:{total:20,succeeded,failed,skipped,pending:20-succeeded-failed-skipped}} as JobInfo)
test('batch identity uses the server batch code with a stable ID fallback',()=>{
 assert.equal(batchCode({id:47}),'BATCH-000047')
 assert.equal(batchCode({id:47,batch_code:'BATCH-000047'}),'BATCH-000047')
})
test('queued and partial real processing counts produce actual progress',()=>{
 assert.deepEqual([importProgress(job('queued')).percent,importProgress(job('queued')).label],[0,'等待处理'])
 const value=importProgress(job('running',7))
 assert.deepEqual([value.processed,value.total,value.percent,value.active],[7,20,35,true])
})
test('finished and failed tasks do not retain a running label',()=>{
 const done=importProgress(job('succeeded',20)),partial=importProgress(job('partial',18,2)),failed=importProgress(job('failed'))
 assert.deepEqual([done.label,done.percent,done.active],['已完成',100,false])
 assert.deepEqual([partial.label,partial.failed,partial.percent,partial.active],['部分完成',2,100,false])
 assert.deepEqual([failed.label,failed.percent,failed.active],['导入失败',0,false])
 assert.equal(importProgress({...job('failed'),progress:undefined,paper_count:0}).percent,0)
})
