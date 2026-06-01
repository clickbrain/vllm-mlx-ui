<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
  DiagnosticsView — Full system monitoring: engine status + request log.

  Engine panel: Metal memory, active TPS, KV cache hit rate, running requests.
  Request log: per-request timing, OOM detection, TPS color-coding, model swap.
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
  prompt_tokens: number
  msg_count: number
  max_tokens: number
  model_swap: boolean
  oom_likely: boolean
  tps: number
  model: string
  stream: boolean
  user_agent: string
  client_ip: string
}

interface EngineRequest {
  request_id: string
  status: string
  phase: string
  elapsed_s: number
  prompt_tokens: number
  completion_tokens: number
  max_tokens: number
  progress: number
  tokens_per_second: number
  ttft_s: number
  cache_hit_type: string
}

interface EngineStatus {
  status?: string
  model?: string
  uptime_s?: number
  num_running?: number
  num_waiting?: number
  total_requests_processed?: number
  generation_tps?: number
  metal?: { active_memory_gb: number; peak_memory_gb: number; cache_memory_gb: number }
  cache?: { hits: number; misses: number; hit_rate: number; evictions: number; current_memory_mb: number; max_memory_mb: number; memory_utilization: number }
  requests?: EngineRequest[]
  error?: string
  external?: boolean
  base_url?: string
  no_detailed_status?: boolean
}

const records = ref<RequestRecord[]>([])
const engineStatus = ref<EngineStatus | null>(null)
const loading = ref(true)
const engineLoading = ref(true)
const error = ref('')
const clearing = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null
let engineTimer: ReturnType<typeof setInterval> | null = null

// Only show requests that look like real production traffic
// (filter out test/dev entries with empty user_agent or junk model names)
const filteredRecords = computed(() =>
  records.value.filter(r => r.user_agent || r.completion_tokens > 0 || r.duration_ms > 200)
)

function sourceLabel(ua: string): string {
  if (!ua) return 'Internal'
  const u = ua.toLowerCase()
  if (u.includes('kilroy')) return 'Kilroy'
  if (u.includes('mozilla') || u.includes('chrome') || u.includes('safari')) return 'Browser'
  if (u.includes('python-httpx') || u.includes('python-requests')) return 'Python'
  if (u.includes('curl')) return 'curl'
  if (u.includes('openai')) return 'OpenAI SDK'
  const trimmed = ua.split('/')[0].split(' ')[0]
  return trimmed.length > 20 ? trimmed.slice(0, 20) + '…' : trimmed || 'Internal'
}

function modelShort(model: string): string {
  if (!model) return '—'
  const parts = model.split('/')
  const name = parts[parts.length - 1]
  return name.length > 28 ? name.slice(0, 28) + '…' : name
}

function fmtDuration(ms: number): string {
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function tpsColor(tps: number): string {
  if (tps <= 0) return ''
  if (tps < 5) return 'tps-low'
  if (tps < 15) return 'tps-mid'
  return 'tps-ok'
}

function memBarPct(used: number, total: number): number {
  return total > 0 ? Math.min(100, (used / total) * 100) : 0
}

function memBarColor(pct: number): string {
  if (pct > 90) return '#ef4444'
  if (pct > 70) return '#f59e0b'
  return '#4ade80'
}

async function fetchRecords() {
  try {
    const data = await api.get<{ count: number; requests: RequestRecord[] }>('/debug/requests?n=200')
    records.value = [...(data.requests || [])].reverse()
    error.value = ''
  } catch (e: any) {
    error.value = e?.message || 'Failed to fetch diagnostics'
  } finally {
    loading.value = false
  }
}

async function fetchEngineStatus() {
  try {
    const data = await api.get<EngineStatus>('/debug/engine')
    // External API engines return {external: true, ...} — treat as valid status
    engineStatus.value = (data?.error && !data?.external) ? null : data
  } catch {
    engineStatus.value = null
  } finally {
    engineLoading.value = false
  }
}

async function clearLog() {
  if (!confirm('Clear all recorded requests? This cannot be undone.')) return
  clearing.value = true
  try {
    await api.delete('/debug/requests')
    records.value = []
  } catch (e: any) {
    error.value = e?.message || 'Failed to clear log'
  } finally {
    clearing.value = false
  }
}

const sourceStats = computed(() => {
  const map: Record<string, { count: number; totalTps: number; streaming: number; nonStreaming: number; swaps: number; totalPt: number; ooms: number }> = {}
  for (const r of filteredRecords.value) {
    const src = sourceLabel(r.user_agent)
    if (!map[src]) map[src] = { count: 0, totalTps: 0, streaming: 0, nonStreaming: 0, swaps: 0, totalPt: 0, ooms: 0 }
    map[src].count++
    map[src].totalTps += r.tps || 0
    map[src].totalPt += r.prompt_tokens || 0
    if (r.stream) map[src].streaming++
    else map[src].nonStreaming++
    if (r.model_swap) map[src].swaps++
    if (r.oom_likely) map[src].ooms++
  }
  return Object.entries(map).map(([source, s]) => ({
    source,
    count: s.count,
    avgTps: s.count ? +(s.totalTps / s.count).toFixed(1) : 0,
    avgPt: s.count ? Math.round(s.totalPt / s.count) : 0,
    streamingPct: s.count ? Math.round(s.streaming / s.count * 100) : 0,
    nonStreaming: s.nonStreaming,
    swaps: s.swaps,
    ooms: s.ooms,
  })).sort((a, b) => b.count - a.count)
})

const hasModelSwaps = computed(() => filteredRecords.value.some(r => r.model_swap))
const hasOoms = computed(() => filteredRecords.value.some(r => r.oom_likely))
const hasLargeContext = computed(() => filteredRecords.value.some(r => (r.prompt_tokens || 0) > 4000))
const hasLowTps = computed(() => filteredRecords.value.some(r => r.tps > 0 && r.tps < 5))

onMounted(() => {
  fetchRecords()
  fetchEngineStatus()
  pollTimer = setInterval(fetchRecords, 5000)
  engineTimer = setInterval(fetchEngineStatus, 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (engineTimer) clearInterval(engineTimer)
})
</script>

<template>
  <div class="diag-page">
    <div class="diag-header-row">
      <div>
        <h1 class="diag-title">System Monitor</h1>
        <p class="diag-subtitle">Live engine status + proxied request log. Updates every 3–5 s.</p>
      </div>
      <button class="btn-clear" :disabled="clearing" @click="clearLog">
        {{ clearing ? 'Clearing…' : 'Clear Log' }}
      </button>
    </div>

    <!-- Engine status panel -->
    <div class="engine-panel">
      <div class="engine-panel-title">Inference Engine</div>

      <div v-if="engineLoading && !engineStatus" class="engine-loading">Loading engine status…</div>
      <div v-else-if="!engineStatus" class="engine-offline">
        <span class="status-dot dot-offline" />
        Engine offline or unreachable
      </div>
      <div v-else-if="engineStatus.external" class="engine-external">
        <span class="status-dot dot-idle" />
        <div>
          <div class="engine-ext-label">External API (proxy)</div>
          <div class="engine-ext-url" :title="engineStatus.base_url">{{ engineStatus.base_url }}</div>
        </div>
      </div>

      <template v-else>
        <!-- Note for engines that don't expose /v1/status (e.g. rapid-mlx) -->
        <div v-if="engineStatus.no_detailed_status" class="engine-limited-note">
          <span class="status-dot dot-idle" /> Engine running — this engine doesn't expose detailed metrics
        </div>
        <div class="engine-stats-grid">
          <!-- Status + model -->
          <div class="estat">
            <div class="estat-label">Status</div>
            <div class="estat-value">
              <span :class="['status-dot', engineStatus.status === 'generating' ? 'dot-generating' : engineStatus.status === 'idle' ? 'dot-idle' : 'dot-offline']" />
              {{ engineStatus.status || '—' }}
            </div>
          </div>
          <div class="estat estat-model">
            <div class="estat-label">Model</div>
            <div class="estat-value" :title="engineStatus.model">{{ modelShort(engineStatus.model || '') }}</div>
          </div>
          <div class="estat">
            <div class="estat-label">Running / Waiting</div>
            <div class="estat-value">{{ engineStatus.num_running ?? '—' }} / {{ engineStatus.num_waiting ?? '—' }}</div>
          </div>
          <div class="estat">
            <div class="estat-label">Live TPS</div>
            <div class="estat-value" :class="tpsColor(engineStatus.generation_tps || 0)">
              {{ engineStatus.generation_tps?.toFixed(1) ?? '—' }} t/s
            </div>
          </div>

          <!-- Metal memory bar -->
          <div class="estat estat-wide" v-if="engineStatus.metal">
            <div class="estat-label">Metal GPU Memory</div>
            <div class="estat-mem">
              <div class="mem-bar-track">
                <div
                  class="mem-bar-fill"
                  :style="{
                    width: memBarPct(engineStatus.metal.active_memory_gb, engineStatus.metal.peak_memory_gb) + '%',
                    background: memBarColor(memBarPct(engineStatus.metal.active_memory_gb, engineStatus.metal.peak_memory_gb))
                  }"
                />
              </div>
              <span class="mem-label">
                {{ engineStatus.metal.active_memory_gb.toFixed(1) }} GB active
                / {{ engineStatus.metal.peak_memory_gb.toFixed(1) }} GB peak
              </span>
            </div>
          </div>

          <!-- KV cache -->
          <div class="estat" v-if="engineStatus.cache">
            <div class="estat-label">KV Cache Hit Rate</div>
            <div class="estat-value" :class="(engineStatus.cache.hit_rate || 0) > 0.5 ? 'tps-ok' : ''">
              {{ ((engineStatus.cache.hit_rate || 0) * 100).toFixed(0) }}%
            </div>
          </div>
          <div class="estat" v-if="engineStatus.cache">
            <div class="estat-label">Cache Memory</div>
            <div class="estat-value">
              {{ ((engineStatus.cache.current_memory_mb || 0) / 1024).toFixed(1) }} /
              {{ ((engineStatus.cache.max_memory_mb || 0) / 1024).toFixed(1) }} GB
            </div>
          </div>
        </div>

        <!-- Active requests -->
        <div v-if="engineStatus.requests?.length" class="active-requests">
          <div class="active-req-title">Active Requests ({{ engineStatus.requests.length }})</div>
          <div v-for="req in engineStatus.requests" :key="req.request_id" class="active-req-row">
            <span class="req-phase" :class="'phase-' + req.phase">{{ req.phase }}</span>
            <span class="req-tps" :class="tpsColor(req.tokens_per_second)">{{ req.tokens_per_second.toFixed(1) }} t/s</span>
            <span class="req-tokens">{{ req.completion_tokens }} / {{ req.max_tokens }} tok</span>
            <div class="req-progress-track">
              <div class="req-progress-fill" :style="{ width: (req.progress * 100).toFixed(1) + '%' }" />
            </div>
            <span class="req-elapsed">{{ req.elapsed_s.toFixed(0) }}s</span>
          </div>
        </div>
      </template>
    </div>

    <!-- OOM warning (highest priority) -->
    <div v-if="hasOoms" class="diag-warning diag-warning-red">
      <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <div>
        <strong>Possible Metal GPU OOM detected.</strong>
        One or more requests ran for &gt;5 s and returned 0 tokens. This usually means the engine ran out of Metal GPU memory (OOM), but can also indicate client cancellation.
        If you see this repeatedly without cancelling: root cause is likely no <code>max_tokens</code> limit sent by the client — the model generates until memory is exhausted.
        Fix: set <strong>Proxy Default Max Tokens</strong> in Settings → Network &amp; Access (4096 recommended).
      </div>
    </div>

    <!-- Model swap warning -->
    <div v-if="hasModelSwaps" class="diag-warning diag-warning-red">
      <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <div>
        <strong>Model swaps detected (likely cause of slow requests).</strong>
        Kilroy is requesting a model name that differs from the loaded model — the server must stop, reload, and warm up (30–120 s).
        Fix: configure Kilroy to use <code>default</code> as the model name, or match it to the loaded model exactly.
      </div>
    </div>

    <!-- Large context warning -->
    <div v-if="hasLargeContext" class="diag-warning diag-warning-amber">
      <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <div>
        <strong>Large prompt context detected (&gt;4 k tokens).</strong>
        Long conversation histories cause slow prefill and lower TPS. Set <strong>Max Context Messages</strong> in Settings → Network &amp; Access to trim history.
      </div>
    </div>

    <!-- Low TPS warning -->
    <div v-if="hasLowTps && !hasModelSwaps && !hasOoms" class="diag-warning diag-warning-amber">
      <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16" aria-hidden="true">
        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <div>
        <strong>Very low TPS detected (&lt;5 t/s).</strong>
        Possible causes: large prompt, model too big for available RAM, GPU pressure from another process.
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
              <th title="Average tokens per second">Avg TPS</th>
              <th title="Average prompt token count">Avg Prompt Tokens</th>
              <th>Streaming</th>
              <th title="Model hot-swaps">Swaps</th>
              <th title="Metal OOM crashes (0 tokens, long duration)">OOMs</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sourceStats" :key="s.source">
              <td class="source-cell">{{ s.source }}</td>
              <td>{{ s.count }}</td>
              <td :class="tpsColor(s.avgTps)">{{ s.avgTps }}</td>
              <td :class="s.avgPt > 4000 ? 'tps-low' : ''">{{ s.avgPt || '—' }}</td>
              <td>
                <span v-if="s.streamingPct > 0" class="badge badge-stream">{{ s.streamingPct }}%</span>
                <span v-else class="tx-muted">—</span>
              </td>
              <td>
                <span v-if="s.swaps > 0" class="badge badge-swap">{{ s.swaps }}</span>
                <span v-else class="tx-muted">—</span>
              </td>
              <td>
                <span v-if="s.ooms > 0" class="badge badge-oom">{{ s.ooms }}</span>
                <span v-else class="tx-muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Per-request log -->
    <div class="diag-section">
      <h2 class="diag-section-title">Recent Requests (last 200)</h2>

      <div v-if="loading" class="diag-empty">Loading…</div>
      <div v-else-if="error" class="diag-error">{{ error }}</div>
      <div v-else-if="!filteredRecords.length" class="diag-empty">
        No requests recorded yet. Make a request from Kilroy or the built-in chat to see data here.
      </div>

      <div v-else class="diag-table-wrap">
        <table class="diag-table diag-table-detail">
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Model</th>
              <th>Flags</th>
              <th title="Prompt token count">Prompt Tok</th>
              <th>Msgs</th>
              <th title="Max tokens cap applied">Cap</th>
              <th title="Time to first token">TTFT</th>
              <th title="Total duration">Duration</th>
              <th title="Tokens per second">TPS</th>
              <th title="Proxy overhead before hitting engine">Proxy</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in filteredRecords"
              :key="r.ts + '-' + i"
              :class="{ 'row-swap': r.model_swap, 'row-oom': r.oom_likely }"
            >
              <td class="time-cell">{{ r.time }}</td>
              <td class="source-cell">{{ sourceLabel(r.user_agent) }}</td>
              <td class="model-cell" :title="r.model">{{ modelShort(r.model) }}</td>
              <td class="flags-cell">
                <span v-if="r.oom_likely" class="badge badge-oom" title="Metal OOM — engine ran out of GPU memory">OOM</span>
                <span v-if="r.model_swap" class="badge badge-swap" title="Model was hot-swapped — adds 30–120 s">swap</span>
                <span :class="r.stream ? 'badge badge-stream' : 'badge badge-nostream'">
                  {{ r.stream ? 'stream' : 'batch' }}
                </span>
              </td>
              <td :class="(r.prompt_tokens || 0) > 4000 ? 'tps-low' : ''">
                {{ r.prompt_tokens || '—' }}
              </td>
              <td>{{ r.msg_count || '—' }}</td>
              <td class="tx-muted">{{ r.max_tokens || '∞' }}</td>
              <td>{{ r.ttft_ms != null ? r.ttft_ms + 'ms' : '—' }}</td>
              <td :class="r.oom_likely ? 'tps-low' : ''">{{ fmtDuration(r.duration_ms) }}</td>
              <td :class="tpsColor(r.tps)">{{ r.tps || (r.oom_likely ? '—' : r.tps) }}</td>
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
        <dt><span class="badge badge-oom">OOM</span></dt>
        <dd>Metal GPU ran out of memory. Request completed with 0 tokens after a long wait. Fix: set Proxy Default Max Tokens in Settings → Network &amp; Access.</dd>
        <dt><span class="badge badge-swap">swap</span></dt>
        <dd>Model was hot-swapped before this request — adds 30–120 s. Fix by configuring Kilroy to use the same model name as the loaded model.</dd>
        <dt>Cap</dt>
        <dd>Max tokens cap applied by the proxy. <strong>∞</strong> means no cap — the model will generate until it hits its own context limit or runs out of GPU memory.</dd>
        <dt>Prompt Tok</dt>
        <dd>Token count of the input. Values &gt;4 k cause slow prefill. Use Max Context Messages in Settings to trim conversation history.</dd>
        <dt>TPS</dt>
        <dd>Tokens per second — actual generation throughput. Should be consistent across clients. &lt;5 t/s = large context or hardware pressure.</dd>
        <dt><span class="badge badge-nostream">batch</span></dt>
        <dd>Client waits for ALL tokens before getting anything. Enable <code>"stream": true</code> for better perceived latency.</dd>
        <dt>Proxy</dt>
        <dd>Milliseconds in the dashboard proxy before forwarding to the engine. Should be under 10 ms.</dd>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.diag-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.diag-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

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

.btn-clear {
  flex-shrink: 0;
  padding: 0.375rem 0.875rem;
  background: var(--bg-elevated);
  border: 1px solid var(--bd);
  border-radius: 6px;
  color: var(--tx-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-clear:hover:not(:disabled) { background: var(--bg-surface); color: var(--tx-primary); }
.btn-clear:disabled { opacity: 0.5; cursor: default; }

/* Engine status panel */
.engine-panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
.engine-panel-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--tx-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.875rem;
}
.engine-loading, .engine-offline {
  font-size: 0.8125rem;
  color: var(--tx-secondary);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.engine-limited-note {
  font-size: 0.8125rem;
  color: var(--tx-secondary);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.engine-external {
  font-size: 0.8125rem;
  color: var(--tx-secondary);
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.25rem 0;
}
.engine-ext-label {
  font-weight: 600;
  color: var(--tx-primary);
  font-size: 0.75rem;
}
.engine-ext-url {
  font-size: 0.75rem;
  color: var(--tx-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}

.engine-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem 1.25rem;
}
.estat { display: flex; flex-direction: column; gap: 0.2rem; }
.estat-wide { grid-column: span 2; }
.estat-model { grid-column: span 2; }
.estat-label {
  font-size: 0.6875rem;
  font-weight: 500;
  color: var(--tx-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.estat-value {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--tx-primary);
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-generating { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
.dot-idle { background: #fbbf24; }
.dot-offline { background: #6b7280; }

.estat-mem { display: flex; flex-direction: column; gap: 0.375rem; }
.mem-bar-track {
  height: 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
  overflow: hidden;
  width: 100%;
}
.mem-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease, background 0.5s ease;
}
.mem-label { font-size: 0.75rem; color: var(--tx-secondary); }

.active-requests { margin-top: 0.875rem; border-top: 1px solid var(--bd); padding-top: 0.75rem; }
.active-req-title { font-size: 0.75rem; font-weight: 600; color: var(--tx-tertiary); text-transform: uppercase; margin-bottom: 0.5rem; }
.active-req-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.8125rem;
  padding: 0.25rem 0;
}
.req-phase {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.1em 0.4em;
  border-radius: 3px;
  text-transform: uppercase;
  background: var(--bg-elevated);
  color: var(--tx-secondary);
  min-width: 64px;
  text-align: center;
}
.phase-generation { background: color-mix(in srgb, #4ade80 15%, transparent); color: #4ade80; }
.phase-prefill { background: color-mix(in srgb, #60a5fa 15%, transparent); color: #60a5fa; }
.req-tps { font-weight: 600; min-width: 70px; }
.req-tokens { color: var(--tx-secondary); min-width: 100px; }
.req-progress-track {
  flex: 1;
  height: 4px;
  background: var(--bg-elevated);
  border-radius: 2px;
  overflow: hidden;
}
.req-progress-fill { height: 100%; background: #4ade80; border-radius: 2px; transition: width 0.5s; }
.req-elapsed { color: var(--tx-tertiary); font-variant-numeric: tabular-nums; min-width: 32px; text-align: right; }

/* Warnings */
.diag-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.8125rem;
  color: var(--tx-primary);
  line-height: 1.5;
}
.diag-warning-red {
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border: 1px solid color-mix(in srgb, #ef4444 35%, transparent);
}
.diag-warning-red svg { color: #ef4444; }
.diag-warning-amber {
  background: color-mix(in srgb, #f59e0b 12%, transparent);
  border: 1px solid color-mix(in srgb, #f59e0b 35%, transparent);
}
.diag-warning-amber svg { color: #f59e0b; }
.diag-warning svg { flex-shrink: 0; margin-top: 1px; }
.diag-warning strong { display: block; margin-bottom: 0.25rem; }
.diag-warning code { background: var(--bg-elevated); padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.875em; }

/* Sections */
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

/* Tables */
.diag-table-wrap { overflow-x: auto; }
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
.row-swap td { background: color-mix(in srgb, #ef4444 6%, transparent); }
.row-swap:hover td { background: color-mix(in srgb, #ef4444 10%, transparent) !important; }
.row-oom td { background: color-mix(in srgb, #ef4444 12%, transparent); }
.row-oom:hover td { background: color-mix(in srgb, #ef4444 18%, transparent) !important; }

.time-cell { color: var(--tx-tertiary); font-variant-numeric: tabular-nums; }
.source-cell { font-weight: 500; }
.model-cell { color: var(--tx-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.flags-cell { white-space: nowrap; }

.tps-ok  { color: #4ade80; font-weight: 600; }
.tps-mid { color: #fbbf24; font-weight: 600; }
.tps-low { color: #f87171; font-weight: 600; }

.badge {
  display: inline-block;
  padding: 0.1em 0.5em;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  margin-right: 0.2em;
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
.badge-swap {
  background: color-mix(in srgb, #ef4444 18%, transparent);
  color: #f87171;
  border: 1px solid color-mix(in srgb, #ef4444 30%, transparent);
}
.badge-oom {
  background: color-mix(in srgb, #ef4444 25%, transparent);
  color: #fca5a5;
  border: 1px solid color-mix(in srgb, #ef4444 50%, transparent);
  font-weight: 700;
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

