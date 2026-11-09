import { createRouter, createWebHistory } from 'vue-router'
import { MENU } from './navigation.ts'
import { auth,refreshSession } from './stores/auth.ts'

const placeholder=()=>import('./views/PlaceholderView.vue')
export const router=createRouter({
  history:createWebHistory(),
  routes:[
    {path:'/',redirect:'/research/papers'},
    {path:'/research/papers',component:()=>import('./views/ResearchView.vue'),meta:{title:'研究工作台'}},
    {path:'/research/raw-papers',component:()=>import('./views/ResearchView.vue'),meta:{title:'A 原始论文'}},
    {path:'/research/knowledge',component:()=>import('./views/KnowledgeView.vue'),meta:{title:'知识与证据'}},
    {path:'/admin/knowledge-feedback',component:()=>import('./views/KnowledgeFeedbackView.vue'),meta:{title:'用户反馈处理',requiresAuth:true}},
    {path:'/research/graph',component:()=>import('./views/ResearchView.vue'),meta:{title:'图谱探索'}},
    {path:'/research/graph/expand',component:()=>import('./views/ResearchView.vue'),meta:{title:'多跳图谱探索'}},
    ...['authors','institutions'].flatMap(kind=>[
      {path:`/research/${kind}`,component:()=>import('./views/GraphProfileView.vue'),meta:{title:kind==='authors'?'作者证据画像':'机构证据画像'}},
      {path:`/research/${kind}/:id(.*)`,component:()=>import('./views/GraphProfileView.vue'),meta:{title:kind==='authors'?'作者证据画像':'机构证据画像'}},
    ]),
    {path:'/research/papers/:id',component:()=>import('./views/PaperView.vue'),meta:{title:'论文详情'}},
    {path:'/admin/login',component:()=>import('./views/LoginView.vue'),meta:{title:'管理员登录'}},
    {path:'/admin/access-check',component:()=>import('./views/SessionView.vue'),meta:{title:'会话与权限验证',requiresAuth:true}},
    {path:'/admin/overview',component:()=>import('./views/DataOverviewView.vue'),meta:{title:'数据管理概览',requiresAuth:true}},
    {path:'/admin/datasets',component:()=>import('./views/DataManagementView.vue'),meta:{title:'数据集',requiresAuth:true}},
    {path:'/admin/imports',component:()=>import('./views/DataManagementView.vue'),meta:{title:'论文导入',requiresAuth:true}},
    {path:'/admin/jobs',component:()=>import('./views/DataManagementView.vue'),meta:{title:'导入记录',requiresAuth:true}},
    // 旧 confirmed-only 审核入口不再属于公共发布流程；保留地址兼容并导向反馈处理。
    {path:'/admin/reviews',redirect:'/admin/knowledge-feedback'},
    {path:'/admin/reviews/edit',redirect:'/admin/knowledge-feedback'},
    {path:'/admin/reviews/demo-review',redirect:'/admin/knowledge-feedback'},
    // 图谱由后台自动发布；旧管理地址仅保留跳转，不再提供同步页面。
    {path:'/admin/graph/sync',redirect:'/admin/overview'},
    {path:'/admin/graph/sync/history',redirect:'/admin/overview'},
    {path:'/admin/graph/batches/check',redirect:'/admin/overview'},
    {path:'/admin/graph/batches/publish',redirect:'/admin/overview'},
    {path:'/admin/batches/pending',redirect:'/admin/overview'},
    {path:'/admin/batches/pending/publish',redirect:'/admin/overview'},
    ...MENU.filter(n=>!n.implemented).map(n=>({path:n.path,component:placeholder,meta:{title:n.label,navId:n.id,requiresAuth:n.path.startsWith('/admin/')}})),
    {path:'/:pathMatch(.*)*',component:placeholder,meta:{title:'页面不存在',notFound:true}},
  ],
  scrollBehavior:()=>({top:0}),
})
router.beforeEach(async to=>{
  if(to.meta.requiresAuth){await refreshSession(true);if(!auth.session)return {path:'/admin/login',query:{redirect:to.fullPath}}}
  return true
})
router.afterEach(to=>{document.title=`${String(to.meta.title??'研究工作台')} · 知域 Atlas`})
