<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
  BenchmarkView — Performance & Data hub.

  Sections (tabbed):
    Live      — real-time server metrics: request charts, GPU memory chart,
                active requests table, cache statistics panel
    Benchmark — unified Speed + Quality benchmark runner; shows current run results
    History   — all prior runs (most recent first), select to compare, favorite, delete
    Advisor   — describe a task → AI recommends best model + config
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import type { ChartData, ChartOptions } from 'chart.js'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import type { QualitySuiteResult } from '@/stores/models'
import AppButton from '@/components/shared/AppButton.vue'
import { api } from '@/api/client'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  Filler, Tooltip, Legend,
)

const serverStore = useServerStore()
const modelsStore = useModelsStore()

// ── Tab state ─────────────────────────────────────────────────────────────
const tabs = ['Live', 'Benchmark', 'History', 'Advisor'] as const
type Tab = typeof tabs[number]
const activeTab = ref<Tab>('Live')

// ── Live tab — polling ─────────────────────────────────────────────────────
let stopPoll: (() => void) | null = null
let cacheInterval: ReturnType<typeof setInterval> | null = null
const cacheStats = ref<Record<string, unknown> | null>(null)
const cacheError = ref(false)

async function refreshCache() {
  if (!serverStore.isRunning) { cacheStats.value = null; return }
  const result = await serverStore.fetchCacheStats()
  if (result && !result.error) { cacheStats.value = result; cacheError.value = false }
  else cacheError.value = true
}

onMounted(() => {
  stopPoll = serverStore.startPolling(3000)
  refreshCache()
  cacheInterval = setInterval(refreshCache, 15_000)
  modelsStore.fetchBenchmarkResults()
  modelsStore.fetchModels()
})

onUnmounted(() => {
  stopPoll?.()
  if (cacheInterval) clearInterval(cacheInterval)
  stopBenchmarkPolls()
})

watch(() => serverStore.isRunning, (running) => {
  if (running) refreshCache()
  else { cacheStats.value = null; cacheError.value = false }
})

// ── Live tab — chart data ──────────────────────────────────────────────────
const lineOpts: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: { legend: { display: false }, tooltip: {
    backgroundColor: '#1c1c1e',
    borderColor: 'rgba(255,255,255,.08)',
    borderWidth: 1,
    titleColor: '#e5e5ea',
    bodyColor: '#aeaeb2',
  }},
  scales: {
    x: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#636366', maxTicksLimit: 8, font: { size: 10 } } },
    y: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#636366', font: { size: 10 } }, beginAtZero: true },
  },
}

const requestsChartData = computed((): ChartData<'line'> => {
  const h = serverStore.metricsHistory
  return {
    labels: h.map(e => e.time),
    datasets: [
      {
        label: 'Active',
        data: h.map(e => e.active),
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167,139,250,.12)',
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      },
      {
        label: 'Queued',
        data: h.map(e => e.queued),
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245,158,11,.08)',
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      },
    ],
  }
})

const memoryChartData = computed((): ChartData<'line'> => {
  const h = serverStore.metricsHistory
  return {
    labels: h.map(e => e.time),
    datasets: [{
      label: 'GPU Memory (GB)',
      data: h.map(e => e.memory_gb),
      borderColor: '#34d399',
      backgroundColor: 'rgba(52,211,153,.1)',
      borderWidth: 1.5,
      fill: true,
      tension: 0.3,
      pointRadius: 0,
    }],
  }
})

// ── Uptime formatter ────────────────────────────────────────────────────────
const uptime = computed(() => {
  const s = serverStore.uptimeSeconds
  if (!s) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
})

// ── Cache stats display ─────────────────────────────────────────────────────
const cacheEntries = computed(() => {
  if (!cacheStats.value) return []
  return Object.entries(cacheStats.value).map(([k, v]) => ({ key: k, value: v }))
})

// ── BENCHMARK TAB — unified Speed + Quality ────────────────────────────────
const QUALITY_SUITES = [
  { id: 'gsm8k',     label: 'GSM8K',     description: 'Math word problems' },
  { id: 'mmlu',      label: 'MMLU',      description: 'Multi-subject knowledge' },
  { id: 'humaneval', label: 'HumanEval', description: 'Python coding tasks' },
]

// Mode: combined runs quality questions with streaming → captures both accuracy + speed
type BenchMode = 'combined' | 'speed' | 'quality'
const benchMode = ref<BenchMode>('combined')
const BENCH_MODES = [
  { id: 'combined' as BenchMode, label: 'Speed + Quality', description: 'Accuracy & real-world speed in one pass' },
  { id: 'speed'    as BenchMode, label: 'Speed only',      description: 'Throughput & TTFT with synthetic prompts' },
  { id: 'quality'  as BenchMode, label: 'Quality only',    description: 'Accuracy scores (speed captured as bonus)' },
]

// Quality suite selection (shown when mode !== 'speed')
const benchSuites       = ref<string[]>(['gsm8k', 'mmlu', 'humaneval'])
// Speed-only options (shown when mode === 'speed')
const benchMaxTokens    = ref(256)
const benchRuns         = ref(3)
const benchNumQuestions = ref(20)

// Model selection
const cachedModels = computed(() => modelsStore.models.filter((m: { cached: boolean }) => m.cached))
const benchSelectedModels = ref<string[]>([])

// Seed selection with the currently running model
watch(
  () => serverStore.modelId,
  (id) => {
    if (id && !benchSelectedModels.value.includes(id)) benchSelectedModels.value = [id]
  },
  { immediate: true },
)

function toggleBenchModel(id: string) {
  const idx = benchSelectedModels.value.indexOf(id)
  if (idx === -1) benchSelectedModels.value.push(id)
  else benchSelectedModels.value.splice(idx, 1)
}

// Run state
const benchRunning     = ref(false)
const speedPhase       = ref<'idle' | 'running' | 'done' | 'error'>('idle')
const qualityPhase     = ref<'idle' | 'running' | 'done' | 'error'>('idle')
const qualityLines     = ref<string[]>([])
const qualityLogRef    = ref<HTMLPreElement | null>(null)
let   qualityPollTimer: ReturnType<typeof setInterval> | null = null
let   speedPollTimer:   ReturnType<typeof setInterval> | null = null

// Last-run results
const lastRunSpeed   = ref<typeof modelsStore.benchmarkResults extends (infer T)[] ? T : any | null>(null)
const lastRunQuality = ref<Record<string, any> | null>(null)
const lastRunModel   = ref('')
const lastRunTime    = ref('')

function stopBenchmarkPolls() {
  if (qualityPollTimer) { clearInterval(qualityPollTimer); qualityPollTimer = null }
  if (speedPollTimer)   { clearInterval(speedPollTimer);   speedPollTimer   = null }
}

async function runBenchmark() {
  if (!serverStore.isRunning || benchRunning.value) return
  if (benchMode.value === 'speed' && benchSelectedModels.value.length === 0) return
  if (benchMode.value !== 'speed' && benchSuites.value.length === 0) return

  benchRunning.value = true
  speedPhase.value   = 'idle'
  qualityPhase.value = 'idle'
  qualityLines.value = []
  lastRunSpeed.value   = null
  lastRunQuality.value = null
  lastRunModel.value   = benchSelectedModels.value.join(', ')
  lastRunTime.value    = new Date().toLocaleTimeString()

  const runSpeed   = benchMode.value === 'speed'
  const runQuality = benchMode.value !== 'speed'

  let speedDone   = !runSpeed
  let qualityDone = !runQuality

  function checkDone() {
    if (speedDone && qualityDone) {
      benchRunning.value = false
      modelsStore.fetchBenchmarkResults()
    }
  }

  // Speed-only: synthetic benchmark (isolated throughput)
  if (runSpeed) {
    speedPhase.value = 'running'
    const models = benchSelectedModels.value.length > 0 ? benchSelectedModels.value : [serverStore.modelId ?? '']
    try {
      await api.post('/benchmark/run', {
        model_ids: models,
        config: { runs: benchRuns.value, max_tokens: benchMaxTokens.value, prompt: 'Explain the concept of machine learning in simple terms.' },
      })
    } catch {
      speedPhase.value = 'error'
      speedDone = true
      checkDone()
    }
    if (speedPhase.value === 'running') {
      speedPollTimer = setInterval(async () => {
        try {
          const status = await api.get<{ running: boolean }>('/benchmark/status')
          if (!status.running) {
            clearInterval(speedPollTimer!); speedPollTimer = null
            speedPhase.value = 'done'
            await modelsStore.fetchBenchmarkResults()
            const hist = modelsStore.benchmarkHistory
            lastRunSpeed.value = hist.length ? hist[hist.length - 1] : null
            speedDone = true
            checkDone()
          }
        } catch {
          clearInterval(speedPollTimer!); speedPollTimer = null
          speedPhase.value = 'error'
          speedDone = true
          checkDone()
        }
      }, 1500)
    }
  }

  // Quality (or combined): streaming questions capture both accuracy + TTFT/tok/s
  if (runQuality) {
    qualityPhase.value = 'running'
    try {
      const runData = await api.post<{ ok: boolean; run_id: string }>('/quality-benchmark/run', {
        suites: benchSuites.value,
        num_questions: benchNumQuestions.value,
      })
      const runId = runData.run_id
      let lineOffset = 0
      qualityPollTimer = setInterval(async () => {
        try {
          const out = await api.get<{
            running: boolean; lines: string[]; results: any; error: string | null; total_lines: number
          }>(`/quality-benchmark/output/${runId}?since=${lineOffset}`)
          qualityLines.value.push(...out.lines)
          lineOffset = out.total_lines
          if (!out.running) {
            clearInterval(qualityPollTimer!); qualityPollTimer = null
            qualityPhase.value = out.error ? 'error' : 'done'
            if (out.results) lastRunQuality.value = out.results
            qualityDone = true
            checkDone()
          }
        } catch {
          clearInterval(qualityPollTimer!); qualityPollTimer = null
          qualityPhase.value = 'error'
          qualityDone = true
          checkDone()
        }
      }, 1000)
    } catch {
      qualityPhase.value = 'error'
      qualityDone = true
      checkDone()
    }
  }
}

watch(qualityLines, () => {
  nextTick(() => {
    if (qualityLogRef.value) qualityLogRef.value.scrollTop = qualityLogRef.value.scrollHeight
  })
})

const anyResultsReady = computed(() =>
  lastRunSpeed.value !== null || lastRunQuality.value !== null
)

// ── HISTORY TAB ────────────────────────────────────────────────────────────
// Most-recent first; loaded by onMounted
const sortedHistory = computed(() =>
  [...(modelsStore.benchmarkHistory ?? [])].sort((a, b) =>
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )
)

const historySelected = ref<Set<number>>(new Set())

function toggleHistorySelect(id: number) {
  const s = new Set(historySelected.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  historySelected.value = s
}

const compareRuns = computed(() =>
  sortedHistory.value.filter(r => historySelected.value.has(r.id))
)

function formatRelTime(ts: string): string {
  if (!ts) return '—'
  const diff = Date.now() - new Date(ts).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)   return 'just now'
  if (s < 3600) return `${Math.floor(s/60)}m ago`
  if (s < 86400) return `${Math.floor(s/3600)}h ago`
  return new Date(ts).toLocaleDateString()
}

// ── Cost Analysis ────────────────────────────────────────────────────────────
interface CostByModel {
  model_id: string
  tier: 'small' | 'medium' | 'large'
  tokens_generated: number
  estimated_cost_usd: number
}
interface CostStats {
  benchmarks_analyzed: number
  total_input_tokens: number
  total_output_tokens: number
  estimated_cloud_cost_usd: number
  estimated_monthly_savings_usd: number
  by_model: CostByModel[]
  rates_used: Record<string, { input_per_1m: number; output_per_1m: number }>
}
const costStats   = ref<CostStats | null>(null)
const costLoading = ref(false)
const costError   = ref(false)

async function fetchCostStats() {
  costLoading.value = true
  costError.value   = false
  try {
    const data = await api.get<CostStats>('/stats/cost')
    costStats.value = data
  } catch {
    costError.value = true
  } finally {
    costLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'History') {
    modelsStore.fetchBenchmarkResults()
    fetchCostStats()
  }
})
</script>

<template>
  <div class="benchmark-view">
    <!-- Page header -->
    <div class="page-header">
      <div class="page-title">Benchmarks <span class="amp">&amp;</span> Data</div>
      <p class="page-desc">Performance metrics, model benchmarks, and data to guide every inference decision.</p>
    </div>

    <!-- Tab bar -->
    <div class="tab-bar-wrap">
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab"
          class="tab-btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >{{ tab }}</button>
      </div>
    </div>

    <!-- ── LIVE TAB ──────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'Live'" class="tab-body">

      <!-- Status banner -->
      <div
        class="status-banner"
        :class="{
          'banner-green': serverStore.isRunning && serverStore.status?.healthy,
          'banner-yellow': serverStore.isRunning && !serverStore.status?.healthy,
          'banner-red': !serverStore.isRunning,
        }"
      >
        <span class="banner-dot" />
        <span v-if="serverStore.isRunning && serverStore.status?.healthy">
          <strong>Running</strong> — {{ serverStore.modelId ?? 'loading model…' }}
          <span class="banner-dim">· PID {{ serverStore.status?.pid }}</span>
        </span>
        <span v-else-if="serverStore.isRunning">
          <strong>Starting</strong> — waiting for model to load…
        </span>
        <span v-else><strong>Server stopped</strong> — go to Serve to start it.</span>
      </div>

      <!-- 8 metric cards -->
      <div class="metrics-grid-8">
        <div class="mcard">
          <div class="mcard-label">Uptime</div>
          <div class="mcard-val mono">{{ uptime }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Active</div>
          <div class="mcard-val">{{ serverStore.isRunning ? serverStore.numRunning : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Queued</div>
          <div class="mcard-val">{{ serverStore.isRunning ? serverStore.numWaiting : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Completed</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalRequests.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Prompt Tokens</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalPromptTokens.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Output Tokens</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalCompletionTokens.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">GPU Memory</div>
          <div class="mcard-val mono">
            {{ serverStore.metalMemoryGb != null ? serverStore.metalMemoryGb.toFixed(2) + ' GB' : '—' }}
          </div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Peak Memory</div>
          <div class="mcard-val mono">
            {{ serverStore.peakMemoryGb != null ? serverStore.peakMemoryGb.toFixed(2) + ' GB' : '—' }}
          </div>
        </div>
      </div>

      <!-- Charts row -->
      <div class="charts-row">
        <div class="chart-card">
          <div class="chart-title">Requests over time</div>
          <div class="chart-legend">
            <span class="legend-dot" style="background:#a78bfa" />Active
            <span class="legend-dot" style="background:#f59e0b" />Queued
          </div>
          <div class="chart-area">
            <Line
              v-if="serverStore.metricsHistory.length > 1"
              :data="requestsChartData"
              :options="lineOpts"
            />
            <div v-else class="chart-empty">Waiting for data…</div>
          </div>
        </div>

        <div class="chart-card">
          <div class="chart-title">GPU memory (GB)</div>
          <div class="chart-area">
            <Line
              v-if="serverStore.metricsHistory.length > 1"
              :data="memoryChartData"
              :options="lineOpts"
            />
            <div v-else class="chart-empty">Waiting for data…</div>
          </div>
        </div>
      </div>

      <!-- Active requests table -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Active requests</div>
          <span v-if="serverStore.metrics?.requests?.length" class="panel-count">
            {{ serverStore.metrics.requests.length }}
          </span>
        </div>
        <div
          v-if="serverStore.isRunning && serverStore.metrics?.requests?.length"
          class="table-wrap"
        >
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Model</th>
                <th class="num">Tokens</th>
                <th class="num">Elapsed (s)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="req in serverStore.metrics!.requests" :key="req.id">
                <td class="mono dim">{{ req.id?.slice(0, 12) ?? '—' }}</td>
                <td class="mono">{{ (req.model || '').split('/').pop() }}</td>
                <td class="num mono">{{ req.tokens_generated ?? '—' }}</td>
                <td class="num mono">{{ req.elapsed_s?.toFixed(1) ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="panel-empty">
          {{ serverStore.isRunning ? 'No active requests right now.' : 'Server not running.' }}
        </div>
      </div>

      <!-- Cache statistics -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Cache statistics</div>
        </div>
        <div v-if="cacheStats && cacheEntries.length" class="cache-grid">
          <div v-for="entry in cacheEntries" :key="entry.key" class="cache-item">
            <div class="cache-key">{{ entry.key }}</div>
            <div class="cache-val mono">
              {{ typeof entry.value === 'object' ? JSON.stringify(entry.value) : String(entry.value) }}
            </div>
          </div>
        </div>
        <div v-else-if="cacheError" class="panel-empty warn">Cache stats unavailable.</div>
        <div v-else class="panel-empty">
          {{ serverStore.isRunning ? 'Loading…' : 'Server not running.' }}
        </div>
      </div>
    </div>

    <!-- ── BENCHMARK TAB ──────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Benchmark'" class="tab-body">

      <!-- Server warning -->
      <div v-if="!serverStore.isRunning" class="status-banner banner-red">
        <span class="banner-dot" />
        <span><strong>Server not running</strong> — start it on the Serve page first.</span>
      </div>

      <!-- Config panel -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Configure Benchmark</div>
          <span v-if="serverStore.modelId" class="panel-model mono">
            {{ serverStore.modelId.split('/').pop() }}
          </span>
        </div>
        <div class="bench-config">

          <!-- Model selector -->
          <div class="bench-section-label">Models to test</div>
          <div v-if="cachedModels.length === 0" class="bench-no-models">
            No downloaded models found — download a model on the Models page first.
          </div>
          <div v-else class="bench-model-list">
            <label
              v-for="m in cachedModels"
              :key="m.id"
              class="bench-check"
              :class="{ checked: benchSelectedModels.includes(m.id) }"
            >
              <input
                type="checkbox"
                :disabled="benchRunning"
                :checked="benchSelectedModels.includes(m.id)"
                @change="toggleBenchModel(m.id)"
              />
              <div class="bench-check-info">
                <span class="bench-check-label mono">{{ m.id.split('/').pop() }}</span>
                <span class="bench-check-desc">{{ m.id.split('/')[0] }} &middot; {{ m.size_gb?.toFixed(1) ?? '?' }} GB</span>
              </div>
              <span v-if="m.id === serverStore.modelId" class="bench-model-badge">running</span>
            </label>
          </div>

          <!-- Mode selector -->
          <div class="bench-section-label">Mode</div>
          <div class="bench-mode-row">
            <label
              v-for="mode in BENCH_MODES"
              :key="mode.id"
              class="bench-mode-option"
              :class="{ active: benchMode === mode.id }"
            >
              <input type="radio" v-model="benchMode" :value="mode.id" :disabled="benchRunning" />
              <div class="bench-check-info">
                <span class="bench-check-label">{{ mode.label }}</span>
                <span class="bench-check-desc">{{ mode.description }}</span>
              </div>
            </label>
          </div>

          <!-- Quality suite checkboxes (hidden for speed-only mode) -->
          <template v-if="benchMode !== 'speed'">
            <div class="bench-section-label">Quality suites</div>
            <div class="bench-checks">
              <label
                v-for="suite in QUALITY_SUITES"
                :key="suite.id"
                class="bench-check"
                :class="{ checked: benchSuites.includes(suite.id) }"
              >
                <input
                  type="checkbox"
                  :value="suite.id"
                  v-model="benchSuites"
                  :disabled="benchRunning"
                />
                <div class="bench-check-info">
                  <span class="bench-check-label">{{ suite.label }}</span>
                  <span class="bench-check-desc">{{ suite.description }}</span>
                </div>
              </label>
            </div>
          </template>

          <!-- Options row -->
          <div class="bench-opts-row">
            <label v-if="benchMode === 'speed'" class="opt-label">
              Runs
              <select v-model="benchRuns" :disabled="benchRunning" class="opt-select">
                <option :value="1">1</option>
                <option :value="3">3</option>
                <option :value="5">5</option>
              </select>
            </label>
            <label v-if="benchMode === 'speed'" class="opt-label">
              Max tokens
              <select v-model="benchMaxTokens" :disabled="benchRunning" class="opt-select">
                <option :value="128">128</option>
                <option :value="256">256</option>
                <option :value="512">512</option>
              </select>
            </label>
            <label v-if="benchMode !== 'speed'" class="opt-label">
              Questions / suite
              <select v-model="benchNumQuestions" :disabled="benchRunning" class="opt-select">
                <option :value="5">5 (quick)</option>
                <option :value="10">10</option>
                <option :value="20">20</option>
                <option :value="25">25 (full)</option>
              </select>
            </label>
          </div>

          <!-- Run button -->
          <div class="bench-run-row">
            <AppButton
              :disabled="benchRunning || !serverStore.isRunning || (benchMode === 'speed' && benchSelectedModels.length === 0) || (benchMode !== 'speed' && benchSuites.length === 0)"
              @click="runBenchmark"
            >
              {{ benchRunning ? 'Running…' : 'Run Benchmark' }}
            </AppButton>
          </div>
        </div>
      </div>

      <!-- Progress panels -->
      <div v-if="benchRunning || anyResultsReady" class="bench-progress-row">

        <!-- Speed progress (speed-only mode) -->
        <div v-if="benchMode === 'speed'" class="panel bench-phase-card">
          <div class="panel-header">
            <div class="panel-title">Speed</div>
            <span class="phase-badge" :class="speedPhase">
              {{ speedPhase === 'running' ? 'Running…' : speedPhase === 'done' ? 'Done' : speedPhase === 'error' ? 'Error' : '' }}
            </span>
          </div>
          <div class="bench-phase-body">
            <div v-if="speedPhase === 'idle'" class="panel-empty">Waiting to start…</div>
            <div v-else-if="speedPhase === 'running'" class="bench-spin-row">
              <span class="spin" />
              <span class="dim">Benchmarking tok/s against live server…</span>
            </div>
            <div v-else-if="speedPhase === 'done' && lastRunSpeed" class="speed-result-inline">
              <div class="sri-stat">
                <div class="sri-val mono">{{ (lastRunSpeed as any).avg_tps?.toFixed(1) ?? '—' }}</div>
                <div class="sri-label">avg t/s</div>
              </div>
              <div v-if="(lastRunSpeed as any).avg_ttft_ms" class="sri-stat">
                <div class="sri-val mono">{{ Math.round((lastRunSpeed as any).avg_ttft_ms) }}ms</div>
                <div class="sri-label">avg TTFT</div>
              </div>
            </div>
            <div v-else-if="speedPhase === 'error'" class="panel-empty warn">Speed benchmark failed.</div>
          </div>
        </div>

        <!-- Quality progress -->
        <div v-if="benchMode !== 'speed'" class="panel bench-phase-card">
          <div class="panel-header">
            <div class="panel-title">{{ benchMode === 'combined' ? 'Quality + Speed' : 'Quality' }}</div>
            <span class="phase-badge" :class="qualityPhase">
              {{ qualityPhase === 'running' ? 'Running…' : qualityPhase === 'done' ? 'Done' : qualityPhase === 'error' ? 'Error' : '' }}
            </span>
          </div>
          <div class="bench-phase-body">
            <div v-if="qualityPhase === 'idle'" class="panel-empty">Waiting to start…</div>
            <pre
              v-else-if="qualityPhase === 'running' || qualityLines.length"
              ref="qualityLogRef"
              class="quality-log"
            >{{ qualityLines.join('') }}</pre>
            <div v-if="qualityPhase === 'done' && lastRunQuality" class="quality-scores-inline">
              <div
                v-for="(sr, key) in lastRunQuality.suites"
                :key="key"
                class="qsi"
              >
                <div class="qsi-name">{{ String(key).toUpperCase() }}</div>
                <div
                  class="qsi-score"
                  :class="(sr as QualitySuiteResult).accuracy >= 0.7 ? 'good' : (sr as QualitySuiteResult).accuracy >= 0.5 ? 'mid' : 'bad'"
                >
                  {{ Math.round((sr as QualitySuiteResult).accuracy * 100) }}%
                </div>
                <div class="qsi-detail dim">{{ (sr as QualitySuiteResult).correct }}/{{ (sr as QualitySuiteResult).total }}</div>
              </div>
              <div class="qsi qsi-overall">
                <div class="qsi-name">Overall</div>
                <div class="qsi-score" :class="lastRunQuality.overall_score >= 0.7 ? 'good' : lastRunQuality.overall_score >= 0.5 ? 'mid' : 'bad'">
                  {{ Math.round(lastRunQuality.overall_score * 100) }}%
                </div>
              </div>
              <!-- Speed metrics captured during quality run -->
              <div v-if="lastRunQuality.overall_speed?.avg_tokens_per_sec" class="qsi-speed-row">
                <span class="qsi-speed-stat">
                  <span class="qsi-speed-val">{{ lastRunQuality.overall_speed.avg_tokens_per_sec }}</span>
                  <span class="qsi-speed-lbl">tok/s</span>
                </span>
                <span v-if="lastRunQuality.overall_speed.avg_ttft_ms" class="qsi-speed-stat">
                  <span class="qsi-speed-val">{{ lastRunQuality.overall_speed.avg_ttft_ms }}</span>
                  <span class="qsi-speed-lbl">ms TTFT</span>
                </span>
                <span class="qsi-speed-stat">
                  <span class="qsi-speed-val">{{ lastRunQuality.overall_speed.total_tokens?.toLocaleString() }}</span>
                  <span class="qsi-speed-lbl">tokens total</span>
                </span>
              </div>
            </div>
            <div v-else-if="qualityPhase === 'error'" class="panel-empty warn">Quality benchmark failed.</div>
          </div>
        </div>
      </div>

    </div>

    <!-- ── HISTORY TAB ────────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'History'" class="tab-body">

      <!-- Cost Analysis panel -->
      <div class="cost-panel">
        <div class="panel-header">
          <div class="panel-title">Cost Analysis</div>
        </div>
        <div v-if="costLoading" class="cost-body">
          <div class="cost-skeleton-row" />
          <div class="cost-skeleton-row short" />
        </div>
        <div v-else-if="costError" class="panel-empty warn">Could not load cost data.</div>
        <div v-else-if="!costStats || costStats.benchmarks_analyzed === 0" class="panel-empty">
          Run a benchmark to see cloud cost estimates.
        </div>
        <div v-else class="cost-body">
          <div class="cost-summary-row">
            <div class="cost-summary-card">
              <div class="cost-summary-label">Estimated cloud cost to date</div>
              <div class="cost-summary-value cu">${{ costStats.estimated_cloud_cost_usd.toFixed(2) }}</div>
              <div class="cost-summary-sub">
                {{ costStats.total_input_tokens.toLocaleString() }} input &plus;
                {{ costStats.total_output_tokens.toLocaleString() }} output tokens
                across {{ costStats.benchmarks_analyzed }} runs
              </div>
            </div>
            <div class="cost-summary-card">
              <div class="cost-summary-label">Est. monthly savings at current usage</div>
              <div class="cost-summary-value si">${{ costStats.estimated_monthly_savings_usd.toFixed(2) }}</div>
              <div class="cost-summary-sub">vs equivalent cloud API calls</div>
            </div>
          </div>
        </div>
      </div>

      <!-- History header -->
      <div v-if="sortedHistory.length" class="history-toolbar">
        <span class="saved-count">{{ sortedHistory.length }} runs</span>
        <div class="history-actions">
          <AppButton
            v-if="historySelected.size >= 2"
            variant="secondary"
            size="sm"
          >
            Compare {{ historySelected.size }} runs
          </AppButton>
          <AppButton
            variant="ghost"
            size="sm"
            @click="modelsStore.clearAllBenchmarks?.()"
          >
            Clear all
          </AppButton>
        </div>
      </div>

      <!-- Comparison table -->
      <div v-if="compareRuns.length >= 2" class="panel compare-panel">
        <div class="panel-header">
          <div class="panel-title">Comparison</div>
          <button class="icon-btn" @click="historySelected = new Set()">✕ Clear</button>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Date</th>
                <th class="num">Speed (t/s)</th>
                <th class="num">TTFT</th>
                <th class="num">GSM8K</th>
                <th class="num">MMLU</th>
                <th class="num">HumanEval</th>
                <th class="num">Overall</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in compareRuns" :key="run.id">
                <td class="mono">{{ (run.model_id || '').split('/').pop() || '—' }}</td>
                <td class="dim">{{ formatRelTime(run.timestamp) }}</td>
                <td class="num mono">{{ run.avg_tps > 0 ? run.avg_tps.toFixed(1) : '—' }}</td>
                <td class="num mono">{{ run.avg_ttft_ms ? Math.round(run.avg_ttft_ms) + 'ms' : '—' }}</td>
                <td class="num mono">{{ run.suites?.gsm8k ? Math.round(run.suites.gsm8k.accuracy * 100) + '%' : '—' }}</td>
                <td class="num mono">{{ run.suites?.mmlu ? Math.round(run.suites.mmlu.accuracy * 100) + '%' : '—' }}</td>
                <td class="num mono">{{ run.suites?.humaneval ? Math.round(run.suites.humaneval.accuracy * 100) + '%' : '—' }}</td>
                <td class="num mono">{{ run.overall_score != null ? Math.round(run.overall_score * 100) + '%' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Runs list -->
      <div v-if="sortedHistory.length" class="history-list">
        <div
          v-for="(run, idx) in sortedHistory"
          :key="run.id"
          class="history-row"
          :class="{ selected: historySelected.has(run.id), latest: idx === 0 }"
        >
          <input
            type="checkbox"
            class="history-check"
            :checked="historySelected.has(run.id)"
            @change="toggleHistorySelect(run.id)"
          />
          <div class="history-main">
            <div class="history-top">
              <span class="latest-badge" v-if="idx === 0">Latest</span>
              <span class="history-model mono">{{ (run.model_id || '').split('/').pop() || '—' }}</span>
              <span class="history-time dim">{{ formatRelTime(run.timestamp) }}</span>
            </div>
            <div class="history-badges">
              <span v-if="run.avg_tps > 0" class="h-badge speed-badge">
                {{ run.avg_tps.toFixed(1) }} t/s
              </span>
              <span v-if="run.suites?.gsm8k" class="h-badge quality-badge"
                :class="run.suites.gsm8k.accuracy >= 0.7 ? 'good' : run.suites.gsm8k.accuracy >= 0.5 ? 'mid' : 'bad'"
              >
                GSM8K {{ Math.round(run.suites.gsm8k.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.mmlu" class="h-badge quality-badge"
                :class="run.suites.mmlu.accuracy >= 0.7 ? 'good' : run.suites.mmlu.accuracy >= 0.5 ? 'mid' : 'bad'"
              >
                MMLU {{ Math.round(run.suites.mmlu.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.humaneval" class="h-badge quality-badge"
                :class="run.suites.humaneval.accuracy >= 0.7 ? 'good' : run.suites.humaneval.accuracy >= 0.5 ? 'mid' : 'bad'"
              >
                HumanEval {{ Math.round(run.suites.humaneval.accuracy * 100) }}%
              </span>
              <span v-if="run.overall_score != null" class="h-badge overall-badge">
                {{ Math.round(run.overall_score * 100) }}% overall
              </span>
            </div>
          </div>
          <div class="history-row-actions">
            <button class="icon-btn danger" title="Delete" @click="modelsStore.deleteBenchmarkResult(run.id)">✕</button>
          </div>
        </div>
      </div>

      <div v-else class="coming-soon-card">
        <h3>No benchmark history yet</h3>
        <p>Run your first benchmark from the Benchmark tab — results appear here automatically.</p>
      </div>
    </div>

    <!-- ── ADVISOR TAB ───────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Advisor'" class="tab-body">
      <div class="coming-soon-card">
        <div class="cs-icon">
          <svg viewBox="0 0 20 20" fill="currentColor" width="28" height="28" aria-hidden="true">
            <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
          </svg>
        </div>
        <h3>AI Advisor</h3>
        <p>
          Describe what you're building — code generation, document summarisation,
          multilingual chat, fast Q&amp;A — and the Advisor will run targeted benchmarks
          across your downloaded models, then recommend the best model and inference
          configuration for that exact task.
        </p>
        <div class="cs-tags">
          <span class="cs-tag">Task matching</span>
          <span class="cs-tag">Auto benchmark</span>
          <span class="cs-tag">Config recommendation</span>
          <span class="cs-tag">Collective data</span>
        </div>
        <p class="cs-note">Coming next release.</p>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ── Layout ──────────────────────────────────────────────────────────────── */
.benchmark-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-5);
}

.page-header { margin-bottom: var(--space-1); }

.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--tx-primary);
  letter-spacing: -.02em;
}
.amp { color: var(--tx-muted); font-weight: 400; }

.page-desc {
  font-size: var(--text-sm);
  color: var(--tx-muted);
  margin: var(--space-1) 0 0;
}

/* ── Tab bar ─────────────────────────────────────────────────────────────── */
.tab-bar-wrap {
  border-bottom: 1px solid var(--bd-default);
  margin-bottom: var(--space-1);
}

.tab-bar {
  display: flex;
  gap: 0;
}

.tab-btn {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--tx-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
  margin-bottom: -1px;
  font-family: inherit;
}

.tab-btn:hover:not(.active) { color: var(--tx-secondary); }

.tab-btn.active {
  color: var(--tx-primary);
  border-bottom-color: var(--si-400);
  font-weight: 600;
}

.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Status banner ───────────────────────────────────────────────────────── */
.status-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 16px;
  border-radius: var(--r-lg);
  font-size: var(--text-sm);
  border: 1px solid transparent;
}
.banner-green  { background: rgba(52,211,153,.08); border-color: rgba(52,211,153,.25); color: #34d399; }
.banner-yellow { background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.25); color: #f59e0b; }
.banner-red    { background: rgba(239,68,68,.08);  border-color: rgba(239,68,68,.2);   color: #f87171; }
.banner-dim    { opacity: .6; }

.banner-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.banner-green  .banner-dot { background: #34d399; box-shadow: 0 0 0 2px rgba(52,211,153,.25); }
.banner-yellow .banner-dot { background: #f59e0b; box-shadow: 0 0 0 2px rgba(245,158,11,.25); }
.banner-red    .banner-dot { background: #f87171; box-shadow: 0 0 0 2px rgba(239,68,68,.2); }

/* ── 8-card metrics grid ─────────────────────────────────────────────────── */
.metrics-grid-8 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

@media (max-width: 900px) { .metrics-grid-8 { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 500px) { .metrics-grid-8 { grid-template-columns: 1fr; } }

.mcard {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
}

.mcard-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.mcard-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--tx-primary);
  line-height: 1.2;
}

/* ── Charts row ──────────────────────────────────────────────────────────── */
.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

@media (max-width: 720px) { .charts-row { grid-template-columns: 1fr; } }

.chart-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  padding: var(--space-4);
}

.chart-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.chart-legend {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  font-size: 11px;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
}

.legend-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.chart-area {
  height: 180px;
  position: relative;
}

.chart-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  color: var(--tx-muted);
}

/* ── Generic panel ───────────────────────────────────────────────────────── */
.panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  background: var(--bg-elevated);
}

.panel-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  flex: 1;
}

.panel-model {
  font-size: 11px;
  color: var(--tx-muted);
}

.panel-count {
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  padding: 1px 8px;
  color: var(--tx-muted);
}

.panel-empty {
  padding: var(--space-4);
  font-size: var(--text-sm);
  color: var(--tx-muted);
}
.panel-empty.warn { color: #f87171; }

/* ── Data table ──────────────────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.data-table th {
  padding: var(--space-2) var(--space-4);
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  border-bottom: 1px solid var(--bd-default);
}

.data-table th.num { text-align: right; }

.data-table td {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  color: var(--tx-secondary);
}

.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,.012); }
.data-table .num { text-align: right; }
.data-table .mono { font-family: var(--font-mono); font-size: 12px; }
.data-table .dim  { color: var(--tx-muted); }

/* ── Cache grid ──────────────────────────────────────────────────────────── */
.cache-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1px;
  background: var(--bd-subtle);
}

.cache-item {
  background: var(--bg-surface);
  padding: var(--space-3) var(--space-4);
}

.cache-key {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: 3px;
}

.cache-val {
  font-size: 12px;
  color: var(--tx-secondary);
  word-break: break-all;
}

/* ── Benchmark tab ───────────────────────────────────────────────────────── */
.bench-config { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.bench-section-label {
  font-size: 10px; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: var(--tx-muted);
}
.bench-checks { display: flex; flex-direction: column; gap: 6px; }

.bench-check {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--bd-default); cursor: pointer;
  transition: background 0.15s;
}
.bench-check:hover { background: var(--bg-elevated); }
.bench-check.checked { border-color: var(--si-400); background: color-mix(in srgb, var(--si-400) 6%, transparent); }
.bench-check input { margin-top: 2px; accent-color: var(--si-400); flex-shrink: 0; }
.bench-check-info { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.bench-check-label { font-weight: 600; font-size: 13px; color: var(--tx-primary); }
.bench-check-desc { font-size: 11px; color: var(--tx-muted); }

.bench-model-list { display: flex; flex-direction: column; gap: 6px; }
.bench-no-models { font-size: 12px; color: var(--tx-muted); padding: 8px 0; }
.bench-model-badge {
  font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
  padding: 2px 6px; border-radius: 4px; background: color-mix(in srgb, var(--si-400) 15%, transparent);
  color: var(--si-400); flex-shrink: 0;
}

.bench-opts-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.opt-label { font-size: 12px; color: var(--tx-secondary); display: flex; align-items: center; gap: 8px; }
.opt-select {
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: 6px; color: var(--tx-primary); padding: 4px 8px; font-size: 12px;
}

.bench-mode-row { display: flex; flex-direction: column; gap: 6px; }
.bench-mode-option {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
  border-radius: 8px; border: 1px solid var(--bd-default); cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.bench-mode-option:hover { background: var(--bg-elevated); }
.bench-mode-option.active { border-color: var(--si-400); background: color-mix(in srgb, var(--si-400) 6%, transparent); }
.bench-mode-option input { margin-top: 2px; accent-color: var(--si-400); flex-shrink: 0; }

.bench-run-row { display: flex; align-items: center; gap: 12px; padding-top: 4px; }

.bench-progress-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-4);
}

.bench-phase-card { display: flex; flex-direction: column; }
.bench-phase-body { padding: 12px 16px; min-height: 60px; }

.phase-badge {
  font-size: 11px; border-radius: 99px; padding: 2px 8px; font-weight: 600;
}
.phase-badge.running {
  background: color-mix(in srgb, var(--si-400) 15%, transparent);
  color: var(--si-400);
  animation: pulse 1.5s infinite;
}
.phase-badge.done {
  background: rgba(52,211,153,.12); color: #34d399;
}
.phase-badge.error {
  background: rgba(239,68,68,.1); color: #f87171;
}

.bench-spin-row {
  display: flex; align-items: center; gap: 10px;
  font-size: 13px; color: var(--tx-muted); padding: 4px 0;
}

.spin {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid var(--bd-default);
  border-top-color: var(--si-400);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Inline speed result */
.speed-result-inline { display: flex; gap: 24px; padding: 4px 0; }
.sri-stat { display: flex; flex-direction: column; gap: 2px; }
.sri-val { font-size: 22px; font-weight: 700; color: var(--tx-primary); line-height: 1.2; }
.sri-label { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); }

/* Quality log + inline scores */
.quality-log {
  background: rgba(0,0,0,.35); color: var(--tx-secondary);
  font-family: var(--font-mono); font-size: 11px; line-height: 1.6;
  padding: 10px 12px; margin: 0; max-height: 240px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-word; border-radius: 0;
}

.quality-scores-inline {
  display: flex; gap: 12px; flex-wrap: wrap; padding: 8px 0 4px;
}
.qsi { text-align: center; min-width: 64px; }
.qsi-name { font-size: 9px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); margin-bottom: 2px; }
.qsi-score { font-size: 20px; font-weight: 700; }
.qsi-score.good { color: #4ade80; }
.qsi-score.mid  { color: #f59e0b; }
.qsi-score.bad  { color: #f87171; }
.qsi-detail { font-size: 10px; color: var(--tx-muted); }
.qsi-overall .qsi-score { font-size: 24px; }
.qsi-speed-row {
  width: 100%; display: flex; gap: 16px; justify-content: center; flex-wrap: wrap;
  padding-top: 10px; margin-top: 8px; border-top: 1px solid var(--bd-subtle);
}
.qsi-speed-stat { display: flex; align-items: baseline; gap: 4px; }
.qsi-speed-val { font-size: 15px; font-weight: 600; color: var(--tx-primary); font-variant-numeric: tabular-nums; }
.qsi-speed-lbl { font-size: 10px; color: var(--tx-muted); }

/* ── History tab ─────────────────────────────────────────────────────────── */
.history-toolbar {
  display: flex; align-items: center;
  justify-content: space-between; gap: 12px;
}
.history-actions { display: flex; gap: 8px; }
.saved-count {
  font-size: 11px; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: var(--tx-muted);
}

.compare-panel { margin-bottom: 0; }

.history-list {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
  display: flex; flex-direction: column;
}

.history-row {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--bd-subtle);
  transition: background 0.12s;
}
.history-row:last-child { border-bottom: none; }
.history-row:hover { background: var(--bg-elevated); }
.history-row.selected { background: color-mix(in srgb, var(--si-400) 5%, transparent); }
.history-row.latest { border-left: 2px solid var(--si-400); }

.history-check {
  margin-top: 4px; flex-shrink: 0; accent-color: var(--si-400);
  width: 14px; height: 14px; cursor: pointer;
}

.history-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.history-top { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }

.latest-badge {
  font-size: 9px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  background: color-mix(in srgb, var(--si-400) 15%, transparent);
  color: var(--si-400); border-radius: 99px; padding: 1px 7px;
}

.history-model { font-size: 13px; font-weight: 600; font-family: var(--font-mono); color: var(--tx-primary); }
.history-time { font-size: 11px; color: var(--tx-muted); }

.history-badges { display: flex; gap: 6px; flex-wrap: wrap; }

.h-badge {
  display: inline-flex; align-items: center;
  font-size: 10px; font-weight: 600;
  padding: 2px 7px; border-radius: var(--r-pill);
  border: 1px solid var(--bd-default);
}

.speed-badge { color: var(--si-400); background: color-mix(in srgb, var(--si-400) 8%, transparent); border-color: color-mix(in srgb, var(--si-400) 25%, transparent); }
.quality-badge.good { color: #4ade80; background: rgba(74,222,128,.08); border-color: rgba(74,222,128,.2); }
.quality-badge.mid  { color: #f59e0b; background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.2); }
.quality-badge.bad  { color: #f87171; background: rgba(248,113,113,.08); border-color: rgba(248,113,113,.2); }
.overall-badge { color: var(--tx-secondary); background: var(--bg-elevated); }

.history-row-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }

/* ── Cost Analysis ───────────────────────────────────────────────────────── */
.cost-panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
}

.cost-body {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.cost-summary-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

@media (max-width: 600px) { .cost-summary-row { grid-template-columns: 1fr; } }

.cost-summary-card {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
}

.cost-summary-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.cost-summary-value {
  font-size: 26px;
  font-weight: 700;
  font-family: var(--font-mono);
  line-height: 1.15;
  margin-bottom: 4px;
}
.cost-summary-value.cu { color: var(--cu-400); }
.cost-summary-value.si { color: var(--si-400); }

.cost-summary-sub {
  font-size: 11px;
  color: var(--tx-muted);
  line-height: 1.5;
}

.cost-skeleton-row {
  height: 20px;
  background: var(--bg-elevated);
  border-radius: var(--r-sm);
  margin-bottom: var(--space-2);
  animation: pulse 1.4s ease-in-out infinite;
}
.cost-skeleton-row.short { width: 55%; }

/* ── Coming soon ─────────────────────────────────────────────────────────── */
.coming-soon-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  padding: var(--space-8) var(--space-6);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
}

.cs-icon {
  width: 52px; height: 52px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  display: flex; align-items: center; justify-content: center;
  color: var(--tx-muted);
}

.coming-soon-card h3 {
  font-size: 16px; font-weight: 700;
  color: var(--tx-primary); margin: 0;
}

.coming-soon-card p {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  max-width: 420px;
  line-height: 1.65;
  margin: 0;
}

.cs-tags { display: flex; gap: var(--space-2); flex-wrap: wrap; justify-content: center; }

.cs-tag {
  font-size: 11px; font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-muted);
}

.cs-note {
  font-size: 12px;
  color: var(--tx-muted);
  font-style: italic;
  margin: 0;
}

/* ── Shared ──────────────────────────────────────────────────────────────── */
.mono { font-family: var(--font-mono); }
.dim  { color: var(--tx-muted); }

.icon-btn {
  background: none; border: none; cursor: pointer;
  color: var(--tx-muted); font-size: 13px; padding: 4px 6px;
  border-radius: var(--r-sm); line-height: 1;
  transition: color 0.15s, background 0.15s;
}
.icon-btn:hover { color: var(--tx-secondary); background: var(--bg-elevated); }
.icon-btn.danger:hover { color: #f87171; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}
</style>
