<!--
  App.vue — root application shell.

  Renders the persistent layout (AppSidebar + AppTopbar) and <RouterView>
  for the active page. Also kicks off the server store's periodic status poll
  on mount so all views share live inference server state.
-->
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppTopbar from '@/components/layout/AppTopbar.vue'
import TourOverlay from '@/components/shared/TourOverlay.vue'
import CommandPalette from '@/components/shared/CommandPalette.vue'
import AuthUnlockPanel from '@/components/shared/AuthUnlockPanel.vue'
import ToastNotification from '@/components/shared/ToastNotification.vue'
import InstallEngineModal from '@/components/shared/InstallEngineModal.vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useTourStore } from '@/stores/tour'
import { useCommandPaletteStore } from '@/stores/commandPalette'

const serverStore = useServerStore()
const modelsStore = useModelsStore()
const tour = useTourStore()
const palette = useCommandPaletteStore()

function handleGlobalKeydown(e: KeyboardEvent) {
  palette.onKeydown(e)
}

let stopPolling: (() => void) | null = null

onMounted(() => {
  stopPolling = serverStore.startPolling()
  tour.checkFirstRun()
  modelsStore.resumeActiveDownloadPolls()
  document.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  stopPolling?.()
  document.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div class="app-shell">
    <TourOverlay />
    <CommandPalette />
    <AuthUnlockPanel />
    <!-- Global install modal — shown from any page when loadModel() returns needs_install -->
    <InstallEngineModal
      v-if="modelsStore.pendingInstall"
      :engine-id="modelsStore.pendingInstall.engineId"
      :engine-name="modelsStore.pendingInstall.engineName"
      :model-id="modelsStore.pendingInstall.modelId"
      @installed="modelsStore.retryLoadAfterInstall()"
      @cancel="modelsStore.clearPendingInstall()"
    />
    <AppSidebar />
    <div class="app-main">
      <AppTopbar />
      <!-- Global model-switch banner; appears on all pages during server restart for model load -->
      <div v-if="modelsStore.serverRestartingFor" class="model-switch-banner" role="status">
        <span class="banner-spinner" aria-hidden="true" />
        <span>
          Loading <strong>{{ (modelsStore.serverRestartingFor || '').split('/').pop() }}</strong>
          — server restarting, requests will resume shortly
        </span>
      </div>
      <main class="app-content">
        <RouterView v-slot="{ Component }">
          <KeepAlive include="ChatView,BenchmarkView,ModelsView">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>
    <ToastNotification />
  </div>
</template>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-canvas);
  color: var(--tx-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  -webkit-font-smoothing: antialiased;
}

.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
}

/* Model-switch global banner */
.model-switch-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px var(--space-4);
  background: rgba(245, 158, 11, 0.12);
  border-bottom: 1px solid rgba(245, 158, 11, 0.25);
  color: #F59E0B;
  font-size: var(--text-xs);
  flex-shrink: 0;
}

.banner-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(245, 158, 11, 0.3);
  border-top-color: #F59E0B;
  border-radius: 50%;
  animation: banner-spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes banner-spin {
  to { transform: rotate(360deg); }
}
</style>
