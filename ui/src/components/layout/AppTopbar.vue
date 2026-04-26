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

const route = useRoute()
const router = useRouter()
const updatesStore = useUpdatesStore()
const isLight = ref(false)

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

function toggleTheme() {
  isLight.value = !isLight.value
  if (isLight.value) {
    document.documentElement.setAttribute('data-theme', 'light')
  } else {
    document.documentElement.removeAttribute('data-theme')
  }
}
</script>

<template>
  <header class="topbar">
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
  font-size: 11px;
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
</style>
