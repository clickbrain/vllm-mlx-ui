<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import StatusPill from '@/components/shared/StatusPill.vue'
import AppButton from '@/components/shared/AppButton.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import EndpointCard from '@/components/serve/EndpointCard.vue'
import MetricCard from '@/components/serve/MetricCard.vue'
import { api } from '@/api/client'

const serverStore = useServerStore()
const modelsStore = useModelsStore()
let stopPolling: (() => void) | null = null

interface NetworkInterface {
  ip: string
  label: string
}
const networkInterfaces = ref<NetworkInterface[]>([])
const copiedUrl = ref<string | null>(null)

// Clear cache confirms
const confirmClearAll = ref(false)
const confirmClearPrefix = ref(false)
const cacheMsg = ref<string | null>(null)

onMounted(() => {
  stopPolling = serverStore.startPolling()
  modelsStore.fetchModels()
  refreshLogs()
  api.get<NetworkInterface[]>('/network/interfaces').then(r => { networkInterfaces.value = r }).catch(() => {})
})
onUnmounted(() => { stopPolling?.() })

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
const memUsed = computed(() => serverStore.memory?.used_gb.toFixed(1) ?? '—')
const memTotal = computed(() => serverStore.memory?.total_gb.toFixed(0) ?? '—')

const logs = ref<string[]>([])

async function refreshLogs() {
  logs.value = await serverStore.fetchLogs(200)
}

// Model picker
const switchingModel = ref(false)
const switchError = ref<string | null>(null)

async function handleModelSwitch(e: Event) {
  const target = e.target as HTMLSelectElement
  const newId = target.value
  if (!newId || newId === serverStore.modelId) return
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

function connectionUrl(ip: string) {
  return `http://${ip}:${serverPort.value}/v1`
}

const OPENAI_PATHS = [
  { tag: 'Base URL',         path: '/v1' },
  { tag: 'Chat',             path: '/v1/chat/completions' },
  { tag: 'Completions',      path: '/v1/completions' },
  { tag: 'Models',           path: '/v1/models' },
  { tag: 'Embeddings',       path: '/v1/embeddings' },
]

function openAiEndpoints(ip: string) {
  const base = `http://${ip}:${serverPort.value}`
  return OPENAI_PATHS.map(ep => ({ tag: ep.tag, path: ep.path, url: base + ep.path }))
}

async function copyUrl(url: string) {
  try {
    await navigator.clipboard.writeText(url)
    copiedUrl.value = url
    setTimeout(() => { if (copiedUrl.value === url) copiedUrl.value = null }, 1500)
  } catch { /* silent */ }
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
        <!-- Model picker -->
        <div class="model-picker-wrap">
          <div class="model-picker-label">Model</div>
          <div class="model-picker-control">
            <select
              class="model-select"
              :value="serverStore.modelId ?? ''"
              :disabled="switchingModel"
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
          </div>
        </div>

        <AppButton
          v-if="!serverStore.isRunning"
          variant="primary"
          size="sm"
          :loading="serverStore.loading"
          @click="serverStore.startServer()"
        >▶ Start</AppButton>
        <AppButton
          v-else
          variant="secondary"
          size="sm"
          :loading="serverStore.loading"
          @click="serverStore.stopServer()"
        >■ Stop</AppButton>
      </div>
    </div>

    <!-- Switch error -->
    <div v-if="switchError" class="error-banner">
      ⚠ {{ switchError }}
      <button class="error-dismiss" @click="switchError = null">✕</button>
    </div>

    <!-- Connection endpoints -->
    <section class="page-section">
      <div class="section-label">Connection</div>
      <div class="endpoint-grid">
        <EndpointCard label="Base URL" :value="baseUrl" copyable :dimWhenEmpty="true" />
        <EndpointCard label="Model ID" :value="modelId" copyable :dimWhenEmpty="true" />
      </div>
    </section>

    <!-- Live metrics -->
    <section class="page-section">
      <div class="section-label">Live Metrics</div>
      <div class="metrics-grid">
        <MetricCard label="Tokens / sec" :value="tps" />
        <MetricCard label="Memory Used" :value="memUsed" :unit="`/ ${memTotal} GB`" />
        <MetricCard label="Memory %" :value="memPct" unit="%" :warnAbove="75" isPercent />
        <MetricCard label="Uptime" :value="uptime" />
      </div>
      <div class="release-mem-row">
        <AppButton variant="secondary" size="sm" @click="serverStore.releaseMemory()">
          ↺ Release Memory
        </AppButton>
        <AppButton variant="secondary" size="sm" @click="confirmClearAll = true">
          🗑 Clear All Cache
        </AppButton>
        <AppButton variant="secondary" size="sm" @click="confirmClearPrefix = true">
          🗑 Clear Prefix Cache
        </AppButton>
        <span v-if="cacheMsg" class="cache-msg">{{ cacheMsg }}</span>
      </div>
    </section>

    <!-- Connection Info -->
    <CollapsibleSection title="📡 Connection Info" :defaultOpen="true">
      <div class="conn-body">
        <div v-if="localOnly" class="conn-warning">
          ⚠ Server is only reachable from this Mac. Change listen address in Settings → Network &amp; Access to allow remote connections.
        </div>
        <p class="conn-note">Copy any URL to use with Cursor, Continue, LM Studio, or any OpenAI-compatible client.</p>

        <div v-if="networkInterfaces.length" class="conn-ifaces">
          <div v-for="iface in networkInterfaces" :key="iface.ip" class="conn-iface-block">
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
  font-size: 10px;
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
  font-size: 12.5px;
}

.config-note {
  font-size: 12px;
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
  font-size: 10px;
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
  font-size: 12px;
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
  font-size: 12.5px;
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
  font-size: 12px;
  color: var(--si-300);
}

/* Connection info */
.conn-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-1) 0;
}

.conn-warning {
  padding: var(--space-2) var(--space-3);
  background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.25);
  border-radius: var(--r-md);
  font-size: 12px;
  color: var(--cu-400);
}

.conn-note {
  font-size: 12px;
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
  font-size: 11px;
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
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tx-muted);
  white-space: nowrap;
}

.ep-url {
  font-family: var(--font-mono);
  font-size: 12px;
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
  font-size: 11px;
  font-family: inherit;
  color: var(--tx-secondary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
  flex-shrink: 0;
}
.copy-btn:hover { border-color: var(--bd-emphasis); color: var(--tx-primary); }
.copy-btn.copied { color: var(--ph-400); border-color: rgba(74,222,128,.3); }

.conn-empty { font-size: 12px; color: var(--tx-muted); font-style: italic; }

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
  font-size: 14px;
  padding: 0 2px;
  opacity: 0.7;
}
.error-dismiss:hover { opacity: 1; }

/* Logs */
.logs-body { min-height: 80px; }
.logs-empty {
  font-size: 12px;
  color: var(--tx-muted);
  font-style: italic;
}
.logs-pre {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--tx-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.55;
  max-height: 320px;
  overflow-y: auto;
  background: var(--bg-canvas);
  border-radius: var(--r-sm);
  padding: var(--space-3);
}
</style>
