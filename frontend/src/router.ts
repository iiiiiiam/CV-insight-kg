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
    {path:'/admin/sources',component:()=>import('./views/SourceSettingsView.vue'),meta:{title:'来源配置',requiresAuth:true}},
    {path:'/admin/quality',component:()=>import('./views/DataQualityView.vue'),meta:{title:'数据质量',requiresAuth:true}},
    {path:'/admin/overview',component:()=>import('./views/DataOverviewView.vue'),meta:{title:'数据管理概览',requiresAuth:true}},
    {path:'/admin/datasets',component:()=>import('./views/DataManagementView.vue'),meta:{title:'数据集',requiresAuth:true}},
    {path:'/admin/imports',component:()=>import('./views/DataManagementView.vue'),meta:{title:'论文导入',requiresAuth:true}},
    {path:'/admin/jobs',component:()=>import('./views/DataManagementView.vue'),meta:{title:'导入记录',requiresAuth:true}},
    {path:'/admin/reviews',component:()=>import('./views/CandidateView.vue'),meta:{title:'候选与证据预览',requiresAuth:true}},
    {path:'/admin/reviews/edit',component:()=>import('./views/CandidateView.vue'),meta:{title:'审核与改名',requiresAuth:true,reviewEnabled:true}},
    {path:'/admin/reviews/demo-review',redirect:'/admin/reviews/edit'},
    // 旧的人工批次发布入口保留为兼容地址，但不再进入正常业务流程。
    {path:'/admin/graph/batches/check',redirect:'/admin/graph/sync'},
    {path:'/admin/graph/batches/publish',redirect:'/admin/graph/sync'},
    {path:'/admin/batches/pending',redirect:'/admin/graph/sync'},
    {path:'/admin/batches/pending/publish',redirect:'/admin/graph/sync'},
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
