<!--
  AppTopbar — top navigation bar rendered above every page.

  Displays the current page title (derived from vue-router path) and two
  persistent actions:
  - Update indicator dot (shown when updatesStore.anyUpdate is true); clicking
    navigates to Settings so the user can apply the update.
  - Theme toggle button (dark ↔ light); writes data-theme attr on <html>.

  No props — reads page title from the route and update state from the store.
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUpdatesStore } from '@/stores/updates'

const route = useRoute()
const router = useRouter()
const updatesStore = useUpdatesStore()
const showMobileMenu = ref(false)

// Initialize theme: localStorage → OS preference → default dark
function getInitialTheme(): boolean {
  const stored = localStorage.getItem('theme')
  if (stored) return stored === 'light'
  return window.matchMedia('(prefers-color-scheme: light)').matches
}

const isLight = ref(getInitialTheme())

function setTheme(light: boolean) {
  isLight.value = light
  if (light) {
    document.documentElement.setAttribute('data-theme', 'light')
    localStorage.setItem('theme', 'light')
  } else {
    document.documentElement.removeAttribute('data-theme')
    localStorage.setItem('theme', 'dark')
  }
}

// Apply initial theme
setTheme(isLight.value)

function toggleTheme() {
  setTheme(!isLight.value)
}

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    '/serve':       'Serve',
    '/models':      'Models',
    '/benchmarks':  'Benchmarks & Data',
    '/settings':    'Settings',
    '/chat':        'Chat',
  }
  return titles[route.path] ?? 'vmUI'
})
</script>

<template>
  <header class="topbar">
    <button class="mobile-menu-btn" aria-label="Open navigation menu" @click="showMobileMenu = true">
      <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18" aria-hidden="true">
        <path fill-rule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd" />
      </svg>
    </button>
    <h1 class="topbar-title">{{ pageTitle }}</h1>
    <div class="topbar-actions">
      <button
        v-if="updatesStore.anyUpdate"
        class="update-indicator"
        title="Updates available — click to view"
        @click="router.push('/settings')"
      >
        <span class="update-dot" />
        Update available
      </button>
      <button class="theme-toggle" @click="toggleTheme" :title="isLight ? 'Switch to dark mode' : 'Switch to light mode'">
        <svg v-if="isLight" viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clip-rule="evenodd" />
        </svg>
        <svg v-else viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
        </svg>
      </button>
    </div>
  </header>

  <!-- Mobile overlay menu -->
  <Teleport to="body">
    <div v-if="showMobileMenu" class="mobile-overlay" @click.self="showMobileMenu = false" @keydown.escape="showMobileMenu = false">
      <nav class="mobile-nav" role="dialog" aria-label="Navigation menu">
        <div class="mobile-nav-header">
          <span class="logo-mark">vm</span><span class="logo-accent">UI</span>
          <button class="mobile-nav-close" aria-label="Close menu" @click="showMobileMenu = false">
            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
        <RouterLink to="/serve" class="mobile-nav-item" :class="{ active: route.path === '/serve' || route.path === '/' }" @click="showMobileMenu = false">Serve</RouterLink>
        <RouterLink to="/models" class="mobile-nav-item" :class="{ active: route.path.startsWith('/models') }" @click="showMobileMenu = false">Models</RouterLink>
        <RouterLink to="/benchmarks" class="mobile-nav-item" :class="{ active: route.path.startsWith('/benchmarks') }" @click="showMobileMenu = false">Benchmarks</RouterLink>
        <RouterLink to="/chat" class="mobile-nav-item" :class="{ active: route.path.startsWith('/chat') }" @click="showMobileMenu = false">Chat</RouterLink>
        <RouterLink to="/docs" class="mobile-nav-item" :class="{ active: route.path.startsWith('/docs') }" @click="showMobileMenu = false">Docs</RouterLink>
        <RouterLink to="/settings" class="mobile-nav-item" :class="{ active: route.path.startsWith('/settings') }" @click="showMobileMenu = false">
          Settings
          <span v-if="updatesStore.anyUpdate" class="update-badge" />
        </RouterLink>
      </nav>
    </div>
  </Teleport>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  height: 46px;
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
  background: var(--bg-surface);
}

.topbar-title {
  flex: 1;
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: -.3px;
  color: var(--tx-primary);
  font-family: var(--font-display);
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.update-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.25);
  border-radius: var(--r-pill);
  font-size: 13px;
  font-weight: 600;
  color: var(--cu-400);
  cursor: pointer;
  letter-spacing: .03em;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.update-indicator:hover {
  background: rgba(245,158,11,.14);
  border-color: rgba(245,158,11,.4);
}

.update-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cu-400);
  flex-shrink: 0;
  box-shadow: 0 0 4px rgba(245,158,11,.6);
}

.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-tertiary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}
.theme-toggle:hover {
  background: var(--bg-elevated);
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}

/* Mobile hamburger — hidden on desktop */
.mobile-menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.mobile-menu-btn:hover {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}

/* Mobile overlay */
.mobile-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, .55);
  z-index: 10000;
  animation: fade-in .12s ease;
}

@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

.mobile-nav {
  position: absolute;
  top: 0;
  left: 0;
  width: 260px;
  max-width: 85vw;
  height: 100%;
  background: var(--bg-surface);
  border-right: 1px solid var(--bd-default);
  display: flex;
  flex-direction: column;
  padding: var(--space-4);
  gap: 4px;
  animation: slide-right .15s ease;
  overflow-y: auto;
}

@keyframes slide-right { from { transform: translateX(-100%); } to { transform: translateX(0); } }

.mobile-nav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
  margin-bottom: var(--space-2);
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -.4px;
}
.logo-mark { color: var(--tx-primary); }
.logo-accent { color: var(--si-400); }

.mobile-nav-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.mobile-nav-close:hover { background: var(--bg-elevated); color: var(--tx-primary); }

.mobile-nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px var(--space-3);
  border-radius: var(--r-md);
  border: 1px solid transparent;
  color: var(--tx-secondary);
  font-size: var(--text-base);
  font-weight: 500;
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}
.mobile-nav-item:hover {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}
.mobile-nav-item.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
}

@media (max-width: 720px) {
  .mobile-menu-btn { display: flex; }
  .topbar-title { margin-left: var(--space-2); }
}
</style>
