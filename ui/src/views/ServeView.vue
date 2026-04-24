<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useServerStore } from '@/stores/server'
import StatusPill from '@/components/shared/StatusPill.vue'
import AppButton from '@/components/shared/AppButton.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import EndpointCard from '@/components/serve/EndpointCard.vue'
import MetricCard from '@/components/serve/MetricCard.vue'

const serverStore = useServerStore()
let stopPolling: (() => void) | null = null

onMounted(() => { stopPolling = serverStore.startPolling() })
onUnmounted(() => { stopPolling?.() })

const status = computed(() => {
  if (serverStore.loading) return 'loading' as const
  if (!serverStore.isRunning) return 'stopped' as const
  return 'running' as const
})

const baseUrl = computed(() => {
  const s = serverStore.status
  return s?.running ? 'http://localhost:8080/v1' : '—'
})

const modelId = computed(() => serverStore.status?.model ?? '—')

const uptime = computed(() => {
  const secs = serverStore.status?.uptime
  if (!secs) return '—'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = Math.floor(secs % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
})

const tps = computed(() => {
  const v = serverStore.status?.tokens_per_sec
  return v !== undefined ? v.toFixed(1) : '—'
})

const memPct = computed(() => serverStore.memoryPercent.toFixed(0))
const memUsed = computed(() => serverStore.memory?.used_gb.toFixed(1) ?? '—')
const memTotal = computed(() => serverStore.memory?.total_gb.toFixed(0) ?? '—')
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
          <span class="config-value mono">{{ modelId }}</span>
        </div>
        <div class="config-row">
          <span class="config-label">Port</span>
          <span class="config-value mono">8080</span>
        </div>
        <div class="config-row">
          <span class="config-label">GPU memory fraction</span>
          <span class="config-value mono">0.90</span>
        </div>
        <p class="config-note">Full configuration editor coming next — edit via the Models → Library tab or CLI for now.</p>
      </div>
    </CollapsibleSection>

    <!-- Server Logs -->
    <CollapsibleSection title="Server Logs">
      <div class="logs-body">
        <p class="logs-empty">Server log stream will appear here once the server is running.</p>
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
  color: var(--tx-muted);
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
  gap: var(--space-3);
}

.config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) 0;
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

/* Logs */
.logs-body { min-height: 80px; }
.logs-empty {
  font-size: 12px;
  color: var(--tx-muted);
  font-style: italic;
}
</style>
