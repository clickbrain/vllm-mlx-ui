import { createRouter, createWebHistory } from 'vue-router'
import ServeView from '@/views/ServeView.vue'
import ModelsView from '@/views/ModelsView.vue'
import SettingsView from '@/views/SettingsView.vue'
import ChatView from '@/views/ChatView.vue'
import BenchmarkView from '@/views/BenchmarkView.vue'
import DocsView from '@/views/DocsView.vue'

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
