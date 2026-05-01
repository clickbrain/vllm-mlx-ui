import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/serve' },
    { path: '/serve', component: () => import('@/views/ServeView.vue') },
    { path: '/models', component: () => import('@/views/ModelsView.vue') },
    { path: '/benchmarks', component: () => import('@/views/BenchmarkView.vue') },
    { path: '/settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/chat', component: () => import('@/views/ChatView.vue') },
    { path: '/docs', component: () => import('@/views/DocsView.vue') },
  ]
})
