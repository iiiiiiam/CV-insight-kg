import assert from 'node:assert/strict'
import test from 'node:test'
import {downloadPaperCsv} from '../src/services/admin.ts'
import {ApiError} from '../src/services/http.ts'

test('paper CSV export sends the batch filter and verifies the download contract',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async(input,init)=>{
    const url=new URL(String(input),'http://test')
    assert.equal(url.pathname,'/api/admin/export')
    assert.equal(url.searchParams.get('batch_id'),'17')
    assert.equal(init?.credentials,'same-origin')
    return new Response('\ufeffpaper_id,title\r\n1,Fixture\r\n',{headers:{
      'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename="papers.csv"','X-Paper-Count':'1',
    }})
  }
  try{
    const result=await downloadPaperCsv({batchId:17})
    assert.equal(result.filename,'papers-batch-17.csv')
    assert.equal(result.count,1)
    assert.match(await result.blob.text(),/Fixture/)
  }finally{globalThis.fetch=previous}
})

test('paper CSV export surfaces an upstream error and rejects malformed success responses',async()=>{
  const previous=globalThis.fetch
  try{
    globalThis.fetch=async()=>Response.json({error:{message:'一次最多导出 10000 篇'}},{status:422})
    await assert.rejects(downloadPaperCsv(),(error:unknown)=>error instanceof ApiError&&error.status===422&&/10000/.test(error.message))
    globalThis.fetch=async()=>Response.json({items:[]},{headers:{'X-Paper-Count':'0'}})
    await assert.rejects(downloadPaperCsv(),/缺少 CSV 类型或论文数量/)
  }finally{globalThis.fetch=previous}
})
