<!--
  ServeView — inference server control panel.

  Provides:
  - Server start / stop with model and parameter selection
  - Live status metrics: uptime, tokens/s, active requests, memory
  - API endpoint display (base URL + API key)
  - Optimal Settings button: auto-configures parameters based on selected model

  This is the primary landing view (`/` → `/serve`). All parameter changes
  are reflected immediately to the server config via the settings store.
-->
<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import StatusPill from '@/components/shared/StatusPill.vue'
import AppButton from '@/components/shared/AppButton.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import EndpointCard from '@/components/serve/EndpointCard.vue'
import MetricCard from '@/components/serve/MetricCard.vue'
import { api } from '@/api/client'

const router = useRouter()

const serverStore = useServerStore()
const modelsStore = useModelsStore()

interface EngineInfo {
  id: string
  name: string
  installed: boolean
  fixed_model_display?: string | null
  capabilities?: string[]
}

interface NetworkInterface {
  ip: string
  label: string
}
const networkInterfaces = ref<NetworkInterface[]>([])
const copiedUrl = ref<string | null>(null)

// Engine + model selection
const engines = ref<EngineInfo[]>([])
const selectedEngine = ref('')
const engineChanged = computed(() => selectedEngine.value && selectedEngine.value !== serverStore.engineId)
const applyPending = ref(false)

const selectedEngineInfo = computed(() =>
  engines.value.find(e => e.id === selectedEngine.value) ?? null
)
const fixedModelDisplay = computed(() => selectedEngineInfo.value?.fixed_model_display ?? null)

async function fetchEngines() {
  try {
    const r = await api.get<{ engines: EngineInfo[] }>('/engines')
    engines.value = r.engines.filter(e => e.installed)
    if (!selectedEngine.value && serverStore.engineId) {
      selectedEngine.value = serverStore.engineId
    }
  } catch { /* non-critical */ }
}

async function saveEngineAndRestart() {
  applyPending.value = true
  try {
    const updates: Record<string, unknown> = { engine_id: selectedEngine.value }
    // Don't propagate the current model when switching to a fixed-model engine —
    // it would overwrite the engine's own model selection with an unrelated HF repo ID.
    if (serverStore.modelId && !fixedModelDisplay.value) updates.model = serverStore.modelId
    await serverStore.saveConfig(updates as any)
    await serverStore.stopServer()
    await serverStore.startServer()
  } catch { /* error handled by store */ }
  finally { applyPending.value = false }
}

// Clear cache confirms
const confirmClearAll = ref(false)
const confirmClearPrefix = ref(false)
const cacheMsg = ref<string | null>(null)

onMounted(() => {
  modelsStore.fetchModels()
  refreshLogs()
  fetchEngines()
  api.get<NetworkInterface[]>('/network/interfaces').then(r => { networkInterfaces.value = r }).catch(() => { /* non-critical network info */ })
  api.get<{ enabled: boolean }>('/auto_switch_enabled').then(r => { autoSwitchEnabled.value = r.enabled }).catch(() => { /* non-critical auto-switch status */ })
})

// Sync selectedEngine from store when engineId becomes available
watch(() => serverStore.engineId, (val) => {
  if (val && !selectedEngine.value) selectedEngine.value = val
}, { immediate: true })

const status = computed(() => {
  if (serverStore.loading) return 'loading' as const
  if (!serverStore.isRunning) return 'stopped' as const
  return 'running' as const
})

const baseUrl = computed(() => serverStore.baseUrl ?? '—')
const modelId = computed(() => serverStore.modelId ?? '—')

const uptime = computed(() => {
  const secs = serverStore.uptimeSeconds
  if (!secs) return '—'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = Math.floor(secs % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
})

const tps = computed(() => {
  const v = serverStore.tps
  return v !== null ? v.toFixed(1) : '—'
})

const memPct = computed(() => serverStore.memoryPercent.toFixed(0))
const memAvailable = computed(() => serverStore.memory?.available_gb.toFixed(1) ?? '—')
const memTotal = computed(() => serverStore.memory?.total_gb.toFixed(0) ?? '—')

const logs = ref<string[]>([])

async function refreshLogs() {
  logs.value = await serverStore.fetchLogs(200)
}

// Model picker
const switchingModel = ref(false)
const switchError = ref<string | null>(null)

// Show last 20 lines of crash log so the banner stays compact
const crashLogTail = computed(() => {
  const log = serverStore.crashLog
  if (!log) return ''
  const lines = log.split('\n')
  return lines.slice(-20).join('\n')
})

async function handleModelSwitch(e: Event) {
  const target = e.target as HTMLSelectElement
  const newId = target.value
  if (!newId || newId === serverStore.modelId) return

  // Auto-switch engine if the model belongs to a specific engine (e.g. ds4)
  const modelMeta = modelsStore.models.find(m => m.id === newId)
  if (modelMeta?.engine && modelMeta.engine !== selectedEngine.value) {
    selectedEngine.value = modelMeta.engine
    // Engine changed — user must click Apply & Restart; don't also load the model now
    return
  }

  switchingModel.value = true
  switchError.value = null
  try {
    await modelsStore.loadModel(newId)
  } catch (err) {
    switchError.value = String(err)
  } finally {
    switchingModel.value = false
  }
}

// Config edit mode
const editMode = ref(false)
const editPort = ref(8080)
const editContextSize = ref(4096)
const editMaxTokens = ref(2048)
const saveError = ref<string | null>(null)

function enterEditMode() {
  editPort.value = serverStore.config?.port ?? 8080
  editContextSize.value = serverStore.config?.context_size ?? 4096
  editMaxTokens.value = serverStore.config?.max_tokens ?? 2048
  saveError.value = null
  editMode.value = true
}

async function saveConfig() {
  saveError.value = null
  try {
    await serverStore.saveConfig({
      port: editPort.value,
      context_size: editContextSize.value,
      max_tokens: editMaxTokens.value,
    })
    editMode.value = false
  } catch (err) {
    saveError.value = String(err)
  }
}

// Network interfaces
const serverPort = computed(() => serverStore.config?.port ?? 8080)
const serverHost = computed(() => serverStore.config?.host ?? '127.0.0.1')
const localOnly = computed(() => serverHost.value.startsWith('127'))
const mgmtPort = computed(() => {
  if (import.meta.env.DEV) return 8502
  return parseInt(window.location.port || '8502', 10)
})
const autoSwitchEnabled = ref(false)

const allInterfaces = computed<NetworkInterface[]>(() => [
  { ip: 'localhost', label: 'Localhost' },
  ...networkInterfaces.value,
])

function connectionUrl(ip: string) {
  return `http://${ip}:${serverPort.value}/v1`
}

// ── Running status hero ───────────────────────────────────────────────────────
const showHero = computed(() => serverStore.isRunning)
const showEmptyState = computed(() =>
  serverStore.config !== null &&
  !serverStore.isRunning &&
  !serverStore.modelId &&
  !serverStore.loading
)

// Use the engine that IS running (not the picker selection, which may differ)
const activeEngineInfo = computed(() =>
  engines.value.find(e => e.id === serverStore.engineId) ?? null
)
const activeCaps = computed(() => new Set(activeEngineInfo.value?.capabilities ?? []))

const heroModelName = computed(() =>
  serverStore.modelId ??
  activeEngineInfo.value?.fixed_model_display ??
  'Unknown model'
)

// ── Engine-aware endpoints ────────────────────────────────────────────────────
const BASE_PATHS = [
  { tag: 'Base URL',    path: '/v1' },
  { tag: 'Chat',        path: '/v1/chat/completions' },
  { tag: 'Completions', path: '/v1/completions' },
  { tag: 'Models',      path: '/v1/models' },
]

const engineEndpointPaths = computed(() => {
  const paths = [...BASE_PATHS]
  if (activeCaps.value.has('embedding')) {
    paths.push({ tag: 'Embeddings', path: '/v1/embeddings' })
  }
  if (serverStore.engineId?.startsWith('ds4')) {
    paths.push({ tag: 'Responses (OpenAI)', path: '/v1/responses' })
    paths.push({ tag: 'Messages (Claude)',  path: '/v1/messages' })
  }
  // Fall back to showing all common paths if engines haven't loaded yet
  if (!engines.value.length) {
    paths.push({ tag: 'Embeddings', path: '/v1/embeddings' })
  }
  return paths
})

function openAiEndpoints(ip: string) {
  const base = `http://${ip}:${serverPort.value}`
  return engineEndpointPaths.value.map(ep => ({ tag: ep.tag, path: ep.path, url: base + ep.path }))
}

function proxyEndpoints(ip: string) {
  return [
    { tag: 'Base URL', path: '/v1', url: `http://${ip}:${mgmtPort.value}/v1` },
    { tag: 'Chat (auto-switch)', path: '/v1/chat/completions', url: `http://${ip}:${mgmtPort.value}/v1/chat/completions` },
  ]
}

async function copyUrl(url: string) {
  try {
    await navigator.clipboard.writeText(url)
    copiedUrl.value = url
    setTimeout(() => { if (copiedUrl.value === url) copiedUrl.value = null }, 1500)
  } catch {
    // Clipboard unavailable (e.g. non-secure context) — non-critical
  }
}

// Clear cache
async function doClearCache(type: string) {
  confirmClearAll.value = false
  confirmClearPrefix.value = false
  cacheMsg.value = null
  try {
    await serverStore.clearCache(type)
    cacheMsg.value = `${type === 'all' ? 'All cache' : 'Prefix cache'} cleared.`
    setTimeout(() => { cacheMsg.value = null }, 3000)
  } catch {
    cacheMsg.value = 'Clear failed.'
    setTimeout(() => { cacheMsg.value = null }, 3000)
  }
}
</script>

<template>
  <div class="serve-view">
    <!-- Page header -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">Serve</h1>
        <StatusPill :status="status" />
      </div>
      <div class="header-actions">
        <!-- Engine picker -->
        <div class="model-picker-wrap">
          <div class="model-picker-label">Engine</div>
          <div class="model-picker-control">
            <select
              class="model-select"
              v-model="selectedEngine"
              aria-label="Select inference engine"
            >
              <option v-for="e in engines" :key="e.id" :value="e.id">
                {{ e.name }}
              </option>
            </select>
          </div>
        </div>

        <!-- Model picker -->
        <div class="model-picker-wrap">
          <div class="model-picker-label">Model</div>
          <div class="model-picker-control">
            <!-- Fixed-model engines (e.g. ds4-m5): show a static label -->
            <div v-if="fixedModelDisplay" class="model-fixed-label" :title="fixedModelDisplay">
              {{ fixedModelDisplay }}
            </div>
            <template v-else>
              <select
                class="model-select"
                :value="serverStore.modelId ?? ''"
                :disabled="switchingModel"
                aria-label="Select inference model"
                @change="handleModelSwitch"
              >
                <option v-if="!serverStore.modelId" value="" disabled>No model loaded</option>
                <option v-if="serverStore.modelId && !modelsStore.models.find(m => m.id === serverStore.modelId)" :value="serverStore.modelId">
                  {{ serverStore.modelId }}
                </option>
                <option v-for="m in modelsStore.models" :key="m.id" :value="m.id">
                  {{ m.id.split('/').pop() }}
                </option>
              </select>
              <div v-if="switchingModel" class="picker-spinner" />
            </template>
          </div>
        </div>

        <!-- Apply & Restart when engine changes -->
        <AppButton
          v-if="engineChanged"
          variant="primary"
          size="sm"
          :loading="applyPending"
          aria-label="Apply engine change and restart"
          @click="saveEngineAndRestart"
        >⟳ Apply & Restart</AppButton>

        <AppButton
          v-if="!serverStore.isRunning"
          variant="primary"
          size="sm"
          :loading="serverStore.loading"
          aria-label="Start inference server"
          @click="serverStore.startServer()"
        >▶ Start</AppButton>
        <AppButton
          v-else
          variant="secondary"
          size="sm"
          :loading="serverStore.loading"
          aria-label="Stop inference server"
          @click="serverStore.stopServer()"
        >■ Stop</AppButton>
      </div>
    </div>

    <!-- Switch error -->
    <div v-if="switchError" class="error-banner">
      ⚠ {{ switchError }}
      <button class="error-dismiss" @click="switchError = null">✕</button>
    </div>

    <!-- Server crash log -->
    <div v-if="serverStore.crashLog && !serverStore.isRunning" class="crash-banner">
      <div class="crash-header">
        <span>⚠ Server failed to start</span>
        <button class="error-dismiss" @click="serverStore.crashLog = null">✕</button>
      </div>
      <pre class="crash-log">{{ crashLogTail }}</pre>
    </div>

    <!-- Empty state: no model configured yet -->
    <div v-if="showEmptyState" class="serve-empty">
      <div class="serve-empty-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35"/>
          <path d="M8 11h6M11 8v6" />
        </svg>
      </div>
      <h2 class="serve-empty-title">No model loaded</h2>
      <p class="serve-empty-desc">Find and download a model to get started. The Model Finder scores models for your hardware and use case.</p>
      <RouterLink to="/models" class="serve-empty-cta">Browse Models →</RouterLink>
    </div>

    <!-- Running hero: confirms what's active when server is up -->
    <div v-if="showHero" class="serve-hero">
      <div class="hero-model">
        <span class="hero-model-label">Running</span>
        <span class="hero-model-name" :title="heroModelName">{{ heroModelName.split('/').pop() }}</span>
        <span class="hero-engine-badge">{{ serverStore.engineId }}</span>
      </div>
      <div class="hero-stats">
        <div class="hero-stat">
          <span class="hero-stat-value">{{ tps }}</span>
          <span class="hero-stat-label">Tok/s</span>
        </div>
        <div class="hero-stat-divider" />
        <div class="hero-stat">
          <span class="hero-stat-value">{{ uptime }}</span>
          <span class="hero-stat-label">Uptime</span>
        </div>
        <div class="hero-stat-divider" />
        <div class="hero-stat">
          <span class="hero-stat-value">{{ memAvailable }}</span>
          <span class="hero-stat-label">GB free</span>
        </div>
      </div>
    </div>

    <!-- Live metrics — shown first so server state is immediately visible -->
    <section class="page-section">
      <div class="section-label">
        Live Metrics
        <span v-if="serverStore.metricsError && serverStore.isRunning" class="metrics-stale-badge">metrics unavailable</span>
        <span v-if="serverStore.isRunning" class="engine-running-badge">Engine: {{ serverStore.engineId }}</span>
        <button class="view-full-link" @click="router.push('/benchmarks')">View full metrics →</button>
      </div>
      <div class="metrics-grid">
        <MetricCard label="Tokens / sec" :value="tps" />
        <MetricCard label="Available RAM" :value="memAvailable" :unit="`/ ${memTotal} GB`" />
        <MetricCard label="Memory %" :value="memPct" unit="%" :warnAbove="75" isPercent />
        <MetricCard label="Uptime" :value="uptime" />
      </div>
      <div class="release-mem-row">
        <AppButton
          variant="secondary"
          size="sm"
          title="Clears MLX model cache and runs OS-level memory compaction. The running server stays up — model weights remain loaded. Use this to reclaim inactive/cached RAM without restarting."
          aria-label="Release memory"
          @click="serverStore.releaseMemory()"
        >
          ↺ Release Memory
        </AppButton>
        <AppButton variant="secondary" size="sm" aria-label="Clear all cache" @click="confirmClearAll = true">
          🗑 Clear All Cache
        </AppButton>
        <AppButton variant="secondary" size="sm" aria-label="Clear prefix cache" @click="confirmClearPrefix = true">
          🗑 Clear Prefix Cache
        </AppButton>
        <span v-if="cacheMsg" class="cache-msg">{{ cacheMsg }}</span>
      </div>
    </section>

    <!-- Connection Info -->
    <CollapsibleSection title="📡 Connection Info" :defaultOpen="true">
      <div class="conn-body">
        <!-- Quick-copy Base URL and Model ID at the top -->
        <div class="endpoint-grid conn-quick-copy">
          <EndpointCard label="Base URL" :value="baseUrl" copyable :dimWhenEmpty="true" />
          <EndpointCard label="Model ID" :value="modelId" copyable :dimWhenEmpty="true" />
        </div>
        <div v-if="localOnly" class="conn-warning">
          ⚠ Server is only reachable from this Mac. Change listen address in Settings → Network &amp; Access to allow remote connections.
        </div>
        <p class="conn-note">Copy any URL to use with Cursor, Continue, LM Studio, or any OpenAI-compatible client.</p>

        <div v-if="allInterfaces.length" class="conn-ifaces">
          <div v-for="iface in allInterfaces" :key="iface.ip" class="conn-iface-block">
            <div class="conn-iface-label">{{ iface.label }} — {{ iface.ip }}</div>
            <div class="conn-endpoint-table">
              <div
                v-for="ep in openAiEndpoints(iface.ip)"
                :key="ep.path"
                class="conn-endpoint-row"
              >
                <span class="ep-tag">{{ ep.tag }}</span>
                <code class="ep-url">{{ ep.url }}</code>
                <button
                  class="copy-btn"
                  :class="{ copied: copiedUrl === ep.url }"
                  @click="copyUrl(ep.url)"
                >{{ copiedUrl === ep.url ? '✓' : 'Copy' }}</button>
              </div>
            </div>
          </div>
        </div>
        <p v-else class="conn-empty">No network interfaces found.</p>

        <!-- Proxy endpoints for auto-switch -->
        <div v-if="allInterfaces.length" class="conn-proxy-section">
          <div class="conn-proxy-header">
            <span class="conn-proxy-title">Via Dashboard Proxy</span>
            <span class="conn-proxy-badge" :class="autoSwitchEnabled ? 'proxy-on' : 'proxy-off'">
              Auto-switch {{ autoSwitchEnabled ? 'ON' : 'OFF' }}
            </span>
          </div>
          <p class="conn-proxy-note">Use these URLs if you want automatic model switching — when a client requests a different model it will be loaded automatically and the client notified. Enable in Settings → Network &amp; Access → Auto Model Switch.</p>
          <div v-for="iface in allInterfaces" :key="'proxy-'+iface.ip" class="conn-iface-block">
            <div class="conn-iface-label">{{ iface.label }} — {{ iface.ip }}</div>
            <div class="conn-endpoint-table">
              <div
                v-for="ep in proxyEndpoints(iface.ip)"
                :key="ep.path"
                class="conn-endpoint-row"
              >
                <span class="ep-tag">{{ ep.tag }}</span>
                <code class="ep-url">{{ ep.url }}</code>
                <button
                  class="copy-btn"
                  :class="{ copied: copiedUrl === ep.url }"
                  @click="copyUrl(ep.url)"
                >{{ copiedUrl === ep.url ? '✓' : 'Copy' }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </CollapsibleSection>

    <!-- Server Configuration -->
    <CollapsibleSection title="Server Configuration">
      <div class="config-body">
        <div v-if="saveError" class="error-banner" style="margin-bottom: var(--space-3)">
          ⚠ {{ saveError }}
          <button class="error-dismiss" @click="saveError = null">✕</button>
        </div>
        <div class="config-row">
          <span class="config-label">Model</span>
          <span class="config-value mono">{{ serverStore.config?.model ?? '—' }}</span>
        </div>
        <div class="config-row">
          <span class="config-label">Port</span>
          <span v-if="!editMode" class="config-value mono">{{ serverStore.config?.port ?? 8080 }}</span>
          <input v-else v-model.number="editPort" type="number" class="config-input" />
        </div>
        <div class="config-row">
          <span class="config-label">Context size</span>
          <span v-if="!editMode" class="config-value mono">{{ serverStore.config?.context_size ?? '—' }}</span>
          <input v-else v-model.number="editContextSize" type="number" class="config-input" />
        </div>
        <div class="config-row">
          <span class="config-label">Max tokens</span>
          <span v-if="!editMode" class="config-value mono">{{ serverStore.config?.max_tokens ?? '—' }}</span>
          <input v-else v-model.number="editMaxTokens" type="number" class="config-input" />
        </div>
        <div class="config-actions">
          <AppButton v-if="!editMode" variant="ghost" size="sm" @click="enterEditMode">Edit</AppButton>
          <template v-else>
            <AppButton variant="ghost" size="sm" @click="editMode = false; saveError = null">Cancel</AppButton>
            <AppButton variant="primary" size="sm" @click="saveConfig">Save</AppButton>
          </template>
        </div>
      </div>
    </CollapsibleSection>

    <!-- Server Logs -->
    <CollapsibleSection title="Server Logs" :defaultOpen="false">
      <div class="logs-body">
        <pre v-if="logs.length" class="logs-pre">{{ logs.join('\n') }}</pre>
        <p v-else class="logs-empty">No log output yet.</p>
        <AppButton variant="ghost" size="sm" @click="refreshLogs" style="margin-top: var(--space-2)">↻ Refresh</AppButton>
      </div>
    </CollapsibleSection>

    <ConfirmModal
      v-if="confirmClearAll"
      title="Clear All Cache"
      message="This will clear the full KV cache. Running requests may be affected."
      confirm-label="Clear"
      :destructive="true"
      @confirm="doClearCache('all')"
      @cancel="confirmClearAll = false"
    />
    <ConfirmModal
      v-if="confirmClearPrefix"
      title="Clear Prefix Cache"
      message="This will clear the prefix (prompt) cache only."
      confirm-label="Clear"
      :destructive="true"
      @confirm="doClearCache('prefix')"
      @cancel="confirmClearPrefix = false"
    />
  </div>
</template>

<style scoped>
.serve-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 960px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.header-actions {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
}

/* Align the AppButton vertically with the model select */
.header-actions > :deep(.app-btn) {
  align-self: flex-end;
  margin-bottom: 1px;
}

.page-title {
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -.3px;
  color: var(--tx-primary);
}

.page-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--si-400);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.section-label::before {
  content: '';
  display: block;
  width: 3px;
  height: 11px;
  background: var(--si-500);
  border-radius: 2px;
  flex-shrink: 0;
}

/* Shown when /metrics fetch fails while server is running */
.metrics-stale-badge {
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
  color: #f97316;
  background: rgba(249, 115, 22, 0.10);
  border: 1px solid rgba(249, 115, 22, 0.25);
  border-radius: var(--r-pill);
  padding: 1px 7px;
}

.engine-running-badge {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: #fb923c;
  background: rgba(251, 146, 60, 0.10);
  border: 1px solid rgba(251, 146, 60, 0.25);
  border-radius: var(--r-pill);
  padding: 1px 7px;
}

.view-full-link {
  margin-left: auto;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
  color: var(--tx-muted);
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  padding: 2px 6px;
  border-radius: var(--r-md);
  transition: color var(--transition-fast);
}
.view-full-link:hover { color: var(--tx-secondary); }
.view-full-link:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}

.endpoint-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}
@media (max-width: 720px) { .endpoint-grid { grid-template-columns: 1fr; } }

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}
@media (max-width: 1000px) { .metrics-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px)  { .metrics-grid { grid-template-columns: 1fr; } }

/* Config section */
.config-body {
  display: flex;
  flex-direction: column;
  gap: 0;
  max-width: 520px;
}

.config-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: var(--space-4);
  align-items: center;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--bd-subtle);
}
.config-row:last-of-type { border-bottom: none; }

.config-label {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
}

.config-value {
  font-size: var(--text-sm);
  color: var(--tx-primary);
}
.config-value.mono {
  font-family: var(--font-mono);
  font-size: 14.5px;
}

.config-note {
  font-size: 14px;
  color: var(--tx-muted);
  font-style: italic;
  padding-top: var(--space-2);
}

/* Model picker */
.model-picker-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.model-picker-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.model-picker-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.model-select {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 14px;
  padding: 5px 28px 5px 10px;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7280'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  cursor: pointer;
  transition: border-color var(--transition-fast);
  min-width: 200px;
  max-width: 320px;
}

.model-fixed-label {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 14px;
  padding: 5px 10px;
  min-width: 200px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.85;
  cursor: default;
}

.model-select:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.model-select:disabled { opacity: 0.6; cursor: not-allowed; }

@keyframes spin { to { transform: rotate(360deg); } }
.picker-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--bd-emphasis);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin .6s linear infinite;
  flex-shrink: 0;
}

.config-actions {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
  padding-top: var(--space-3);
}

.config-input {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 14.5px;
  padding: 4px 8px;
  width: 120px;
  transition: border-color var(--transition-fast);
}
.config-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.release-mem-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding-top: var(--space-2);
}

.cache-msg {
  font-size: 14px;
  color: var(--si-300);
}

/* Connection info */
.conn-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-1) 0;
}

.conn-quick-copy {
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
}

.conn-warning {
  padding: var(--space-2) var(--space-3);
  background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.25);
  border-radius: var(--r-md);
  font-size: 14px;
  color: var(--cu-400);
}

.conn-note {
  font-size: 14px;
  color: var(--tx-muted);
}

/* Per-interface block */
.conn-ifaces {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.conn-iface-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.conn-iface-label {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--si-400);
}

/* Endpoint table */
.conn-endpoint-table {
  background: var(--bg-canvas);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.conn-endpoint-row {
  display: grid;
  grid-template-columns: 120px 1fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
}
.conn-endpoint-row:last-child { border-bottom: none; }

.ep-tag {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tx-muted);
  white-space: nowrap;
}

.ep-url {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.copy-btn {
  padding: 3px 10px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  font-size: 13px;
  font-family: inherit;
  color: var(--tx-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
  flex-shrink: 0;
}
.copy-btn:hover { border-color: var(--bd-emphasis); color: var(--tx-primary); }
.copy-btn.copied { color: var(--ph-400); border-color: rgba(74,222,128,.3); }
.copy-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}

.conn-empty { font-size: 14px; color: var(--tx-muted); font-style: italic; }

/* Proxy section */
.conn-proxy-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--bd-subtle);
  margin-top: var(--space-2);
}

.conn-proxy-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.conn-proxy-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.conn-proxy-badge {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .05em;
  padding: 2px 8px;
  border-radius: var(--r-pill);
}
.proxy-on { color: var(--ph-400); background: rgba(74,222,128,.10); border: 1px solid rgba(74,222,128,.25); }
.proxy-off { color: var(--tx-muted); background: var(--bg-elevated); border: 1px solid var(--bd-subtle); }

.conn-proxy-note {
  font-size: 13.5px;
  color: var(--tx-muted);
  line-height: 1.5;
}

/* Error banner */
.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--cr-300);
}

.error-dismiss {
  background: none;
  border: none;
  color: var(--cr-300);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  opacity: 0.7;
}
.error-dismiss:hover { opacity: 1; }

/* Crash log banner */
.crash-banner {
  border: 1px solid rgba(239,68,68,.3);
  border-radius: var(--r-md);
  background: rgba(239,68,68,.06);
  overflow: hidden;
}
.crash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--cr-300);
}
.crash-log {
  margin: 0;
  padding: var(--space-2) var(--space-4) var(--space-3);
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid rgba(239,68,68,.15);
  max-height: 220px;
  overflow-y: auto;
}

/* Logs */
.logs-body { min-height: 80px; }
.logs-empty {
  font-size: 14px;
  color: var(--tx-muted);
  font-style: italic;
}
.logs-pre {
  font-family: var(--font-mono);
  font-size: 13.5px;
  color: var(--tx-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.55;
  max-height: 300px;
  overflow-y: auto;
  background: var(--bg-canvas);
  border-radius: var(--r-md);
  padding: var(--space-3);
}

/* Empty state: no model configured */
.serve-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-8) var(--space-6);
  text-align: center;
  border: 1px dashed var(--bd-emphasis);
  border-radius: var(--r-xl);
  background: var(--bg-elevated);
}
.serve-empty-icon {
  color: var(--tx-muted);
  opacity: 0.6;
}
.serve-empty-title {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--tx-primary);
  margin: 0;
}
.serve-empty-desc {
  font-size: 15px;
  color: var(--tx-secondary);
  max-width: 420px;
  line-height: 1.55;
  margin: 0;
}
.serve-empty-cta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 9px 20px;
  background: var(--si-500);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  border-radius: var(--r-md);
  text-decoration: none;
  transition: background var(--transition-fast), transform var(--transition-fast);
}
.serve-empty-cta:hover {
  background: var(--si-600, var(--si-500));
  transform: translateY(-1px);
}
.serve-empty-cta:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 3px;
}

/* Running hero */
.serve-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: color-mix(in srgb, var(--si-500) 8%, var(--bg-elevated));
  border: 1px solid color-mix(in srgb, var(--si-500) 25%, var(--bd-default));
  border-radius: var(--r-xl);
  flex-wrap: wrap;
}
.hero-model {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.hero-model-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--ph-400);
  white-space: nowrap;
}
.hero-model-name {
  font-size: 15px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 360px;
}
.hero-engine-badge {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  background: var(--bg-canvas);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  color: var(--tx-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}
.hero-stats {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}
.hero-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.hero-stat-value {
  font-size: 18px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--tx-primary);
  line-height: 1;
}
.hero-stat-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}
.hero-stat-divider {
  width: 1px;
  height: 32px;
  background: var(--bd-subtle);
}
@media (max-width: 640px) {
  .serve-hero { flex-direction: column; align-items: flex-start; }
  .hero-model-name { max-width: 240px; }
}

</style>
