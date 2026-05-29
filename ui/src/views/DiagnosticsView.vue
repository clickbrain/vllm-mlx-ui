<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
  DiagnosticsView — Request diagnostics and performance analysis.

  Shows a live-refreshing table of all proxied requests (chat, completions)
  with stream mode, latency, TPS, and source. Helps identify performance
  differences between clients (e.g. streaming vs non-streaming apps).
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'

interface RequestRecord {
  ts: number
  start: number
  time: string
  ttft_ms: number | null
  duration_ms: number
  proxy_overhead_ms: number | null
  completion_tokens: number
  tps: number
  model: string
  stream: boolean
  user_agent: string
  client_ip: string
}

const records = ref<RequestRecord[]>([])
const loading = ref(true)
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

function sourceLabel(ua: string): string {
  if (!ua) return 'Unknown'
  const u = ua.toLowerCase()
  if (u.includes('kilroy')) return 'Kilroy'
  if (u.includes('mozilla') || u.includes('chrome') || u.includes('safari')) return 'Browser'
  if (u.includes('python-httpx') || u.includes('python-requests')) return 'Python'
  if (u.includes('curl')) return 'curl'
  if (u.includes('openai')) return 'OpenAI SDK'
  // Short display of anything else
  const trimmed = ua.split('/')[0].split(' ')[0]
  return trimmed.length > 20 ? trimmed.slice(0, 20) + '…' : trimmed || 'Unknown'
}

function modelShort(model: string): string {
  if (!model) return '—'
  // Show last segment of HF-style "org/model-name"
  const parts = model.split('/')
  const name = parts[parts.length - 1]
  return name.length > 28 ? name.slice(0, 28) + '…' : name
}

function fmtDuration(ms: number): string {
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

async function fetchRecords() {
  try {
    const data = await api.get<{ count: number; requests: RequestRecord[] }>('/debug/requests?n=100')
    // Newest first
    records.value = [...(data.requests || [])].reverse()
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || 'Failed to fetch diagnostics'
  } finally {
    loading.value = false
  }
}

// Per-source averages for the summary row
const sourceStats = computed(() => {
  const map: Record<string, { count: number; totalTps: number; streaming: number; nonStreaming: number }> = {}
  for (const r of records.value) {
    const src = sourceLabel(r.user_agent)
    if (!map[src]) map[src] = { count: 0, totalTps: 0, streaming: 0, nonStreaming: 0 }
    map[src].count++
    map[src].totalTps += r.tps || 0
    if (r.stream) map[src].streaming++
    else map[src].nonStreaming++
  }
  return Object.entries(map).map(([source, s]) => ({
    source,
    count: s.count,
    avgTps: s.count ? +(s.totalTps / s.count).toFixed(1) : 0,
    streamingPct: s.count ? Math.round(s.streaming / s.count * 100) : 0,
    nonStreaming: s.nonStreaming,
  })).sort((a, b) => b.count - a.count)
})

const hasNonStreaming = computed(() => records.value.some(r => !r.stream))

onMounted(() => {
  fetchRecords()
  pollTimer = setInterval(fetchRecords, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="diag-page">
    <div class="diag-header">
      <h1 class="diag-title">Request Diagnostics</h1>
      <p class="diag-subtitle">Live log of all proxied inference requests. Refreshes every 5 s.</p>
    </div>

    <!-- Non-streaming warning -->
    <div v-if="hasNonStreaming" class="diag-warning">
      <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <div>
        <strong>Non-streaming requests detected.</strong>
        Clients using <code>stream: false</code> must wait for <em>all</em> tokens before getting any response —
        this is the most common cause of perceived slowness. Enable streaming in Kilroy for immediate token delivery.
      </div>
    </div>

    <!-- Summary table by source -->
    <div v-if="sourceStats.length" class="diag-section">
      <h2 class="diag-section-title">Summary by Source</h2>
      <div class="diag-table-wrap">
        <table class="diag-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Requests</th>
              <th>Avg TPS</th>
              <th>Streaming</th>
              <th>Non-streaming</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sourceStats" :key="s.source">
              <td class="source-cell">{{ s.source }}</td>
              <td>{{ s.count }}</td>
              <td>{{ s.avgTps }}</td>
              <td>
                <span v-if="s.streamingPct > 0" class="badge badge-stream">{{ s.streamingPct }}%</span>
                <span v-else class="tx-muted">—</span>
              </td>
              <td>
                <span v-if="s.nonStreaming > 0" class="badge badge-nostream">{{ s.nonStreaming }}</span>
                <span v-else class="tx-muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Per-request log -->
    <div class="diag-section">
      <h2 class="diag-section-title">Recent Requests</h2>

      <div v-if="loading" class="diag-empty">Loading…</div>
      <div v-else-if="error" class="diag-error">{{ error }}</div>
      <div v-else-if="!records.length" class="diag-empty">
        No requests recorded yet. Make a request from Kilroy or the built-in chat to see data here.
      </div>

      <div v-else class="diag-table-wrap">
        <table class="diag-table diag-table-detail">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Model</th>
              <th title="Whether the client used stream:true or stream:false">Mode</th>
              <th title="Time to first token (streaming only)">TTFT</th>
              <th title="Total generation duration">Duration</th>
              <th title="Tokens per second">TPS</th>
              <th title="Proxy overhead before forwarding to inference engine">Proxy</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in records" :key="r.ts + '-' + i" :class="{ 'row-nostream': !r.stream }">
              <td class="time-cell">{{ r.time }}</td>
              <td class="source-cell">{{ sourceLabel(r.user_agent) }}</td>
              <td class="model-cell" :title="r.model">{{ modelShort(r.model) }}</td>
              <td>
                <span :class="r.stream ? 'badge badge-stream' : 'badge badge-nostream'">
                  {{ r.stream ? 'stream' : 'batch' }}
                </span>
              </td>
              <td>{{ r.ttft_ms != null ? r.ttft_ms + 'ms' : '—' }}</td>
              <td>{{ fmtDuration(r.duration_ms) }}</td>
              <td>{{ r.tps }}</td>
              <td>{{ r.proxy_overhead_ms != null ? Math.round(r.proxy_overhead_ms) + 'ms' : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- How to read this -->
    <div class="diag-section diag-help">
      <h2 class="diag-section-title">How to Read This</h2>
      <dl class="help-dl">
        <dt><span class="badge badge-stream">stream</span></dt>
        <dd>Client receives tokens <em>as they are generated</em>. Fast perceived response.</dd>

        <dt><span class="badge badge-nostream">batch</span></dt>
        <dd>Client waits for ALL tokens before getting anything. Appears frozen until complete. Enable <code>"stream": true</code> in Kilroy API calls to fix this.</dd>

        <dt>TTFT</dt>
        <dd>Time to first token — how long until the model starts producing output. High TTFT usually means a large prompt or cold model.</dd>

        <dt>TPS</dt>
        <dd>Tokens per second — actual generation throughput. Should be similar across clients if hardware isn't the bottleneck.</dd>

        <dt>Proxy</dt>
        <dd>Milliseconds spent in the dashboard proxy before forwarding to the inference engine. Should be under 10ms normally.</dd>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.diag-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.diag-header { }
.diag-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--tx-primary);
  margin: 0 0 0.25rem;
}
.diag-subtitle {
  font-size: 0.8125rem;
  color: var(--tx-secondary);
  margin: 0;
}

.diag-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  background: color-mix(in srgb, #f59e0b 12%, transparent);
  border: 1px solid color-mix(in srgb, #f59e0b 35%, transparent);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.8125rem;
  color: var(--tx-primary);
  line-height: 1.5;
}
.diag-warning svg { flex-shrink: 0; color: #f59e0b; margin-top: 1px; }
.diag-warning strong { display: block; margin-bottom: 0.25rem; }
.diag-warning code { background: var(--bg-elevated); padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.875em; }

.diag-section {
  background: var(--bg-surface);
  border: 1px solid var(--bd);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
.diag-section-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--tx-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 0.875rem;
}

.diag-table-wrap {
  overflow-x: auto;
}
.diag-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}
.diag-table th {
  text-align: left;
  color: var(--tx-tertiary);
  font-weight: 500;
  padding: 0.375rem 0.75rem;
  border-bottom: 1px solid var(--bd);
  white-space: nowrap;
}
.diag-table td {
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
  color: var(--tx-primary);
  white-space: nowrap;
}
.diag-table tr:last-child td { border-bottom: none; }
.diag-table-detail tbody tr:hover td { background: var(--bg-elevated); }
.row-nostream td { background: color-mix(in srgb, #f59e0b 4%, transparent); }
.row-nostream:hover td { background: color-mix(in srgb, #f59e0b 8%, transparent) !important; }

.time-cell { color: var(--tx-tertiary); font-variant-numeric: tabular-nums; }
.source-cell { font-weight: 500; }
.model-cell { color: var(--tx-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }

.badge {
  display: inline-block;
  padding: 0.1em 0.5em;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.03em;
}
.badge-stream {
  background: color-mix(in srgb, #22c55e 18%, transparent);
  color: #4ade80;
  border: 1px solid color-mix(in srgb, #22c55e 30%, transparent);
}
.badge-nostream {
  background: color-mix(in srgb, #f59e0b 18%, transparent);
  color: #fbbf24;
  border: 1px solid color-mix(in srgb, #f59e0b 30%, transparent);
}

.tx-muted { color: var(--tx-muted); }

.diag-empty, .diag-error {
  font-size: 0.8125rem;
  color: var(--tx-secondary);
  padding: 1rem 0;
  text-align: center;
}
.diag-error { color: #f87171; }

.diag-help .help-dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.5rem 1rem;
  font-size: 0.8125rem;
  margin: 0;
}
.diag-help dt { display: flex; align-items: center; font-weight: 600; color: var(--tx-secondary); }
.diag-help dd { margin: 0; color: var(--tx-secondary); line-height: 1.5; }
.diag-help code { background: var(--bg-elevated); padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.875em; color: var(--tx-primary); }
</style>
