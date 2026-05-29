<!--
  AppSidebar — primary navigation sidebar rendered on every page.

  Responsibilities:
  - Navigation links: Serve, Models, Benchmark, Chat, Docs, Settings
  - Machine switcher: select between Local and configured remote machines;
    shows online/offline status with a colour dot
  - Inference server status pill: running / stopped / loading / error
  - Update badge: shows a dot when updatesStore.anyUpdate is true
  - Remote connection UI: form to add a new remote machine by host:port
  - Server start/stop shortcut from the sidebar status area

  Uses ConfirmModal for the "Remove machine" destructive action.
  Subscribes to updatesStore.checkUpdates() on mount.
-->
<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useMachinesStore } from '@/stores/machines'
import { useUpdatesStore } from '@/stores/updates'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { api } from '@/api/client'

const route = useRoute()
const router = useRouter()
const serverStore = useServerStore()
const modelsStore = useModelsStore()
const machinesStore = useMachinesStore()
const updatesStore = useUpdatesStore()

const showShutdownConfirm = ref(false)
const shuttingDown = ref(false)
const memReleaseMsg = ref('')
const scanning = ref(false)
const discoveredMachines = ref<import('@/stores/machines').Machine[]>([])
let refreshInterval: ReturnType<typeof setInterval> | null = null

// ── Engine switcher ────────────────────────────────────────────────────────────
interface EngineInfo { id: string; name: string; installed: boolean; fixed_model_display?: string | null }
const engines           = ref<EngineInfo[]>([])
const selectedEngine    = ref(serverStore.engineId)
const activeEngineInfo  = computed(() => engines.value.find(e => e.id === serverStore.engineId))
const fixedModelDisplay = computed<string | null>(() => activeEngineInfo.value?.fixed_model_display ?? null)
const switchingEngine   = ref(false)

async function loadEngines() {
  try {
    const result = await api.get<{ engines: EngineInfo[] } | EngineInfo[]>('/engines')
    const all: EngineInfo[] = Array.isArray(result) ? result : (result as any).engines ?? []
    engines.value = all.filter(e => e.installed)
  } catch { /* best-effort */ }
}

async function switchEngine(id: string) {
  if (id === serverStore.engineId || switchingEngine.value) return
  selectedEngine.value = id
  switchingEngine.value = true
  try {
    await api.post('/config', { engine_id: id })
    await serverStore.restart()
    // Phase 1: wait for server to go offline (max 10 s)
    let downElapsed = 0
    await new Promise<void>(resolve => {
      const downPoll = setInterval(async () => {
        downElapsed += 1
        await serverStore.fetchStatus()
        if (!serverStore.isRunning || downElapsed >= 10) { clearInterval(downPoll); resolve() }
      }, 1000)
    })
    // Phase 2: wait for server to come back with the target engine (max 90 s)
    let upElapsed = 0
    await new Promise<void>(resolve => {
      const upPoll = setInterval(async () => {
        upElapsed += 2
        await serverStore.fetchStatus()
        await serverStore.fetchConfig()
        if ((serverStore.engineId === id && serverStore.isRunning) || upElapsed >= 90) {
          clearInterval(upPoll)
          await serverStore.fetchMetrics()
          await modelsStore.fetchModels()
          resolve()
        }
      }, 2000)
    })
  } catch (e) {
    selectedEngine.value = serverStore.engineId  // revert on failure
    console.error('Engine switch failed', e)
  } finally {
    switchingEngine.value = false
  }
}

watch(() => serverStore.engineId, (id) => {
  if (!switchingEngine.value) selectedEngine.value = id
})

const memAvailPct = computed(() => {
  const mem = serverStore.memory
  if (!mem || !mem.total_gb) return 0
  return Math.max(0, (mem.available_gb / mem.total_gb) * 100)
})
const arcFillColor = computed(() => memAvailPct.value < 25 ? 'var(--cu-500)' : 'var(--si-500)')
const arcDashOffset = computed(() => {
  const arc = 157
  return arc - arc * (memAvailPct.value / 100)
})
const memAvailGb = computed(() => serverStore.memory?.available_gb.toFixed(1) ?? '—')
const memTotalGb = computed(() => serverStore.memory?.total_gb.toFixed(0) ?? '—')
const loadedModel = computed(() => serverStore.modelId)

// Rough heuristic: 4-bit quantised models use ~0.55 GB per billion params
const modelFitsHint = computed(() => {
  const avail = serverStore.memory?.available_gb
  if (!avail || avail < 1) return null
  const paramB = Math.floor(avail / 0.55)
  if (paramB < 1) return null
  return `~${paramB}B param models fit`
})

onMounted(() => {
  // best-effort — don't block render
  updatesStore.checkUpdates().catch(() => {})
  machinesStore.refreshOnlineStatus()
  refreshInterval = setInterval(() => machinesStore.refreshOnlineStatus(), 30000)
  if (!modelsStore.models.length) modelsStore.fetchModels().catch(() => {})
  loadEngines()
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})

function selectMachine(id: string) {
  machinesStore.setActive(id)
}

const isActive = (path: string): boolean => {
  if (path === '/serve') return route.path === '/serve' || route.path === '/'
  return route.path.startsWith(path)
}

async function releaseMemory() {
  memReleaseMsg.value = 'Releasing…'
  try {
    const r = await api.post<{ freed_gb: number; heap_notes?: string[]; warnings?: string[] }>('/memory/release')
    const freed = r?.freed_gb ?? 0
    const warnings = r?.warnings ?? []
    if (freed > 0.05) {
      memReleaseMsg.value = `Freed ${freed.toFixed(1)} GB`
    } else if (warnings.length && warnings.every(w => w.includes('Could not reach'))) {
      memReleaseMsg.value = 'Server offline — caches not cleared'
    } else {
      memReleaseMsg.value = 'Done — caches cleared'
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    memReleaseMsg.value = `Failed: ${msg}`
    console.error('Release memory failed', err)
  }
  setTimeout(() => { memReleaseMsg.value = '' }, 4500)
}

async function scanForMachines() {
  scanning.value = true
  discoveredMachines.value = []
  try {
    discoveredMachines.value = await machinesStore.scanNetwork()
  } catch (err) {
    console.error('Network scan failed', err)
  }
  scanning.value = false
}

function addDiscovered(m: import('@/stores/machines').Machine) {
  machinesStore.addMachine({ name: m.name, host: m.host, port: m.port, type: 'remote', memoryGb: 0 })
  discoveredMachines.value = discoveredMachines.value.filter(d => d.host !== m.host)
}

async function doShutdown() {
  shuttingDown.value = true
  showShutdownConfirm.value = false
  try { await serverStore.shutdown() }
  catch { /* silent — server is going down */ }
}
</script>

<template>
  <aside class="sidebar">
    <!-- Wordmark -->
    <div class="sidebar-logo">
      <span class="logo-mark">vm</span><span class="logo-accent">UI</span>
    </div>

    <!-- Nav — above the gauge -->
    <nav class="sidebar-nav">
      <RouterLink to="/serve" class="nav-item" :class="{ active: isActive('/serve') }" data-tour="serve">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" />
        </svg>
        <span>Serve</span>
      </RouterLink>

      <RouterLink to="/models" class="nav-item" :class="{ active: isActive('/models') }" data-tour="models">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M4.25 2A2.25 2.25 0 002 4.25v2.5A2.25 2.25 0 004.25 9h2.5A2.25 2.25 0 009 6.75v-2.5A2.25 2.25 0 006.75 2h-2.5zm0 9A2.25 2.25 0 002 13.25v2.5A2.25 2.25 0 004.25 18h2.5A2.25 2.25 0 009 15.75v-2.5A2.25 2.25 0 006.75 11h-2.5zm6.5-9A2.25 2.25 0 008.5 4.25v2.5A2.25 2.25 0 0010.75 9h2.5A2.25 2.25 0 0015.5 6.75v-2.5A2.25 2.25 0 0013.25 2h-2.5zm0 9a2.25 2.25 0 00-2.25 2.25v2.5A2.25 2.25 0 0010.75 18h2.5a2.25 2.25 0 002.25-2.25v-2.5a2.25 2.25 0 00-2.25-2.25h-2.5z" />
        </svg>
        <span>Models</span>
      </RouterLink>

      <RouterLink to="/benchmarks" class="nav-item" :class="{ active: isActive('/benchmarks') }" :aria-current="isActive('/benchmarks') ? 'page' : undefined">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
        </svg>
        <span>Benchmarks</span>
      </RouterLink>

      <RouterLink to="/diagnostics" class="nav-item" :class="{ active: isActive('/diagnostics') }" :aria-current="isActive('/diagnostics') ? 'page' : undefined">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2z" clip-rule="evenodd" />
        </svg>
        <span>Diagnostics</span>
      </RouterLink>

      <RouterLink to="/chat" class="nav-item" :class="{ active: isActive('/chat') }" data-tour="chat">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M2 5a2 2 0 012-2h8a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5zm3 1h6v4H5V6zm6 6H5v2h6v-2z" clip-rule="evenodd" />
          <path d="M15 7h1a2 2 0 012 2v5.5a.5.5 0 01-.5.5H15V7z" />
        </svg>
        <span>Chat</span>
      </RouterLink>

      <RouterLink to="/settings" class="nav-item" :class="{ active: isActive('/settings') }" data-tour="settings">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M7.84 1.804A1 1 0 018.82 1h2.36a1 1 0 01.98.804l.331 1.652a6.993 6.993 0 011.929 1.115l1.598-.54a1 1 0 011.186.447l1.18 2.044a1 1 0 01-.205 1.251l-1.267 1.113a7.047 7.047 0 010 2.228l1.267 1.113a1 1 0 01.206 1.25l-1.18 2.045a1 1 0 01-1.187.447l-1.598-.54a6.993 6.993 0 01-1.929 1.115l-.33 1.652a1 1 0 01-.98.804H8.82a1 1 0 01-.98-.804l-.331-1.652a6.993 6.993 0 01-1.929-1.115l-1.598.54a1 1 0 01-1.186-.447l-1.18-2.044a1 1 0 01.205-1.251l1.267-1.114a7.05 7.05 0 010-2.227L1.821 7.773a1 1 0 01-.206-1.25l1.18-2.045a1 1 0 011.187-.447l1.598.54A6.993 6.993 0 017.51 3.456l.33-1.652zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
        </svg>
        <span>Settings</span>
        <span v-if="updatesStore.anyUpdate" class="update-badge" title="Software updates available — see Settings" />
      </RouterLink>

      <div class="nav-divider" role="separator" />

      <RouterLink to="/docs" class="nav-item nav-item-util" :class="{ active: isActive('/docs') }" :aria-current="isActive('/docs') ? 'page' : undefined">
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
        </svg>
        <span>Docs</span>
      </RouterLink>
    </nav>

    <!-- Server Status Row (click to go to Serve) -->
    <button
      class="sidebar-status-row"
      title="Go to Serve page"
      @click="router.push('/serve')"
    >
      <span class="status-dot" :class="serverStore.isRunning ? 'running' : 'stopped'" />
      <div class="status-text">
        <span class="status-engine">{{ serverStore.engineId ?? 'No engine' }}</span>
        <span
          v-if="fixedModelDisplay || serverStore.modelId"
          class="status-model"
          :title="fixedModelDisplay || serverStore.modelId || ''"
        >{{ fixedModelDisplay || (serverStore.modelId ?? '').split('/').pop() }}</span>
        <span v-else class="status-model-none">No model loaded</span>
      </div>
    </button>

    <!-- Memory Arc Gauge -->
    <div class="sidebar-section gauge-section">
      <svg viewBox="0 0 120 72" xmlns="http://www.w3.org/2000/svg" class="arc-svg" aria-label="Available RAM gauge">
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke="var(--arc-track)" stroke-width="9" stroke-linecap="round" />
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" :stroke="arcFillColor" stroke-width="9" stroke-linecap="round" stroke-dasharray="157" :stroke-dashoffset="arcDashOffset" class="arc-fill" />
        <text x="60" y="50" text-anchor="middle" font-family="var(--font-mono)" font-size="19" font-weight="700" fill="var(--tx-primary)">{{ memAvailGb }}</text>
        <text x="60" y="62" text-anchor="middle" font-size="11.5" fill="var(--tx-muted)">available</text>
      </svg>
      <div v-if="loadedModel" class="gauge-model-name">{{ loadedModel }}</div>
      <div v-if="modelFitsHint" class="gauge-fits-hint">{{ modelFitsHint }}</div>
      <button class="release-mem-btn" title="Clears MLX model cache and runs OS-level memory compaction. Server stays up — model weights remain loaded. Use to reclaim inactive/cached RAM without restarting." @click="releaseMemory">
        ↺ Release Memory
      </button>
      <span v-if="memReleaseMsg" class="release-mem-msg">{{ memReleaseMsg }}</span>
    </div>

    <!-- Fleet -->
    <div class="sidebar-section fleet-section">
      <div class="fleet-header">
        <div class="section-label">Fleet</div>
        <button
          class="scan-btn"
          :disabled="scanning"
          :aria-label="scanning ? 'Scanning network' : 'Scan local network for vllm-mlx servers'"
          @click="scanForMachines"
        >
          <svg v-if="!scanning" viewBox="0 0 20 20" fill="currentColor" width="11" height="11">
            <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
          </svg>
          <span v-if="scanning" class="scan-spinner" />
        </button>
      </div>
      <div class="machine-list" role="list" aria-label="Connected machines">
        <button
          v-for="m in machinesStore.machines"
          :key="m.id"
          class="machine-item"
          :class="{ active: m.id === machinesStore.activeMachineId }"
          role="listitem"
          :aria-pressed="m.id === machinesStore.activeMachineId"
          :title="`${m.name} — ${m.online ? 'Online' : 'Offline'}`"
          @click="selectMachine(m.id)"
        >
          <span class="machine-dot" :class="m.online ? 'online' : 'offline'" />
          <span class="machine-name">{{ m.name }}</span>
          <span v-if="m.type === 'remote'" class="machine-host">{{ m.host }}</span>
        </button>
      </div>
      <!-- Discovered machines waiting to be added -->
      <div v-if="discoveredMachines.length > 0" class="discovered-list">
        <div class="discovered-label">Found on network</div>
        <div
          v-for="d in discoveredMachines"
          :key="d.host"
          class="discovered-item"
        >
          <span class="machine-dot online" />
          <span class="discovered-name">{{ d.name }}</span>
          <button class="add-machine-btn" @click="addDiscovered(d)">+ Add</button>
        </div>
      </div>
      <div v-if="scanning" class="fleet-hint">Scanning local network…</div>
      <div v-else-if="!scanning && discoveredMachines.length === 0 && machinesStore.machines.length <= 1" class="fleet-hint">
        Use the scan button above to find servers on your network.
      </div>
    </div>

    <!-- Footer -->
    <div class="sidebar-footer">
      <button
        class="shutdown-btn"
        aria-label="Shut down vllm-mlx-ui"
        :disabled="shuttingDown"
        @click="showShutdownConfirm = true"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13" aria-hidden="true">
          <path fill-rule="evenodd" d="M10 2a1 1 0 011 1v5a1 1 0 11-2 0V3a1 1 0 011-1zm4.22 2.78a1 1 0 011.415 0 8 8 0 11-11.27 0 1 1 0 011.414 1.415 6 6 0 108.44 0 1 1 0 010-1.415z" clip-rule="evenodd" />
        </svg>
        <span>{{ shuttingDown ? 'Shutting down…' : 'Shut Down' }}</span>
      </button>
      <div class="footer-right">
        <span class="footer-version">v{{ serverStore.dashboardVersion ?? '—' }}</span>
        <span class="footer-dot" :class="serverStore.isRunning ? 'running' : 'stopped'" />
      </div>
    </div>

    <ConfirmModal
      v-if="showShutdownConfirm"
      title="Shut Down Dashboard"
      message="This will stop vllm-mlx-ui completely. You'll need to reopen it from the menu bar or terminal."
      confirm-label="Shut Down"
      :destructive="true"
      @confirm="doShutdown"
      @cancel="showShutdownConfirm = false"
    />
  </aside>
</template>

<style scoped>
.sidebar {
  width: 224px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--bd-default);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* Wordmark */
.sidebar-logo {
  padding: var(--space-4) var(--space-4) var(--space-3);
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -.4px;
  line-height: 1;
  flex-shrink: 0;
}
.logo-mark { color: var(--tx-primary); }
.logo-accent { color: var(--si-400); }

/* Sections */
/* Server status row — compact read-only pill; click → /serve */
.sidebar-status-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: none;
  border: none;
  border-bottom: 1px solid var(--bd-subtle);
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  color: var(--tx-secondary);
  flex-shrink: 0;
  transition: background .15s;
}
.sidebar-status-row:hover { background: var(--bg-hover); }
.sidebar-status-row:focus-visible { outline: 2px solid var(--si-400); outline-offset: -2px; }
.status-dot {
  width: 7px;
  height: 7px;
  margin-top: 4px; /* align with first text line */
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.running  { background: var(--si-500); }
.status-dot.stopped  { background: var(--tx-muted); }
/* Two-line stacked engine + model display */
.status-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  gap: 1px;
}
.status-engine {
  font-weight: 600;
  color: var(--tx-primary);
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status-model {
  color: var(--tx-secondary);
  font-size: 11px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-model-none {
  color: var(--tx-muted);
  font-size: 11px;
  font-style: italic;
}

.sidebar-section {
  padding: var(--space-3) var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.section-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  padding: 0 var(--space-1) var(--space-2);
}

/* Machine list */
.machine-list { display: flex; flex-direction: column; gap: 2px; }

.machine-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 5px var(--space-2);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  cursor: pointer;
  color: var(--tx-secondary);
  font-size: var(--text-sm);
  font-family: inherit;
  text-align: left;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.machine-item:hover {
  background: var(--bg-elevated);
}
.machine-item:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: -2px;
}
.machine-item.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
}

.machine-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.machine-dot.online  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.machine-dot.offline { background: var(--g-600); }

.machine-name { flex: 1; font-weight: 500; }
.machine-host { font-size: 13px; color: var(--tx-muted); font-family: var(--font-mono); }

.fleet-section {
  flex-shrink: 0;
  max-height: 220px;
  overflow-y: auto;
}

.fleet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.fleet-header .section-label {
  margin-bottom: 0;
}

.scan-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
  flex-shrink: 0;
}
.scan-btn:hover:not(:disabled) {
  color: var(--tx-secondary);
  border-color: var(--bd-emphasis);
}
.scan-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}
.scan-btn:disabled { opacity: 0.5; cursor: default; }

.scan-spinner {
  display: inline-block;
  width: 9px;
  height: 9px;
  border: 1.5px solid var(--tx-muted);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.discovered-list {
  margin-top: var(--space-2);
  border-top: 1px solid var(--bd-subtle);
  padding-top: var(--space-2);
}

.discovered-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
  padding: 0 var(--space-2);
}

.discovered-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px var(--space-2);
  border-radius: var(--r-sm);
  font-size: 14px;
}

.discovered-name {
  flex: 1;
  font-family: var(--font-mono);
  color: var(--tx-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.add-machine-btn {
  background: transparent;
  border: 1px solid var(--si-600);
  border-radius: var(--r-sm);
  color: var(--si-400);
  font-size: 12px;
  font-family: inherit;
  padding: 2px 7px;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
}
.add-machine-btn:hover {
  background: var(--ac-bg);
  color: var(--si-300);
}
.add-machine-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}

.fleet-hint {
  font-size: 13px;
  color: var(--tx-muted);
  padding: var(--space-1) var(--space-2);
  font-style: italic;
}

/* Arc gauge */
.gauge-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: var(--space-4);
  padding-bottom: var(--space-3);
}

.arc-svg {
  width: 140px;
  height: auto;
  display: block;
}

.arc-fill {
  transition: stroke-dashoffset .5s ease, stroke .3s ease;
}

.gauge-model-name {
  margin-top: var(--space-2);
  font-size: 13px;
  color: var(--tx-tertiary);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
}

.gauge-fits-hint {
  margin-top: var(--space-1);
  font-size: 11px;
  color: var(--tx-muted);
  text-align: center;
}

/* Nav */
.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: var(--space-2) var(--space-2);
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px var(--space-2);
  border-radius: var(--r-md);
  border: 1px solid transparent;
  color: var(--tx-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}
.nav-item:hover {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}
.nav-item:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: -2px;
}
.nav-item.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
}

.nav-item-util { color: var(--tx-tertiary); }
.nav-item-util.active { color: var(--si-300); }

.nav-divider {
  height: 1px;
  background: var(--bd-subtle);
  margin: var(--space-1) var(--space-1);
}

/* Footer */
.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.footer-right {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.footer-version {
  font-size: 13px;
  color: var(--tx-muted);
  font-family: var(--font-mono);
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.release-mem-btn {
  margin-top: var(--space-2);
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-muted);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
}
.release-mem-btn:hover {
  color: var(--tx-secondary);
  border-color: var(--bd-emphasis);
}
.release-mem-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}

.release-mem-msg {
  margin-top: var(--space-1);
  font-size: 12.5px;
  color: var(--si-400);
  text-align: center;
  min-height: 14px;
}

.release-btn {
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  cursor: pointer;
  padding: 3px 5px;
  display: flex;
  align-items: center;
  transition: color var(--transition-fast), border-color var(--transition-fast);
}
.release-btn:hover {
  color: var(--tx-secondary);
  border-color: var(--bd-default);
}

.footer-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.footer-dot.running  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.footer-dot.stopped  { background: var(--g-600); }

/* Responsive: hide sidebar below 720px */
@media (max-width: 720px) {
  .sidebar { display: none; }
}

@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
.update-badge {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--si-400);
  box-shadow: 0 0 0 2px rgba(91, 106, 208, .2);
  flex-shrink: 0;
  margin-left: auto;
  animation: pulse-dot 2.5s ease-in-out infinite;
}

.shutdown-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 6px var(--space-2);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .2);
  border-radius: var(--r-md);
  color: var(--cr-300, #f87171);
  font-size: var(--text-sm);
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
  text-align: left;
}
.shutdown-btn:hover {
  background: rgba(239, 68, 68, .15);
  border-color: rgba(239, 68, 68, .40);
}
.shutdown-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}
.shutdown-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Model Selector */
.model-section {
  padding: var(--space-2) var(--space-3);
}

.model-select {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 4px 8px;
  cursor: pointer;
  transition: border-color var(--transition-fast);
  appearance: auto;
}
.model-select:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}
.model-select:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
  box-shadow: none;
}
.model-select:disabled { opacity: 0.5; cursor: not-allowed; }

.model-switching {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 2px;
}

.switch-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--tx-muted);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  flex-shrink: 0;
}

.switch-text {
  font-size: 13px;
  color: var(--cu-400);
  font-family: var(--font-mono);
}

.manage-models-link {
  display: block;
  margin-top: var(--space-1);
  font-size: 12.5px;
  color: var(--tx-muted);
  text-decoration: none;
  padding: 2px 2px;
  border-radius: var(--r-sm);
  transition: color var(--transition-fast);
}
.manage-models-link:hover { color: var(--si-300); }
.manage-models-link:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 0;
}
</style>
