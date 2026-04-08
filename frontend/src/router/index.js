import { createRouter, createWebHistory } from 'vue-router'
import ChatUI from '../views/ChatUI.vue'
import AdminDashboard from '../views/AdminDashboard.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', component: ChatUI, meta: { title: '智能对话' } },
  { path: '/admin', component: AdminDashboard, meta: { title: '角色管理' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = `${to.meta.title || 'BtB'} — Deep Dialogue Intelligence`
})

export default router
