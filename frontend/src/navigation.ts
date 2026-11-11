export interface MenuItem { id:string; group:string; section:string; label:string; path:string; implemented:boolean; owner:string }
export const MENU:MenuItem[]=[
 {id:'NAV01',group:'文献调研',section:'检索与图谱',label:'公共知识检索',path:'/research/papers',implemented:true,owner:'D / C'},
 {id:'NAV06',group:'文献调研',section:'结果导出',label:'当前论文集导出',path:'/research/exports/new',implemented:false,owner:'D 后续'},
 {id:'NAV07',group:'文献调研',section:'结果导出',label:'导出进度与下载',path:'/research/exports/demo-export',implemented:false,owner:'D 后续'},
 {id:'NAV08',group:'研究分析',section:'统计与下钻',label:'研究分析看板',path:'/research/trends',implemented:true,owner:'C / D'},
 {id:'NAV10',group:'研究分析',section:'作者调研',label:'作者证据画像',path:'/research/authors',implemented:true,owner:'C / D；完整合作统计后续'},
 {id:'NAV11',group:'研究分析',section:'机构调研',label:'机构证据画像',path:'/research/institutions',implemented:true,owner:'C / D'},
 {id:'A-DATA',group:'数据管理',section:'数据概览',label:'数据管理概览',path:'/admin/overview',implemented:true,owner:'A'},
 {id:'NAV12',group:'数据管理',section:'数据集',label:'数据集',path:'/admin/datasets',implemented:true,owner:'A / D'},
 {id:'NAV13',group:'数据管理',section:'导入任务',label:'论文导入',path:'/admin/imports',implemented:true,owner:'A / D'},
 {id:'NAV14',group:'数据管理',section:'导入任务',label:'导入记录',path:'/admin/jobs',implemented:true,owner:'A / D'},
 {id:'NAV15',group:'数据管理',section:'导入任务',label:'失败任务',path:'/admin/jobs?view=errors',implemented:true,owner:'A / D'},
 {id:'NAV16',group:'文献调研',section:'论文知识',label:'知识证据与个人调整',path:'/research/knowledge',implemented:true,owner:'B / D'},
 {id:'NAV17',group:'数据管理',section:'反馈处理',label:'用户反馈处理',path:'/admin/knowledge-feedback',implemented:true,owner:'B / D'},
 {id:'NAV20',group:'系统管理',section:'管理员会话',label:'会话与权限验证',path:'/admin/access-check',implemented:true,owner:'D'},
]
