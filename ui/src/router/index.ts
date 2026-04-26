import { createRouter, createWebHashHistory } from 'vue-router'
import ServeView from '@/views/ServeView.vue'
import ModelsView from '@/views/ModelsView.vue'
import SettingsView from '@/views/SettingsView.vue'
import ChatView from '@/views/ChatView.vue'
import BenchmarkView from '@/views/BenchmarkView.vue'
import DocsView from '@/views/DocsView.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/serve' },
    { path: '/serve', component: ServeView },
    { path: '/models', component: ModelsView },
    { path: '/benchmarks', component: BenchmarkView },
    { path: '/settings', component: SettingsView },
    { path: '/chat', component: ChatView },
    { path: '/docs', component: DocsView },
  ]
})
