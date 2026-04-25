<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import StatusPill from '@/components/shared/StatusPill.vue'
import AppButton from '@/components/shared/AppButton.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import EndpointCard from '@/components/serve/EndpointCard.vue'
import MetricCard from '@/components/serve/MetricCard.vue'

const serverStore = useServerStore()
const modelsStore = useModelsStore()
let stopPolling: (() => void) | null = null

onMounted(() => {
  stopPolling = serverStore.startPolling()
  modelsStore.fetchModels()
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
    </section>

    <!-- Server Configuration -->
    <CollapsibleSection title="Server Configuration">
      <div class="config-body">
        <div class="config-row">
          <span class="config-label">Model</span>
          <span class="config-value mono">{{ serverStore.config?.model ?? '—' }}</span>
        </div>
        <div class="config-row">
          <span class="config-label">Port</span>
          <span class="config-value mono">{{ serverStore.config?.port ?? 8080 }}</span>
        </div>
        <div class="config-row">
          <span class="config-label">Context size</span>
          <span class="config-value mono">{{ serverStore.config?.context_size ?? '—' }}</span>
        </div>
        <div class="config-row">
          <span class="config-label">Max tokens</span>
          <span class="config-value mono">{{ serverStore.config?.max_tokens ?? '—' }}</span>
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
  gap: var(--space-2);
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
.header-actions {
  align-items: center;
}

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
