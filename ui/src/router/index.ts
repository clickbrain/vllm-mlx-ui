import { createRouter, createWebHashHistory } from 'vue-router'
import ServeView from '@/views/ServeView.vue'
import ModelsView from '@/views/ModelsView.vue'
import SettingsView from '@/views/SettingsView.vue'
import ChatView from '@/views/ChatView.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/serve' },
    { path: '/serve', component: ServeView },
    { path: '/models', component: ModelsView },
    { path: '/settings', component: SettingsView },
    { path: '/chat', component: ChatView }
  ]
})
