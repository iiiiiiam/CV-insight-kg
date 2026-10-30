import { createRouter, createWebHistory } from 'vue-router'
import { MENU } from './navigation.ts'
import { auth,refreshSession } from './stores/auth.ts'

const placeholder=()=>import('./views/PlaceholderView.vue')
export const router=createRouter({
  history:createWebHistory(),
  routes:[
    {path:'/',redirect:'/research/papers'},
    {path:'/research/papers',component:()=>import('./views/ResearchView.vue'),meta:{title:'研究工作台'}},
    {path:'/research/graph',component:()=>import('./views/ResearchView.vue'),meta:{title:'图谱探索'}},
    {path:'/research/papers/:id',component:()=>import('./views/PaperView.vue'),meta:{title:'论文详情'}},
    {path:'/admin/login',component:()=>import('./views/LoginView.vue'),meta:{title:'管理员登录'}},
    {path:'/admin/access-check',component:()=>import('./views/SessionView.vue'),meta:{title:'会话与权限验证',requiresAuth:true}},
    {path:'/admin/datasets',component:()=>import('./views/DataManagementView.vue'),meta:{title:'基准清单',requiresAuth:true}},
    {path:'/admin/imports',component:()=>import('./views/DataManagementView.vue'),meta:{title:'创建固定样本导入',requiresAuth:true}},
    {path:'/admin/jobs',component:()=>import('./views/DataManagementView.vue'),meta:{title:'任务与批次论文',requiresAuth:true}},
    {path:'/admin/reviews',component:()=>import('./views/CandidateView.vue'),meta:{title:'候选与证据预览',requiresAuth:true}},
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
