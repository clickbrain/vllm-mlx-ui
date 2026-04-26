// SPDX-License-Identifier: Apache-2.0
/**
 * main.ts — Vue application bootstrap.
 *
 * Creates the Vue app, registers Pinia (state) and the router, mounts to
 * #app.  CSS tokens (design-system variables) are imported here so they are
 * available globally before any component renders.
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './assets/tokens.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
