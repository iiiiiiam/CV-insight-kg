/** Title search and browser-local reading history for the knowledge page. */
export interface PaperChoice {paper_id:string;title:string}
export const LAST_KNOWLEDGE_PAPER='research-insight:knowledge:last-paper:1'
interface ReadingStorage {getItem(key:string):string|null;setItem(key:string,value:string):void}

export function filterPaperTitles<T extends PaperChoice>(papers:T[],query:string):T[]{
  const words=query.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean)
  return papers.filter(p=>{const title=p.title.normalize('NFKC').toLocaleLowerCase();return words.every(word=>title.includes(word))})
}
export function resolveReadingPaper(papers:PaperChoice[],requested:string,remembered:string|null):string{
  const ids=new Set(papers.map(p=>p.paper_id))
  return ids.has(requested)?requested:remembered&&ids.has(remembered)?remembered:papers[0]?.paper_id??''
}
export function readLastPaper(storage:ReadingStorage):string|null{
  try{return storage.getItem(LAST_KNOWLEDGE_PAPER)}catch{return null}
}
export function rememberPaper(storage:ReadingStorage,paperId:string):boolean{
  try{storage.setItem(LAST_KNOWLEDGE_PAPER,paperId);return true}catch{return false}
}
