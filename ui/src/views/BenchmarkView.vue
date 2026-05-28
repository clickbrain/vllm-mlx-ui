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

<!-- Module-level timer state — lives outside setup() so it survives any component
     remount (e.g. if KeepAlive evicts the instance). The timers write into the
     Pinia benchmarkRun store so state is always visible on return. -->
<script lang="ts">
let _qualityPollTimer: ReturnType<typeof setInterval> | null = null
let _speedPollTimer:   ReturnType<typeof setInterval> | null = null
let _customPollTimer:  ReturnType<typeof setInterval> | null = null
let _lineOffset = 0
</script>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick, defineOptions } from 'vue'
import { storeToRefs } from 'pinia'
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
import { useBenchmarkRunStore } from '@/stores/benchmarkRun'
import AppButton from '@/components/shared/AppButton.vue'
import { api } from '@/api/client'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  Filler, Tooltip, Legend,
)

const serverStore = useServerStore()
const modelsStore = useModelsStore()
const benchmarkRunStore = useBenchmarkRunStore()
const {
  benchRunning, speedPhase, qualityPhase, qualityLines,
  benchStopping, qualityRunId, lastRunQuality, lastRunSpeed,
  lastRunModel, lastRunTime,
} = storeToRefs(benchmarkRunStore)

defineOptions({ name: 'BenchmarkView' })

// ── Tab state ─────────────────────────────────────────────────────────────
const tabs = ['Run Tests', 'Live', 'History', 'Advisor'] as const
type Tab = typeof tabs[number]
const activeTab = ref<Tab>('Run Tests')

// ── Live tab — polling ─────────────────────────────────────────────────────
let stopPoll: (() => void) | null = null
let cacheInterval: ReturnType<typeof setInterval> | null = null
const cacheStats = ref<Record<string, unknown> | null>(null)
const cacheError = ref(false)

async function refreshCache() {
  if (!serverStore.isRunning) { cacheStats.value = null; return }
  const result = await serverStore.fetchCacheStats()
  // Only accept if engine_cache is present; soft errors (e.g. mlx_vlm not loaded)
  // are surfaced as a footnote via cacheSoftError
  if (result && result.engine_cache) {
    cacheStats.value = result
    cacheError.value = false
  } else {
    cacheStats.value = null
    cacheError.value = true
  }
}

function _startLivePolling() {
  if (!stopPoll) stopPoll = serverStore.startPolling(3000)
  refreshCache()
  if (!cacheInterval) cacheInterval = setInterval(refreshCache, 15_000)
}

function _stopLivePolling() {
  stopPoll?.()
  stopPoll = null
  if (cacheInterval) { clearInterval(cacheInterval); cacheInterval = null }
}

// First mount: load everything
onMounted(() => {
  _startLivePolling()
  modelsStore.fetchBenchmarkResults()
  modelsStore.fetchModels()
  loadPerfSettings()
  loadBenchEngines()
  // Reconnect poll if benchmark was running when this component was last unmounted
  // (e.g. KeepAlive evicted the instance but the backend job is still going)
  if (benchRunning.value && qualityRunId.value && !_qualityPollTimer) {
    _reconnectQualityPoll(qualityRunId.value)
  }
})

// Navigated back to this page: restart Live polling and refresh history
onActivated(() => {
  _startLivePolling()
  modelsStore.fetchBenchmarkResults()
  loadBenchEngines()
  // Auto-switch to Run Tests tab so the user sees a running benchmark
  if (benchRunning.value) {
    activeTab.value = 'Run Tests'
  }
})

// Navigated away: stop Live polling but leave benchmark polls running
onDeactivated(() => {
  _stopLivePolling()
})

// KeepAlive eviction or full unmount: stop live polling.
// Only stop benchmark polls if no run is active — if a benchmark IS running,
// the module-level timers keep firing and the store retains the state.
onUnmounted(() => {
  _stopLivePolling()
  if (!benchRunning.value) {
    stopBenchmarkPolls()
  }
})

watch(() => serverStore.isRunning, (running) => {
  if (running) {
    refreshCache()
    // Reset so perf settings are re-fetched from the (possibly restarted) server
    perfSettingsLoaded.value = false
  } else { cacheStats.value = null; cacheError.value = false }
})

// ── Live tab — chart data ──────────────────────────────────────────────────
const chartRange = ref<'1h' | '6h' | '24h'>('24h')

const visibleMetricsHistory = computed(() => {
  const h = serverStore.metricsHistory
  if (chartRange.value === '24h') return h
  const pts = chartRange.value === '1h' ? 720 : 4320
  return h.slice(-pts)
})

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
  const h = visibleMetricsHistory.value
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
  const h = visibleMetricsHistory.value
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
const cacheSoftError = computed(() => (cacheStats.value as any)?.error ?? null)

const cacheEntries = computed(() => {
  if (!cacheStats.value) return []
  const ec = (cacheStats.value as any).engine_cache
  const pc = (cacheStats.value as any).prefix_cache
  const rows: { key: string; value: string }[] = []
  const fmt = (v: unknown) => v == null ? '—' : String(v)
  const pct = (v: unknown) => v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`
  if (ec) {
    rows.push({ key: 'Hit Rate',    value: pct(ec.hit_rate) })
    rows.push({ key: 'Hits',        value: fmt(ec.hits) })
    rows.push({ key: 'Misses',      value: fmt(ec.misses) })
    if (ec.entries_used != null) rows.push({ key: 'Entries Used', value: fmt(ec.entries_used) })
    if (ec.memory_used  != null) rows.push({ key: 'Memory Used',  value: fmt(ec.memory_used) })
    if (ec.tokens_saved != null) rows.push({ key: 'Tokens Saved', value: fmt(ec.tokens_saved) })
    if (ec.evictions    != null) rows.push({ key: 'Evictions',    value: fmt(ec.evictions) })
  }
  if (pc) {
    rows.push({ key: 'Prefix Hit Rate', value: pct(pc.hit_rate) })
    rows.push({ key: 'Prefix Hits',     value: fmt(pc.hits) })
    rows.push({ key: 'Prefix Misses',   value: fmt(pc.misses) })
  }
  // Fallback: if neither engine_cache nor prefix_cache is present, display other raw keys
  // (should not happen given refreshCache gating, but keeps the computed robust)
  if (rows.length === 0) {
    for (const [k, v] of Object.entries(cacheStats.value)) {
      if (k === 'error' || k === 'engine_cache' || k === 'prefix_cache') continue
      rows.push({ key: k, value: fmt(v) })
    }
  }
  return rows
})

// ── BENCHMARK TAB — unified Speed + Quality ────────────────────────────────
const QUALITY_SUITES = [
  { id: 'gsm8k',     label: 'GSM8K',     description: 'Math word problems' },
  { id: 'mmlu',      label: 'MMLU',      description: 'Multi-subject knowledge' },
  { id: 'humaneval', label: 'HumanEval', description: 'Python coding tasks' },
  { id: 'math',      label: 'MATH',      description: 'Competition math' },
  { id: 'ifeval',    label: 'IFEval',    description: 'Instruction-following' },
]

// Mode: combined runs quality questions with streaming → captures both accuracy + speed
type BenchMode = 'combined' | 'speed' | 'quality' | 'custom'
const benchMode = ref<BenchMode>('combined')
const BENCH_MODES = [
  { id: 'combined' as BenchMode, label: 'Speed + Quality', description: 'Accuracy & real-world speed in one pass' },
  { id: 'speed'    as BenchMode, label: 'Speed only',      description: 'Throughput & TTFT with synthetic prompts' },
  { id: 'quality'  as BenchMode, label: 'Quality only',    description: 'Accuracy scores (speed captured as bonus)' },
  { id: 'custom'   as BenchMode, label: 'Custom Prompts',  description: 'Your own prompts — TTFT, tok/s, total time per prompt' },
]

// Quality suite selection (shown when mode !== 'speed')
const benchSuites       = ref<string[]>(['gsm8k', 'mmlu', 'humaneval'])
// Speed-only options (shown when mode === 'speed')
const benchMaxTokens    = ref(256)
const benchRuns         = ref(3)
const benchNumQuestions = ref(20)
// Custom prompt options
const customMaxTokens   = ref(2048)
const customEnableThinking = ref(false)

// Engine selector for Run Tests
interface BenchEngineInfo { id: string; name: string; installed: boolean }
const benchEngines = ref<BenchEngineInfo[]>([])
const benchEngineId = ref(serverStore.engineId)

async function loadBenchEngines() {
  try {
    const result = await api.get<{ engines: BenchEngineInfo[] } | BenchEngineInfo[]>('/engines')
    const all: BenchEngineInfo[] = Array.isArray(result) ? result : (result as any).engines ?? []
    benchEngines.value = all.filter(e => e.installed)
  } catch { /* best-effort */ }
}

async function setBenchEngine(id: string) {
  if (id === benchEngineId.value) return
  benchEngineId.value = id
  // Don't write to global config — engine_id is passed per-run so it doesn't corrupt config
}

watch(() => serverStore.engineId, (id) => { benchEngineId.value = id })

// Model selection
const cachedModels = computed(() => modelsStore.models.filter((m: { cached: boolean }) => m.cached))
const benchSelectedModels = ref<string[]>([])

// Model search/filter state (shared between Run Tests and Advisor)
const modelSearch    = ref('')
const modelSizeFilter = ref('all')
const modelQuantFilter = ref('all')

const filteredCachedModels = computed(() => {
  const q = modelSearch.value.trim().toLowerCase()
  return cachedModels.value.filter((m: { id: string; size_gb?: number; quantization?: string }) => {
    if (q && !m.id.toLowerCase().includes(q)) return false
    const gb = m.size_gb ?? 0
    if (modelSizeFilter.value === '<4'  && gb >= 4)   return false
    if (modelSizeFilter.value === '4-8'  && (gb < 4 || gb >= 8))  return false
    if (modelSizeFilter.value === '8-16' && (gb < 8 || gb >= 16)) return false
    if (modelSizeFilter.value === '>16' && gb < 16)  return false
    if (modelQuantFilter.value !== 'all' && m.quantization !== modelQuantFilter.value) return false
    return true
  })
})

const availableQuants = computed(() => {
  const quants = new Set(cachedModels.value.map((m: { quantization?: string }) => m.quantization).filter(Boolean))
  return Array.from(quants).sort()
})

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

function selectAllBenchModels() {
  benchSelectedModels.value = filteredCachedModels.value.map((m: { id: string }) => m.id)
}

function clearBenchModels() {
  benchSelectedModels.value = []
}

// qualityLogRef is a DOM ref — remains local to the component
const qualityLogRef    = ref<HTMLPreElement | null>(null)
// benchRunName is local config, not persistent run state
const benchRunName    = ref('')

// ── Speed output log (streamed from /benchmark/output) ───────────────────────
const speedLines       = ref<string[]>([])
const speedLogRef      = ref<HTMLPreElement | null>(null)
const speedCurrentModel = ref('')
const speedModelIndex  = ref(0)
const speedModelTotal  = ref(0)
let _speedOutputOffset = 0

watch(speedLines, () => {
  nextTick(() => {
    if (speedLogRef.value) speedLogRef.value.scrollTop = speedLogRef.value.scrollHeight
  })
})

// ── Custom prompts state ─────────────────────────────────────────────────────
const customPrompts    = ref<string[]>([''])
const customRunId      = ref<string | null>(null)
const customPhase      = ref<'idle' | 'running' | 'done' | 'error'>('idle')
const customLines      = ref<string[]>([])
const customAllResults = ref<any[]>([])
const customLogRef     = ref<HTMLPreElement | null>(null)
let _customPollTimer: ReturnType<typeof setInterval> | null = null
let _customLineOffset = 0

function addCustomPrompt() { customPrompts.value.push('') }
function removeCustomPrompt(i: number) {
  if (customPrompts.value.length > 1) customPrompts.value.splice(i, 1)
}

interface CustomPromptRow {
  prompt: string
  ttft_ms?: number
  tps?: number | null
  total_ms?: number
  tokens?: number
  buffered?: boolean
  error?: string
}

// Flat list of all per_prompt rows across all models run
const customPerPromptResults = computed<(CustomPromptRow & { model: string })[]>(() => {
  const rows: (CustomPromptRow & { model: string })[] = []
  for (const res of customAllResults.value) {
    for (const row of (res.per_prompt ?? [])) {
      rows.push({ ...row, model: (res.model ?? '').split('/').pop() ?? res.model })
    }
  }
  return rows
})

watch(customLines, () => {
  nextTick(() => {
    if (customLogRef.value) customLogRef.value.scrollTop = customLogRef.value.scrollHeight
  })
})

function stopBenchmarkPolls() {
  if (_qualityPollTimer) { clearInterval(_qualityPollTimer); _qualityPollTimer = null }
  if (_speedPollTimer)   { clearInterval(_speedPollTimer);   _speedPollTimer   = null }
  if (_customPollTimer)  { clearInterval(_customPollTimer);  _customPollTimer  = null }
}

/** Re-attaches the quality poll after a component remount while a run is active. */
function _reconnectQualityPoll(runId: string) {
  _lineOffset = 0  // Reset offset — we re-fetch from the beginning to avoid stale cursor
  _qualityPollTimer = setInterval(async () => {
    try {
      const out = await api.get<{
        running: boolean; lines: string[]; results: any; error: string | null; total_lines: number
      }>(`/quality-benchmark/output/${runId}?since=${_lineOffset}`)
      qualityLines.value.push(...out.lines)
      _lineOffset = out.total_lines
      if (!out.running) {
        clearInterval(_qualityPollTimer!); _qualityPollTimer = null
        qualityPhase.value = out.error ? 'error' : 'done'
        if (out.results) lastRunQuality.value = out.results
        benchRunning.value = false
        modelsStore.fetchBenchmarkResults()
      }
    } catch {
      clearInterval(_qualityPollTimer!); _qualityPollTimer = null
      qualityPhase.value = 'error'
      benchRunning.value = false
    }
  }, 1000)
}

async function stopBenchmark() {
  if (!benchRunning.value) return
  benchStopping.value = true
  try {
    if (qualityRunId.value) {
      await api.post(`/quality-benchmark/stop/${qualityRunId.value}`, {})
    }
    if (customRunId.value) {
      await api.post(`/custom-benchmark/stop/${customRunId.value}`, {})
    }
    await api.post('/benchmark/stop', {}).catch(() => {})
  } catch { /* ignore */ }
  stopBenchmarkPolls()
  benchRunning.value = false
  benchStopping.value = false
  if (qualityPhase.value === 'running') qualityPhase.value = 'error'
  if (speedPhase.value === 'running') speedPhase.value = 'error'
  if (customPhase.value === 'running') customPhase.value = 'error'
}

async function runBenchmark() {
  if (benchRunning.value) return
  if (benchSelectedModels.value.length === 0) return
  if (benchMode.value !== 'speed' && benchMode.value !== 'custom' && benchSuites.value.length === 0) return
  if (benchMode.value === 'custom') {
    const validPrompts = customPrompts.value.map(p => p.trim()).filter(Boolean)
    if (validPrompts.length === 0) return
    return runCustomBenchmark()
  }

  benchRunning.value = true
  speedPhase.value   = 'idle'
  qualityPhase.value = 'idle'
  qualityLines.value = []
  speedLines.value   = []
  speedCurrentModel.value = ''
  speedModelIndex.value = 0
  speedModelTotal.value = 0
  _speedOutputOffset = 0
  qualityRunId.value   = null
  lastRunSpeed.value   = null
  lastRunQuality.value = null
  lastRunModel.value   = benchSelectedModels.value.join(', ')
  lastRunTime.value    = new Date().toLocaleTimeString()

  await applyPerfAndRun(_doBenchmarkRun)
}

async function runCustomBenchmark() {
  const validPrompts = customPrompts.value.map(p => p.trim()).filter(Boolean)
  if (!validPrompts.length) return

  benchRunning.value   = true
  customPhase.value    = 'running'
  customLines.value    = []
  customAllResults.value = []
  customRunId.value    = null
  _customLineOffset    = 0

  try {
    const runData = await api.post<{ ok: boolean; run_id: string }>('/custom-benchmark/run', {
      prompts: validPrompts,
      model_ids: benchSelectedModels.value,
      label: benchRunName.value,
      max_tokens: customMaxTokens.value,
      enable_thinking: customEnableThinking.value,
    })
    customRunId.value = runData.run_id
    _customPollTimer = setInterval(async () => {
      try {
        const out = await api.get<{
          running: boolean; lines: string[]; all_results: any[]; error: string | null; total_lines: number
        }>(`/custom-benchmark/output/${customRunId.value}?since=${_customLineOffset}`)
        customLines.value.push(...out.lines)
        _customLineOffset = out.total_lines
        if (out.all_results?.length) customAllResults.value = out.all_results
        if (!out.running) {
          clearInterval(_customPollTimer!); _customPollTimer = null
          customPhase.value = out.error ? 'error' : 'done'
          benchRunning.value = false
          modelsStore.fetchBenchmarkResults()
        }
      } catch {
        clearInterval(_customPollTimer!); _customPollTimer = null
        customPhase.value = 'error'
        benchRunning.value = false
      }
    }, 1000)
  } catch {
    customPhase.value = 'error'
    benchRunning.value = false
  }
}

async function _doBenchmarkRun() {
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
        label: benchRunName.value,
        engine_id: benchEngineId.value || undefined,
        config: { runs: benchRuns.value, max_tokens: benchMaxTokens.value, prompt: 'Explain the concept of machine learning in simple terms.' },
      })
    } catch {
      speedPhase.value = 'error'
      speedDone = true
      checkDone()
    }
    if (speedPhase.value === 'running') {
      _speedPollTimer = setInterval(async () => {
        try {
          const status = await api.get<{
            running: boolean; current_model?: string; model_index?: number; model_total?: number
          }>('/benchmark/status')
          // Update current model tracking
          if (status.current_model) speedCurrentModel.value = status.current_model
          if (status.model_index) speedModelIndex.value = status.model_index
          if (status.model_total) speedModelTotal.value = status.model_total
          // Pull output lines
          try {
            const out = await api.get<{ running: boolean; lines: string[]; total_lines: number }>(
              `/benchmark/output?since=${_speedOutputOffset}`
            )
            if (out.lines.length) speedLines.value.push(...out.lines)
            _speedOutputOffset = out.total_lines
          } catch { /* output endpoint is optional */ }

          if (!status.running) {
            clearInterval(_speedPollTimer!); _speedPollTimer = null
            speedPhase.value = 'done'
            await modelsStore.fetchBenchmarkResults()
            const hist = modelsStore.benchmarkHistory
            lastRunSpeed.value = hist.length ? hist[hist.length - 1] : null
            speedDone = true
            checkDone()
          }
        } catch {
          clearInterval(_speedPollTimer!); _speedPollTimer = null
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
        label: benchRunName.value,
        model_ids: benchSelectedModels.value,
      })
      const runId = runData.run_id
      qualityRunId.value = runId
      _lineOffset = 0
      _qualityPollTimer = setInterval(async () => {
        try {
          const out = await api.get<{
            running: boolean; lines: string[]; results: any; error: string | null; total_lines: number
          }>(`/quality-benchmark/output/${runId}?since=${_lineOffset}`)
          qualityLines.value.push(...out.lines)
          _lineOffset = out.total_lines
          if (!out.running) {
            clearInterval(_qualityPollTimer!); _qualityPollTimer = null
            qualityPhase.value = out.error ? 'error' : 'done'
            if (out.results) lastRunQuality.value = out.results
            qualityDone = true
            checkDone()
          }
        } catch {
          clearInterval(_qualityPollTimer!); _qualityPollTimer = null
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
  (benchMode.value === 'speed' && lastRunSpeed.value !== null) ||
  (benchMode.value === 'custom' && customPerPromptResults.value.length > 0)
)

// ── PERFORMANCE SETTINGS OVERRIDE ──────────────────────────────────────────
// These let the user run benchmarks with specific server settings, overriding
// the current server config for the duration of the test.
interface PerfSettings {
  continuous_batching: boolean
  paged_kv_cache: boolean
  kv_cache_quantization: boolean
  kv_cache_quantization_bits: number
  gpu_memory_utilization: number
  prefill_step_size: number
}

const showPerfSettings = ref(false)
const perfSettingsLoaded = ref(false)
// Original settings before any override (for restore after benchmark)
const perfOriginal = ref<PerfSettings | null>(null)
// User-editable override values
const perfOverride = ref<PerfSettings>({
  continuous_batching: false,
  paged_kv_cache: false,
  kv_cache_quantization: false,
  kv_cache_quantization_bits: 8,
  gpu_memory_utilization: 90,
  prefill_step_size: 0,
})
const perfApplying = ref(false)
const perfApplyError = ref('')

async function loadPerfSettings() {
  if (perfSettingsLoaded.value) return
  try {
    const cfg = await api.get<Record<string, any>>('/config')
    const s: PerfSettings = {
      continuous_batching: !!cfg.continuous_batching,
      paged_kv_cache: !!cfg.paged_kv_cache,
      kv_cache_quantization: !!cfg.kv_cache_quantization,
      kv_cache_quantization_bits: cfg.kv_cache_quantization_bits ?? 8,
      gpu_memory_utilization: Math.round((cfg.gpu_memory_utilization ?? 0.9) * 100),
      prefill_step_size: cfg.prefill_step_size ?? 0,
    }
    perfOverride.value = { ...s }
    perfOriginal.value = { ...s }
    perfSettingsLoaded.value = true
  } catch { /* ignore */ }
}

const perfChanged = computed(() => {
  if (!perfOriginal.value) return false
  const o = perfOriginal.value
  const n = perfOverride.value
  return o.continuous_batching !== n.continuous_batching
    || o.paged_kv_cache !== n.paged_kv_cache
    || o.kv_cache_quantization !== n.kv_cache_quantization
    || o.kv_cache_quantization_bits !== n.kv_cache_quantization_bits
    || o.gpu_memory_utilization !== n.gpu_memory_utilization
    || o.prefill_step_size !== n.prefill_step_size
})

// Apply perf settings and restart server, wait for it to come back, then call callback
async function applyPerfAndRun(callback: () => Promise<void>) {
  if (!perfChanged.value) { await callback(); return }
  perfApplying.value = true
  perfApplyError.value = ''
  try {
    // Save new settings
    await api.post('/config', {
      continuous_batching: perfOverride.value.continuous_batching,
      paged_kv_cache: perfOverride.value.paged_kv_cache,
      kv_cache_quantization: perfOverride.value.kv_cache_quantization,
      kv_cache_quantization_bits: perfOverride.value.kv_cache_quantization_bits,
      gpu_memory_utilization: perfOverride.value.gpu_memory_utilization / 100,
      prefill_step_size: perfOverride.value.prefill_step_size,
    })
    await api.post('/restart', {})
    // Wait for server to come back (up to 30s)
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 500))
      try {
        const st = await api.get<{ running: boolean }>('/status')
        if (st.running) break
      } catch { /* still restarting */ }
    }
    perfOriginal.value = { ...perfOverride.value }
    await callback()
  } catch (e: any) {
    perfApplyError.value = e?.message ?? 'Failed to apply settings'
    benchRunning.value = false
    speedPhase.value = 'idle'
    qualityPhase.value = 'idle'
  } finally {
    perfApplying.value = false
  }
}

// ── ADVISOR TAB ────────────────────────────────────────────────────────────
const ADVISOR_TASKS = [
  { id: 'code',       label: '💻 Code Generation',   suites: ['humaneval'], speedWeight: 0.3, qualityWeight: 0.7 },
  { id: 'math',       label: '🧮 Math & Reasoning',   suites: ['gsm8k'],     speedWeight: 0.2, qualityWeight: 0.8 },
  { id: 'knowledge',  label: '📚 Knowledge / Q&A',    suites: ['mmlu'],      speedWeight: 0.3, qualityWeight: 0.7 },
  { id: 'fast',       label: '⚡ Fast Responses',      suites: [],            speedWeight: 0.9, qualityWeight: 0.1 },
  { id: 'general',    label: '🌐 General Purpose',     suites: ['gsm8k','mmlu','humaneval'], speedWeight: 0.4, qualityWeight: 0.6 },
  { id: 'summarise',  label: '📝 Summarisation',       suites: ['mmlu'],      speedWeight: 0.4, qualityWeight: 0.6 },
] as const

type AdvisorTaskId = typeof ADVISOR_TASKS[number]['id']

const advisorTask       = ref<AdvisorTaskId>('general')
const advisorModels     = ref<string[]>([])
const advisorRunning    = ref(false)
const advisorDone       = ref(false)
const advisorLines      = ref<string[]>([])
const advisorRunId      = ref<string | null>(null)
const advisorResults    = ref<Record<string, any> | null>(null)
const advisorSpeedResults = ref<any[]>([])
let advisorPollTimer: ReturnType<typeof setInterval> | null = null

const advisorTaskDef = computed(() => ADVISOR_TASKS.find(t => t.id === advisorTask.value)!)

// Seed advisor models with all cached models
watch(cachedModels, (models) => {
  if (advisorModels.value.length === 0 && models.length > 0) {
    advisorModels.value = models.map((m: { id: string }) => m.id)
  }
}, { immediate: true })

function toggleAdvisorModel(id: string) {
  const idx = advisorModels.value.indexOf(id)
  if (idx === -1) advisorModels.value.push(id)
  else advisorModels.value.splice(idx, 1)
}

function selectAllAdvisorModels() {
  advisorModels.value = filteredCachedModels.value.map((m: { id: string }) => m.id)
}

function clearAdvisorModels() {
  advisorModels.value = []
}

// Score a model based on quality + speed results
function scoreModel(modelId: string): { score: number; quality: number; speed: number } {
  const taskDef = advisorTaskDef.value
  let qualityScore = 0
  let speedScore = 0

  // Quality from last advisor run results
  if (advisorResults.value?.suites) {
    const suites = advisorResults.value.suites as Record<string, any>
    const relevant = taskDef.suites.filter(s => suites[s])
    if (relevant.length > 0) {
      qualityScore = relevant.reduce((acc, s) => acc + (suites[s]?.accuracy ?? 0), 0) / relevant.length
    }
  }

  // Speed from speed benchmark results
  const speedResult = advisorSpeedResults.value.find((r: any) => r.model_id === modelId || r.model === modelId)
  if (speedResult?.avg_tps) {
    // Normalise: 50 tok/s = 1.0, scale linearly
    speedScore = Math.min(1, speedResult.avg_tps / 50)
  }

  const score = qualityScore * taskDef.qualityWeight + speedScore * taskDef.speedWeight
  return { score, quality: qualityScore, speed: speedScore }
}

interface AdvisorModelResult {
  id: string
  label: string
  score: number
  quality: number
  speed: number
  speedRaw: number
  recommendation: string
}

const advisorRankings = computed((): AdvisorModelResult[] => {
  if (!advisorDone.value) return []
  return advisorModels.value.map(id => {
    const s = scoreModel(id)
    const speedResult = advisorSpeedResults.value.find((r: any) => r.model_id === id || r.model === id)
    return {
      id,
      label: id.split('/').pop() ?? id,
      score: s.score,
      quality: s.quality,
      speed: s.speed,
      speedRaw: speedResult?.avg_tps ?? 0,
      recommendation: getAdvisorRec(id, s),
    }
  }).sort((a, b) => b.score - a.score)
})

function getAdvisorRec(modelId: string, scores: { score: number; quality: number; speed: number }): string {
  const name = modelId.toLowerCase()
  const isSmall = /0\.[0-9]b|1[bB]|2[bB]/.test(name)
  const isMed = /7[bB]|8[bB]/.test(name)
  const recs: string[] = []
  if (scores.quality > 0.7) recs.push('high accuracy')
  else if (scores.quality < 0.4) recs.push('limited accuracy')
  if (scores.speedRaw > 40) recs.push('fast generation')
  else if (scores.speedRaw > 0 && scores.speedRaw < 20) recs.push('slower generation')
  if (isSmall) recs.push('low memory')
  if (isMed) recs.push('balanced')
  return recs.length ? recs.join(' · ') : 'good all-rounder'
}

async function runAdvisorAnalysis() {
  if (advisorRunning.value || advisorModels.value.length === 0) return
  advisorRunning.value = true
  advisorDone.value = false
  advisorLines.value = []
  advisorResults.value = null
  advisorSpeedResults.value = []
  advisorRunId.value = null

  const taskDef = advisorTaskDef.value

  try {
    // 1. Run quality benchmark if task has suites
    if (taskDef.suites.length > 0) {
      advisorLines.value.push(`→ Running ${taskDef.suites.join(', ').toUpperCase()} benchmarks…\n`)
      const runData = await api.post<{ ok: boolean; run_id: string }>('/quality-benchmark/run', {
        suites: [...taskDef.suites],
        num_questions: 10,
        label: `advisor:${taskDef.id}`,
      })
      advisorRunId.value = runData.run_id
      let offset = 0
      await new Promise<void>((resolve) => {
        advisorPollTimer = setInterval(async () => {
          try {
            const out = await api.get<{ running: boolean; lines: string[]; results: any; total_lines: number }>(
              `/quality-benchmark/output/${runData.run_id}?since=${offset}`
            )
            advisorLines.value.push(...out.lines)
            offset = out.total_lines
            if (!out.running) {
              clearInterval(advisorPollTimer!); advisorPollTimer = null
              if (out.results) advisorResults.value = out.results
              resolve()
            }
          } catch { clearInterval(advisorPollTimer!); advisorPollTimer = null; resolve() }
        }, 1000)
      })
    }

    // 2. Run speed benchmark for all selected models (if task cares about speed)
    if (taskDef.speedWeight > 0.2) {
      advisorLines.value.push(`\n→ Running speed benchmarks for ${advisorModels.value.length} model(s)…\n`)
      await api.post('/benchmark/run', {
        model_ids: advisorModels.value,
        label: `advisor:${taskDef.id}:speed`,
        engine_id: benchEngineId.value || undefined,
        config: { runs: 2, max_tokens: 256 },
      })
      await new Promise<void>((resolve) => {
        const t = setInterval(async () => {
          try {
            const status = await api.get<{ running: boolean }>('/benchmark/status')
            if (!status.running) {
              clearInterval(t)
              await modelsStore.fetchBenchmarkResults()
              const hist = modelsStore.benchmarkHistory ?? []
              // Get the most recent speed results for our models
              advisorModels.value.forEach(id => {
                const r = [...hist].reverse().find((h: any) => h.model_id === id || h.model === id)
                if (r) advisorSpeedResults.value.push(r)
              })
              resolve()
            }
          } catch { clearInterval(t); resolve() }
        }, 1500)
      })
    }

    advisorDone.value = true
    advisorLines.value.push('\n✓ Analysis complete\n')
  } catch (e: any) {
    advisorLines.value.push(`\n✗ Error: ${e?.message ?? 'Unknown error'}\n`)
  } finally {
    advisorRunning.value = false
  }
}

function stopAdvisor() {
  if (advisorPollTimer) { clearInterval(advisorPollTimer); advisorPollTimer = null }
  if (advisorRunId.value) {
    api.post(`/quality-benchmark/stop/${advisorRunId.value}`, {}).catch(() => {})
  }
  api.post('/benchmark/stop', {}).catch(() => {})
  advisorRunning.value = false
}

// Most-recent first; loaded by onMounted
const sortedHistory = computed(() => {
  let list = [...(modelsStore.benchmarkHistory ?? [])].sort((a, b) =>
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  )
  if (historySearch.value.trim()) {
    const q = historySearch.value.toLowerCase()
    list = list.filter(r =>
      (r.model_id || '').toLowerCase().includes(q) ||
      (r.label || '').toLowerCase().includes(q)
    )
  }
  if (historyTypeFilter.value !== 'all') {
    list = list.filter(r => r.benchmark_type === historyTypeFilter.value)
  }
  return list
})

const historySelected = ref<Set<number>>(new Set())
const historySearch  = ref('')
const historyTypeFilter = ref<'all' | 'speed' | 'quality' | 'custom'>('all')
const comparePanelRef = ref<HTMLElement | null>(null)
const detailPanelRef  = ref<HTMLElement | null>(null)

function toggleHistorySelect(id: number) {
  const s = new Set(historySelected.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  historySelected.value = s
}

function scrollToCompare() {
  nextTick(() => comparePanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

function scrollToDetail() {
  nextTick(() => detailPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

const compareRuns = computed(() =>
  sortedHistory.value.filter(r => historySelected.value.has(r.id))
)

const selectedRun = computed(() =>
  historySelected.value.size === 1
    ? sortedHistory.value.find(r => historySelected.value.has(r.id)) ?? null
    : null
)

/** Returns true when a custom run was recorded before the tok/s fix in v0.3.80. */
function hasStaleMetrics(run: { benchmark_type?: string; dashboard_version?: string }): boolean {
  if (run.benchmark_type !== 'custom') return false
  if (!run.dashboard_version) return true
  const m = run.dashboard_version.match(/^v?(\d+)\.(\d+)\.(\d+)/)
  if (!m) return true
  const v = [Number(m[1]), Number(m[2]), Number(m[3])]
  const fix = [0, 3, 80]
  for (let i = 0; i < 3; i++) {
    if (v[i] < fix[i]) return true
    if (v[i] > fix[i]) return false
  }
  return false
}

function formatRelTime(ts: string): string {
  if (!ts) return '—'
  const diff = Date.now() - new Date(ts).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)   return 'just now'
  if (s < 3600) return `${Math.floor(s/60)}m ago`
  if (s < 86400) return `${Math.floor(s/3600)}h ago`
  return new Date(ts).toLocaleDateString()
}

// ── Export helpers ─────────────────────────────────────────────────────────────

function exportCSV() {
  const rows = sortedHistory.value
  if (!rows.length) return
  const headers = ['model_id', 'engine_id', 'benchmark_type', 'timestamp', 'label', 'avg_tps', 'avg_ttft_ms', 'max_tokens', 'overall_score']
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  let csv = headers.join(',') + '\n'
  for (const r of rows) {
    csv += headers.map(h => esc((r as any)[h] ?? '')).join(',') + '\n'
  }
  _downloadBlob(csv, 'benchmarks.csv', 'text/csv')
}

function exportJSON() {
  const blob = JSON.stringify(sortedHistory.value, null, 2)
  _downloadBlob(blob, 'benchmarks.json', 'application/json')
}

function _downloadBlob(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── Sort state for comparison table ────────────────────────────────────────────

const compareSortCol = ref<string | null>(null)
const compareSortDir = ref<'asc' | 'desc'>('desc')

function toggleCompareSort(col: string) {
  if (compareSortCol.value === col) {
    compareSortDir.value = compareSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    compareSortCol.value = col
    compareSortDir.value = 'desc'
  }
}

const sortedCompareRuns = computed(() => {
  const col = compareSortCol.value
  if (!col) return compareRuns.value
  const dir = compareSortDir.value === 'asc' ? 1 : -1
  return [...compareRuns.value].sort((a, b) => {
    const va = (a as any)[col]
    const vb = (b as any)[col]
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'number') return dir * (va - vb)
    if (col === 'timestamp') return dir * (new Date(va).getTime() - new Date(vb).getTime())
    return dir * String(va).localeCompare(String(vb))
  })
})

function s(active: boolean, dir: string) {
  return { active, asc: active && dir === 'asc', desc: active && dir === 'desc' }
}

// ── History helpers ───────────────────────────────────────────────────────────
watch(activeTab, (tab) => {
  if (tab === 'History') {
    modelsStore.fetchBenchmarkResults()
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
        >
          {{ tab }}
          <span v-if="tab === 'Run Tests' && benchRunning" class="tab-run-dot" />
        </button>
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
          <div class="chart-header">
            <div class="chart-title">Requests over time</div>
            <div class="chart-range-btns">
              <button v-for="r in ['1h','6h','24h']" :key="r" class="chart-range-btn" :class="{ active: chartRange === r }" @click="chartRange = r as any">{{ r }}</button>
            </div>
          </div>
          <div class="chart-legend">
            <span class="legend-dot" style="background:#a78bfa" />Active
            <span class="legend-dot" style="background:#f59e0b" />Queued
          </div>
          <div class="chart-area">
            <Line
              v-if="visibleMetricsHistory.length > 1"
              :data="requestsChartData"
              :options="lineOpts"
            />
            <div v-else class="chart-empty">Waiting for data…</div>
          </div>
        </div>

        <div class="chart-card">
          <div class="chart-header">
            <div class="chart-title">GPU memory (GB)</div>
            <div class="chart-range-btns">
              <button v-for="r in ['1h','6h','24h']" :key="r" class="chart-range-btn" :class="{ active: chartRange === r }" @click="chartRange = r as any">{{ r }}</button>
            </div>
          </div>
          <div class="chart-area">
            <Line
              v-if="visibleMetricsHistory.length > 1"
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
            <div class="cache-val mono">{{ entry.value }}</div>
          </div>
          <div v-if="cacheSoftError" class="cache-note">{{ cacheSoftError }}</div>
        </div>
        <div v-else-if="cacheError" class="panel-empty warn">Cache stats unavailable.</div>
        <div v-else class="panel-empty">
          {{ serverStore.isRunning ? 'Loading…' : 'Server not running.' }}
        </div>
      </div>
    </div>

    <!-- ── BENCHMARK TAB ──────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Run Tests'" class="tab-body">

      <!-- Server warning: show advisory only; benchmark auto-starts server for each model -->
      <div v-if="!serverStore.isRunning" class="status-banner banner-yellow">
        <span class="banner-dot" />
        <span>Server not running — it will be started automatically for each model when the benchmark begins.</span>
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
          <div class="bench-cols">

            <!-- Left column: model selection -->
            <div class="bench-col bench-col-left">
              <div class="bench-step">
                <span class="bench-step-num">1</span>
                <span class="bench-step-title">Select models</span>
              </div>
              <div v-if="cachedModels.length === 0" class="bench-no-models">
                No downloaded models found — download a model on the Models page first.
              </div>
              <template v-else>
                <!-- Search + filter bar -->
                <div class="model-filter-bar">
                  <div class="model-search-wrap">
                    <svg class="model-search-icon" viewBox="0 0 16 16" fill="none"><circle cx="6.5" cy="6.5" r="4" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                    <input
                      v-model="modelSearch"
                      class="model-search-input"
                      placeholder="Search models…"
                      :disabled="benchRunning"
                    />
                    <button v-if="modelSearch" class="model-search-clear" @click="modelSearch = ''" :disabled="benchRunning">×</button>
                  </div>
                  <div class="model-filter-row">
                    <select v-model="modelSizeFilter" class="model-filter-select" :disabled="benchRunning">
                      <option value="all">All sizes</option>
                      <option value="<4">&lt; 4 GB</option>
                      <option value="4-8">4 – 8 GB</option>
                      <option value="8-16">8 – 16 GB</option>
                      <option value=">16">&gt; 16 GB</option>
                    </select>
                    <select v-model="modelQuantFilter" class="model-filter-select" :disabled="benchRunning">
                      <option value="all">All quant</option>
                      <option v-for="q in availableQuants" :key="q" :value="q">{{ q }}</option>
                    </select>
                  </div>
                  <div class="model-filter-actions">
                    <span class="model-filter-count">{{ filteredCachedModels.length }} of {{ cachedModels.length }}</span>
                    <button class="model-filter-link" :disabled="benchRunning" @click="selectAllBenchModels">All</button>
                    <button class="model-filter-link" :disabled="benchRunning" @click="clearBenchModels">None</button>
                  </div>
                </div>

                <div v-if="filteredCachedModels.length === 0" class="bench-no-models">
                  No models match the current filters.
                </div>
                <div v-else class="bench-model-list">
                  <label
                    v-for="m in filteredCachedModels"
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
                      <span class="bench-check-desc">{{ m.id.split('/')[0] }} &middot; {{ m.size_gb?.toFixed(1) ?? '?' }} GB &middot; {{ m.quantization }}</span>
                    </div>
                    <span v-if="benchRunning && benchSelectedModels.includes(m.id)" class="bench-model-badge" :class="speedCurrentModel && m.id === speedCurrentModel ? '' : (serverStore.modelId && m.id === serverStore.modelId ? '' : 'badge-pending')">
                     {{ (speedCurrentModel && m.id === speedCurrentModel) || (!speedCurrentModel && m.id === serverStore.modelId) ? 'running' : 'queued' }}
                    </span>
                    <span v-else-if="!benchRunning && m.id === serverStore.modelId" class="bench-model-badge">loaded</span>
                  </label>
                </div>
              </template>
            </div>

            <!-- Divider -->
            <div class="bench-col-divider" />

            <!-- Right column: test configuration -->
            <div
              class="bench-col bench-col-right"
              :class="{ 'bench-col-locked': benchSelectedModels.length === 0 && cachedModels.length > 0 }"
            >
              <div class="bench-step">
                <span class="bench-step-num">2</span>
                <span class="bench-step-title">Configure &amp; run</span>
                <span v-if="benchSelectedModels.length === 0 && cachedModels.length > 0" class="bench-needs-model">
                  ← select a model first
                </span>
              </div>

              <!-- Engine selector -->
              <div v-if="benchEngines.length > 1" class="bench-section-label">Inference Engine</div>
              <div v-if="benchEngines.length > 1" class="bench-engine-row">
                <select
                  class="bench-engine-select"
                  :value="benchEngineId"
                  :disabled="benchRunning"
                  @change="setBenchEngine(($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="e in benchEngines" :key="e.id" :value="e.id">{{ e.name }}</option>
                </select>
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

              <!-- Quality suite checkboxes (hidden for speed-only or custom mode) -->
              <template v-if="benchMode !== 'speed' && benchMode !== 'custom'">
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
                    <option :value="1024">1024</option>
                    <option :value="2048">2048</option>
                    <option :value="4096">4096</option>
                  </select>
                </label>
                <label v-if="benchMode !== 'speed' && benchMode !== 'custom'" class="opt-label">
                  Questions / suite
                  <select v-model="benchNumQuestions" :disabled="benchRunning" class="opt-select">
                    <option :value="5">5 (quick)</option>
                    <option :value="10">10</option>
                    <option :value="20">20</option>
                    <option :value="25">25 (full)</option>
                  </select>
                </label>
              </div>

              <!-- Custom prompts editor -->
              <template v-if="benchMode === 'custom'">
                <div class="bench-section-label">Prompts</div>
                <div class="custom-prompts-list">
                  <div
                    v-for="(_, i) in customPrompts"
                    :key="i"
                    class="custom-prompt-row"
                  >
                    <span class="custom-prompt-num">{{ i + 1 }}</span>
                    <textarea
                      v-model="customPrompts[i]"
                      class="custom-prompt-input"
                      :placeholder="`Prompt ${i + 1}…`"
                      rows="2"
                      :disabled="benchRunning"
                    />
                    <button
                      class="custom-prompt-remove"
                      :disabled="customPrompts.length <= 1 || benchRunning"
                      @click="removeCustomPrompt(i)"
                      title="Remove prompt"
                    >×</button>
                  </div>
                </div>
                <button class="custom-prompt-add" :disabled="benchRunning" @click="addCustomPrompt">
                  + Add prompt
                </button>
                <div class="bench-section-label" style="margin-top:10px">Max tokens <span class="opt-hint">(per prompt)</span></div>
                <select v-model="customMaxTokens" :disabled="benchRunning" class="opt-select">
                  <option :value="512">512</option>
                  <option :value="1024">1024</option>
                  <option :value="2048">2048 (default)</option>
                  <option :value="4096">4096</option>
                </select>
                <label class="thinking-toggle-row" :class="{ disabled: benchRunning }">
                  <input type="checkbox" v-model="customEnableThinking" :disabled="benchRunning" />
                  Enable thinking mode
                  <span class="opt-hint">(off = faster, accurate metrics)</span>
                </label>
              </template>

              <!-- Run name -->
              <div class="bench-section-label">Run name <span class="opt-hint">(optional)</span></div>
              <input
                v-model="benchRunName"
                type="text"
                class="bench-name-input"
                placeholder="e.g. baseline, after-tuning…"
                :disabled="benchRunning"
              />

              <!-- Performance settings override -->
              <div class="perf-toggle-row" @click="showPerfSettings = !showPerfSettings; loadPerfSettings()">
                <svg class="perf-chevron" :class="{ open: showPerfSettings }" viewBox="0 0 16 16" fill="currentColor" width="13" height="13"><path d="M4 6l4 4 4-4"/></svg>
                <span class="bench-section-label" style="cursor:pointer;margin:0">Performance Settings</span>
                <span v-if="perfChanged" class="perf-override-badge">overridden</span>
              </div>
              <div v-if="showPerfSettings" class="perf-settings-panel">
                <div class="perf-row">
                  <label class="perf-toggle">
                    <input type="checkbox" v-model="perfOverride.continuous_batching" :disabled="benchRunning" />
                    <span class="perf-label">Continuous Batching</span>
                  </label>
                  <p class="perf-desc">
                    Processes multiple requests simultaneously instead of one at a time. Dramatically improves throughput when multiple users or prompts are queued — often 3–5× faster overall. Slight latency increase per individual request.
                    <a href="https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/guides/continuous-batching.md" target="_blank" rel="noopener" class="perf-link">Learn more ↗</a>
                  </p>
                </div>
                <div class="perf-row">
                  <label class="perf-toggle">
                    <input type="checkbox" v-model="perfOverride.paged_kv_cache" :disabled="benchRunning" />
                    <span class="perf-label">Paged KV Cache</span>
                  </label>
                  <p class="perf-desc">
                    Manages the attention key/value cache in fixed-size pages (like virtual memory), eliminating wasted reserved space. Enables longer contexts and higher concurrency. Required for continuous batching to reach its full benefit.
                    <a href="https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/guides/continuous-batching.md#paged-kv-cache" target="_blank" rel="noopener" class="perf-link">Learn more ↗</a>
                  </p>
                </div>
                <div class="perf-row">
                  <label class="perf-toggle">
                    <input type="checkbox" v-model="perfOverride.kv_cache_quantization" :disabled="benchRunning" />
                    <span class="perf-label">KV Cache Quantization</span>
                  </label>
                  <p class="perf-desc">
                    Compresses the KV cache to lower precision, reducing memory usage by up to 50%. Allows larger context windows or more concurrent sessions on the same hardware. Tiny quality reduction — often imperceptible.
                    <a href="https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/reference/configuration.md#kv-cache" target="_blank" rel="noopener" class="perf-link">Learn more ↗</a>
                  </p>
                  <div v-if="perfOverride.kv_cache_quantization" class="perf-bits-row">
                    <span class="perf-label">Quantization bits</span>
                    <select v-model.number="perfOverride.kv_cache_quantization_bits" :disabled="benchRunning" class="opt-select">
                      <option :value="8">8-bit (less compression, best quality)</option>
                      <option :value="4">4-bit (more compression, slight quality loss)</option>
                    </select>
                  </div>
                </div>
                <div class="perf-row perf-row-inline">
                  <span class="perf-label">GPU Memory Utilization</span>
                  <input type="number" v-model.number="perfOverride.gpu_memory_utilization" min="10" max="100" step="5" class="perf-num-input" :disabled="benchRunning" />
                  <span class="perf-unit">%</span>
                  <p class="perf-desc" style="flex-basis:100%">
                    The fraction of Apple Silicon unified memory allocated to the model and KV cache. Higher = more memory for the model (longer context, bigger model fits), but leaves less for the OS and other apps. 75–90% is safe for most setups.
                    <a href="https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/reference/configuration.md" target="_blank" rel="noopener" class="perf-link">Learn more ↗</a>
                  </p>
                </div>
                <div class="perf-row perf-row-inline">
                  <span class="perf-label">Prefill Step Size</span>
                  <input type="number" v-model.number="perfOverride.prefill_step_size" min="0" max="4096" step="64" class="perf-num-input" :disabled="benchRunning" />
                  <span class="perf-unit">tokens</span>
                  <p class="perf-desc" style="flex-basis:100%">
                    How many tokens are processed per chunk during the initial prompt ingestion (prefill) phase. Larger = faster prefill but higher peak memory and first-token latency. <strong>0 = auto</strong> (engine chooses). Only tune if you see memory spikes on very long prompts.
                    <a href="https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/reference/configuration.md" target="_blank" rel="noopener" class="perf-link">Learn more ↗</a>
                  </p>
                </div>
                <p v-if="perfChanged" class="perf-warn">
                  ⚠ These settings differ from the current server config. The server will restart before the benchmark runs (~5–10s).
                </p>
                <p v-if="perfApplyError" class="perf-error">{{ perfApplyError }}</p>
                <button v-if="perfChanged" class="perf-reset-btn" @click="perfOverride = { ...perfOriginal! }" :disabled="benchRunning">Reset to current</button>
              </div>

              <!-- Run button -->
              <div class="bench-run-row">
                <AppButton
                  :disabled="perfApplying || benchRunning || benchSelectedModels.length === 0 || (benchMode !== 'speed' && benchMode !== 'custom' && benchSuites.length === 0) || (benchMode === 'custom' && customPrompts.filter(p => p.trim()).length === 0)"
                  @click="runBenchmark"
                >
                  <span v-if="perfApplying || benchRunning" class="spin" style="margin-right:6px" />
                  {{ perfApplying ? 'Applying settings…' : benchRunning ? 'Running…' : 'Run Benchmarks' }}
                </AppButton>
                <AppButton
                  v-if="benchRunning"
                  variant="secondary"
                  :disabled="benchStopping"
                  @click="stopBenchmark"
                >
                  {{ benchStopping ? 'Stopping…' : 'Stop Run' }}
                </AppButton>
              </div>

              <!-- Inline quality log -->
              <div v-if="benchMode !== 'speed' && (qualityPhase !== 'idle' || qualityLines.length > 0)" class="inline-log-wrap">
                <pre ref="qualityLogRef" class="quality-log">{{ qualityLines.join('') }}</pre>
                <div v-if="qualityPhase === 'done' && lastRunQuality" class="quality-scores-inline">
                  <div v-for="(sr, key) in lastRunQuality.suites" :key="key" class="qsi">
                    <div class="qsi-name">{{ String(key).toUpperCase() }}</div>
                    <div class="qsi-score" :class="(sr as QualitySuiteResult).accuracy >= 0.7 ? 'good' : (sr as QualitySuiteResult).accuracy >= 0.5 ? 'mid' : 'bad'">
                      {{ Math.round((sr as QualitySuiteResult).accuracy * 100) }}%
                    </div>
                    <div v-if="(sr as QualitySuiteResult).accuracy_ci_95" class="qsi-ci dim">
                      ±{{ Math.round((((sr as QualitySuiteResult).accuracy_ci_95[1] - (sr as QualitySuiteResult).accuracy_ci_95[0]) / 2) * 100) }}%
                    </div>
                    <div class="qsi-detail dim">{{ (sr as QualitySuiteResult).correct }}/{{ (sr as QualitySuiteResult).total }}</div>
                  </div>
                  <div class="qsi qsi-overall">
                    <div class="qsi-name">Overall</div>
                    <div class="qsi-score" :class="lastRunQuality.overall_score >= 0.7 ? 'good' : lastRunQuality.overall_score >= 0.5 ? 'mid' : 'bad'">
                      {{ Math.round(lastRunQuality.overall_score * 100) }}%
                    </div>
                  </div>
                  <div v-if="lastRunQuality.overall_speed?.avg_tokens_per_sec" class="qsi-speed-row">
                    <span class="qsi-speed-stat">
                      <span class="qsi-speed-val">{{ lastRunQuality.overall_speed.avg_tokens_per_sec }}</span>
                      <span class="qsi-speed-lbl">tok/s</span>
                    </span>
                    <span v-if="lastRunQuality.overall_speed.avg_ttft_ms != null" class="qsi-speed-stat">
                      <span class="qsi-speed-val">{{ lastRunQuality.overall_speed.avg_ttft_ms }}</span>
                      <span class="qsi-speed-lbl">ms TTFT</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>

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
              <span class="dim">
                {{ speedCurrentModel ? `Benchmarking: ${speedCurrentModel.split('/').pop()}${speedModelTotal > 1 ? ` (${speedModelIndex}/${speedModelTotal})` : ''}` : 'Starting benchmark…' }}
              </span>
            </div>
            <!-- Live output log during speed run -->
            <pre v-if="speedLines.length" ref="speedLogRef" class="quality-log speed-log">{{ speedLines.join('') }}</pre>
            <div v-else-if="speedPhase === 'done' && lastRunSpeed" class="speed-result-inline">
              <div class="sri-stat">
                <div class="sri-val mono">{{ (lastRunSpeed as any).avg_tps?.toFixed(1) ?? '—' }}</div>
                <div class="sri-label">avg t/s</div>
              </div>
              <div v-if="(lastRunSpeed as any).avg_ttft_ms != null" class="sri-stat">
                <div class="sri-val mono">{{ Math.round((lastRunSpeed as any).avg_ttft_ms) }}ms</div>
                <div class="sri-label">avg TTFT</div>
              </div>
            </div>
            <div v-else-if="speedPhase === 'error'" class="panel-empty warn">Speed benchmark failed.</div>
          </div>
        </div>

        <!-- Custom benchmark progress + results -->
        <div v-if="benchMode === 'custom'" class="panel bench-phase-card bench-phase-card--wide">
          <div class="panel-header">
            <div class="panel-title">Custom Prompts</div>
            <span class="phase-badge" :class="customPhase">
              {{ customPhase === 'running' ? 'Running…' : customPhase === 'done' ? 'Done' : customPhase === 'error' ? 'Error' : '' }}
            </span>
          </div>
          <div class="bench-phase-body">
            <div v-if="customPhase === 'running'" class="bench-spin-row">
              <span class="spin" />
              <span class="dim">Running custom prompts…</span>
            </div>

            <!-- Live log during run -->
            <pre v-if="customLines.length" ref="customLogRef" class="quality-log custom-log">{{ customLines.join('') }}</pre>

            <!-- Per-prompt results table after done -->
            <div v-if="customPhase === 'done' && customPerPromptResults.length" class="custom-results-wrap">
              <table class="data-table custom-results-table">
                <thead>
                  <tr>
                    <th v-if="benchSelectedModels.length > 1">Model</th>
                    <th>Prompt</th>
                    <th class="num">TTFT</th>
                    <th class="num">Tok/s</th>
                    <th class="num">Total</th>
                    <th class="num">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in customPerPromptResults" :key="i" :class="{ 'row-error': row.error }">
                    <td v-if="benchSelectedModels.length > 1" class="mono dim">{{ row.model }}</td>
                    <td class="custom-prompt-cell" :title="row.prompt">{{ row.prompt.length > 60 ? row.prompt.slice(0, 60) + '…' : row.prompt }}</td>
                    <td class="num mono">{{ row.ttft_ms != null ? Math.round(row.ttft_ms) + 'ms' : '—' }}</td>
                    <td class="num mono">
                      <span v-if="row.tps != null">{{ row.tps.toFixed(1) }}</span>
                      <span v-else-if="row.buffered" class="dim" title="Buffered stream — TPS not measurable">n/a</span>
                      <span v-else>—</span>
                    </td>
                    <td class="num mono">{{ row.total_ms != null ? Math.round(row.total_ms) + 'ms' : '—' }}</td>
                    <td class="num mono">{{ row.tokens ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="customPhase === 'error'" class="panel-empty warn">Custom benchmark failed.</div>
          </div>
        </div>

      </div>

    </div>

    <!-- ── HISTORY TAB ────────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'History'" class="tab-body">

      <!-- Filter bar -->
      <div class="history-filter-bar">
        <input
          v-model="historySearch"
          type="text"
          class="history-search"
          placeholder="Search by model or name…"
        />
        <div class="hf-type-btns">
          <button
            v-for="t in ['all', 'speed', 'quality', 'custom']"
            :key="t"
            class="hf-btn"
            :class="{ active: historyTypeFilter === t }"
            @click="historyTypeFilter = t as any"
          >{{ t === 'all' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1) }}</button>
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
            @click="scrollToCompare"
          >
            Compare {{ historySelected.size }} runs
          </AppButton>
          <AppButton
            v-else-if="historySelected.size === 1"
            variant="secondary"
            size="sm"
            @click="scrollToDetail"
          >
            View details
          </AppButton>
          <AppButton variant="ghost" size="sm" @click="exportCSV">Export CSV</AppButton>
          <AppButton variant="ghost" size="sm" @click="exportJSON">Export JSON</AppButton>
          <AppButton
            variant="ghost"
            size="sm"
            @click="modelsStore.clearAllBenchmarks?.()"
          >
            Clear all
          </AppButton>
        </div>
      </div>

      <!-- Comparison table (2+ selected) -->
      <div ref="comparePanelRef" v-if="compareRuns.length >= 2" class="panel compare-panel">
        <div class="panel-header">
          <div class="panel-title">Comparison</div>
          <button class="icon-btn" @click="historySelected = new Set()">✕ Clear</button>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th class="sortable" :class="s(compareSortCol === 'model_id', compareSortDir)" @click="toggleCompareSort('model_id')">Model<span class="sort-arrow" /></th>
                <th class="sortable" :class="s(compareSortCol === 'engine_id', compareSortDir)" @click="toggleCompareSort('engine_id')">Engine<span class="sort-arrow" /></th>
                <th class="sortable" :class="s(compareSortCol === 'benchmark_type', compareSortDir)" @click="toggleCompareSort('benchmark_type')">Type<span class="sort-arrow" /></th>
                <th class="sortable" :class="s(compareSortCol === 'timestamp', compareSortDir)" @click="toggleCompareSort('timestamp')">Date<span class="sort-arrow" /></th>
                <th class="num sortable" :class="s(compareSortCol === 'avg_tps', compareSortDir)" @click="toggleCompareSort('avg_tps')">Speed (t/s)<span class="sort-arrow" /></th>
                <th class="num sortable" :class="s(compareSortCol === 'avg_ttft_ms', compareSortDir)" @click="toggleCompareSort('avg_ttft_ms')">TTFT<span class="sort-arrow" /></th>
                <th class="num sortable" :class="s(compareSortCol === 'max_tokens', compareSortDir)" @click="toggleCompareSort('max_tokens')">Max Tok<span class="sort-arrow" /></th>
                <th class="num sortable" :class="s(compareSortCol === 'enable_thinking', compareSortDir)" @click="toggleCompareSort('enable_thinking')">Thinking<span class="sort-arrow" /></th>
                <th class="num">KV Quant</th>
                <th class="num">GSM8K</th>
                <th class="num">MMLU</th>
                <th class="num">HumanEval</th>
                <th class="num">MATH</th>
                <th class="num">IFEval</th>
                <th class="num sortable" :class="s(compareSortCol === 'overall_score', compareSortDir)" @click="toggleCompareSort('overall_score')">Overall<span class="sort-arrow" /></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in sortedCompareRuns" :key="run.id">
                <td class="mono">{{ (run.model_id || '').split('/').pop() || '—' }}</td>
                <td><span class="engine-pill">{{ run.engine_id ?? 'vllm-mlx' }}</span></td>
                <td><span class="type-pill" :class="run.benchmark_type">{{ run.benchmark_type || 'speed' }}</span></td>
                <td class="dim">{{ formatRelTime(run.timestamp) }}</td>
                <td class="num mono">
                  <span :title="hasStaleMetrics(run) ? 'tok/s may be inaccurate (pre-v0.3.80)' : undefined">
                    {{ run.avg_tps > 0 ? run.avg_tps.toFixed(1) : '—' }}
                    <span v-if="hasStaleMetrics(run)" class="stale-warn">⚠</span>
                  </span>
                </td>
                <td class="num mono">{{ run.avg_ttft_ms != null ? Math.round(run.avg_ttft_ms) + "ms" : "—" }}</td>
                <td class="num mono">{{ run.max_tokens ?? '—' }}</td>
                <td class="num mono">{{ run.enable_thinking != null ? (run.enable_thinking ? '✓' : '✗') : '—' }}</td>
                <td class="num mono">
                  {{ run.server_settings?.kv_cache_quantization
                    ? (run.server_settings.kv_cache_quantization_bits ?? 8) + '-bit'
                    : '✗' }}
                </td>
                <td class="num mono">
                  {{ run.suites?.gsm8k ? Math.round(run.suites.gsm8k.accuracy * 100) + '%' : '—' }}
                  <span v-if="run.suites?.gsm8k?.accuracy_ci_95" class="ci-range dim" :title="`95% CI: ${Math.round(run.suites.gsm8k.accuracy_ci_95[0]*100)}%–${Math.round(run.suites.gsm8k.accuracy_ci_95[1]*100)}%`">
                    ±{{ Math.round((run.suites.gsm8k.accuracy_ci_95[1] - run.suites.gsm8k.accuracy_ci_95[0]) / 2 * 100) }}%
                  </span>
                </td>
                <td class="num mono">
                  {{ run.suites?.mmlu ? Math.round(run.suites.mmlu.accuracy * 100) + '%' : '—' }}
                  <span v-if="run.suites?.mmlu?.accuracy_ci_95" class="ci-range dim" :title="`95% CI: ${Math.round(run.suites.mmlu.accuracy_ci_95[0]*100)}%–${Math.round(run.suites.mmlu.accuracy_ci_95[1]*100)}%`">
                    ±{{ Math.round((run.suites.mmlu.accuracy_ci_95[1] - run.suites.mmlu.accuracy_ci_95[0]) / 2 * 100) }}%
                  </span>
                </td>
                <td class="num mono">
                  {{ run.suites?.humaneval ? Math.round(run.suites.humaneval.accuracy * 100) + '%' : '—' }}
                  <span v-if="run.suites?.humaneval?.accuracy_ci_95" class="ci-range dim" :title="`95% CI: ${Math.round(run.suites.humaneval.accuracy_ci_95[0]*100)}%–${Math.round(run.suites.humaneval.accuracy_ci_95[1]*100)}%`">
                    ±{{ Math.round((run.suites.humaneval.accuracy_ci_95[1] - run.suites.humaneval.accuracy_ci_95[0]) / 2 * 100) }}%
                  </span>
                </td>
                <td class="num mono">{{ run.suites?.math ? Math.round(run.suites.math.accuracy * 100) + '%' : '—' }}</td>
                <td class="num mono">{{ run.suites?.ifeval ? Math.round(run.suites.ifeval.accuracy * 100) + '%' : '—' }}</td>
                <td class="num mono">{{ run.overall_score != null ? Math.round(run.overall_score * 100) + '%' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <!-- Bar comparison charts -->
        <div class="compare-charts">
          <div class="compare-chart-group" v-if="compareRuns.some(r => r.avg_tps > 0)">
            <div class="compare-chart-title">Speed (tok/s)</div>
            <div v-for="run in compareRuns" :key="'spd-' + run.id" class="compare-bar-row">
              <span class="compare-bar-label mono">{{ (run.model_id || '').split('/').pop()?.slice(0, 20) }}</span>
              <div class="compare-bar-track">
                <div
                  class="compare-bar-fill speed-fill"
                  :style="{ width: Math.min(100, (run.avg_tps / Math.max(...compareRuns.map(r => r.avg_tps || 0))) * 100) + '%' }"
                />
              </div>
              <span class="compare-bar-val mono">{{ run.avg_tps > 0 ? run.avg_tps.toFixed(1) : '—' }}</span>
            </div>
          </div>
          <div class="compare-chart-group" v-if="compareRuns.some(r => r.overall_score != null)">
            <div class="compare-chart-title">Quality (overall %)</div>
            <div v-for="run in compareRuns" :key="'q-' + run.id" class="compare-bar-row">
              <span class="compare-bar-label mono">{{ (run.model_id || '').split('/').pop()?.slice(0, 20) }}</span>
              <div class="compare-bar-track">
                <div
                  class="compare-bar-fill quality-fill"
                  :style="{ width: (run.overall_score != null ? run.overall_score * 100 : 0) + '%' }"
                />
              </div>
              <span class="compare-bar-val mono">{{ run.overall_score != null ? Math.round(run.overall_score * 100) + '%' : '—' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Detail panel (1 selected) -->
      <div ref="detailPanelRef" v-if="selectedRun" class="panel detail-panel">
        <div class="panel-header">
          <div class="panel-title">
            Run Detail
            <span class="type-pill" :class="selectedRun.benchmark_type">{{ selectedRun.benchmark_type || 'speed' }}</span>
          </div>
          <button class="icon-btn" @click="historySelected = new Set()">✕ Close</button>
        </div>
        <div class="detail-body">
          <!-- Summary row -->
          <div class="detail-summary">
            <div class="detail-kv">
              <span class="detail-k">Model</span>
              <span class="detail-v mono">{{ selectedRun.model_id }}</span>
            </div>
            <div class="detail-kv">
              <span class="detail-k">Run at</span>
              <span class="detail-v">{{ new Date(selectedRun.timestamp).toLocaleString() }}</span>
            </div>
            <div class="detail-kv" v-if="selectedRun.label">
              <span class="detail-k">Label</span>
              <span class="detail-v">"{{ selectedRun.label }}"</span>
            </div>
            <div class="detail-kv" v-if="selectedRun.avg_tps > 0">
              <span class="detail-k">Avg tok/s</span>
              <span class="detail-v mono">
                {{ selectedRun.avg_tps.toFixed(1) }}
                <span v-if="hasStaleMetrics(selectedRun)" class="stale-warn" title="tok/s may be inaccurate — recorded before v0.3.80 fix">⚠ pre-fix</span>
              </span>
            </div>
            <div class="detail-kv" v-if="selectedRun.avg_ttft_ms != null">
              <span class="detail-k">Avg TTFT</span>
              <span class="detail-v mono">{{ Math.round(selectedRun.avg_ttft_ms) }}ms</span>
            </div>
          </div>

          <!-- Settings used -->
          <div class="detail-section">
            <div class="detail-section-title">Settings</div>
            <div class="detail-settings-grid">
              <div class="detail-kv" v-if="selectedRun.max_tokens != null">
                <span class="detail-k">Max tokens</span>
                <span class="detail-v mono">{{ selectedRun.max_tokens }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.enable_thinking != null">
                <span class="detail-k">Thinking mode</span>
                <span class="detail-v">{{ selectedRun.enable_thinking ? 'On' : 'Off' }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.server_settings?.kv_cache_quantization != null">
                <span class="detail-k">KV quantization</span>
                <span class="detail-v">
                  {{ selectedRun.server_settings.kv_cache_quantization
                    ? (selectedRun.server_settings.kv_cache_quantization_bits ?? 8) + '-bit on'
                    : 'Off' }}
                </span>
              </div>
              <div class="detail-kv" v-if="selectedRun.server_settings?.use_paged_cache != null">
                <span class="detail-k">Paged KV cache</span>
                <span class="detail-v">{{ selectedRun.server_settings.use_paged_cache ? 'On' : 'Off' }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.server_settings?.continuous_batching != null">
                <span class="detail-k">Continuous batching</span>
                <span class="detail-v">{{ selectedRun.server_settings.continuous_batching ? 'On' : 'Off' }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.server_settings?.enable_prefix_cache != null">
                <span class="detail-k">Prefix cache</span>
                <span class="detail-v">{{ selectedRun.server_settings.enable_prefix_cache ? 'On' : 'Off' }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.server_settings?.gpu_memory_utilization != null">
                <span class="detail-k">GPU mem util</span>
                <span class="detail-v mono">{{ Math.round((selectedRun.server_settings.gpu_memory_utilization ?? 0) * 100) }}%</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.dashboard_version">
                <span class="detail-k">Dashboard ver</span>
                <span class="detail-v mono">{{ selectedRun.dashboard_version }}</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.engine_id">
                <span class="detail-k">Engine</span>
                <span class="detail-v"><span class="engine-pill">{{ selectedRun.engine_id }}</span></span>
              </div>
            </div>
            <div class="detail-section">
              <div class="detail-section-title">Hardware</div>
              <div class="detail-settings-grid" v-if="selectedRun.hardware">
                <div class="detail-kv">
                  <span class="detail-k">Chip</span>
                  <span class="detail-v">{{ selectedRun.hardware.chip }}</span>
                </div>
                <div class="detail-kv" v-if="selectedRun.hardware.total_ram_gb">
                  <span class="detail-k">RAM</span>
                  <span class="detail-v">{{ selectedRun.hardware.total_ram_gb }} GB</span>
                </div>
                <div class="detail-kv">
                  <span class="detail-k">macOS</span>
                  <span class="detail-v">{{ selectedRun.hardware.os_version }}</span>
                </div>
                <div class="detail-kv" v-if="selectedRun.hardware.mlx_version">
                  <span class="detail-k">MLX</span>
                  <span class="detail-v">{{ selectedRun.hardware.mlx_version }}</span>
                </div>
              </div>
              <div v-else class="panel-empty">Not captured (pre-v0.7 benchmark)</div>
            </div>
          </div>

          <!-- Per-prompt results (custom benchmark) -->
          <div class="detail-section" v-if="selectedRun.per_prompt?.length">
            <div class="detail-section-title">Per-prompt results</div>
            <div class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Prompt</th>
                    <th class="num">TTFT</th>
                    <th class="num">tok/s</th>
                    <th class="num">Total</th>
                    <th class="num">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(pp, i) in selectedRun.per_prompt" :key="i" :class="{ 'row-error': pp.error }">
                    <td class="dim">{{ i + 1 }}</td>
                    <td class="prompt-cell" :title="pp.prompt">{{ pp.prompt?.slice(0, 80) }}{{ (pp.prompt?.length ?? 0) > 80 ? '…' : '' }}</td>
                    <td class="num mono">{{ pp.error ? '✗' : pp.ttft_ms != null ? pp.ttft_ms.toFixed(0) + 'ms' : '—' }}</td>
                    <td class="num mono">
                      <span v-if="pp.error" class="error-text">{{ pp.error }}</span>
                      <span v-else>{{ pp.tps != null ? pp.tps.toFixed(1) : '—' }}</span>
                    </td>
                    <td class="num mono">{{ pp.total_ms != null ? (pp.total_ms / 1000).toFixed(1) + 's' : '—' }}</td>
                    <td class="num mono">{{ pp.tokens ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Quality suite results -->
          <div class="detail-section" v-if="selectedRun.suites">
            <div class="detail-section-title">Quality scores</div>
            <div class="detail-settings-grid">
              <div class="detail-kv" v-for="(suite, name) in selectedRun.suites" :key="String(name)">
                <span class="detail-k">{{ name }}</span>
                <span class="detail-v mono">{{ Math.round(suite.accuracy * 100) }}% ({{ suite.correct }}/{{ suite.total }})</span>
              </div>
              <div class="detail-kv" v-if="selectedRun.overall_score != null">
                <span class="detail-k">Overall</span>
                <span class="detail-v mono">{{ Math.round(selectedRun.overall_score * 100) }}%</span>
              </div>
            </div>
          </div>
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
              <span class="type-pill" :class="run.benchmark_type">{{ run.benchmark_type || 'speed' }}</span>
              <span class="history-model mono">{{ (run.model_id || '').split('/').pop() || '—' }}</span>
              <span class="history-time dim">{{ formatRelTime(run.timestamp) }}</span>
              <span v-if="run.label" class="history-label">"{{ run.label }}"</span>
              <span v-if="run.engine_id && run.engine_id !== 'vllm-mlx'" class="h-badge engine-badge">{{ run.engine_id }}</span>
            </div>
            <div class="history-badges">
              <span v-if="run.avg_tps > 0" class="h-badge speed-badge"
                :title="hasStaleMetrics(run) ? 'tok/s may be inaccurate — recorded before v0.3.80 fix' : undefined"
              >
                {{ run.avg_tps.toFixed(1) }} t/s
                <span v-if="hasStaleMetrics(run)" class="stale-warn">⚠</span>
              </span>
              <span v-if="run.max_tokens" class="h-badge dim-badge">{{ run.max_tokens }} tok</span>
              <span v-if="run.enable_thinking" class="h-badge thinking-badge">thinking on</span>
              <span v-if="run.server_settings?.kv_cache_quantization" class="h-badge kv-badge">
                KV {{ run.server_settings.kv_cache_quantization_bits ?? 8 }}-bit
              </span>
              <span v-if="run.server_settings?.use_paged_cache" class="h-badge kv-badge">paged KV</span>
              <span v-if="run.suites?.gsm8k" class="h-badge quality-badge"
                :class="run.suites.gsm8k.accuracy >= 0.7 ? 'good' : run.suites.gsm8k.accuracy >= 0.5 ? 'mid' : 'bad'"
                :title="run.suites.gsm8k.accuracy_ci_95
                  ? `95% CI: ${Math.round(run.suites.gsm8k.accuracy_ci_95[0] * 100)}%–${Math.round(run.suites.gsm8k.accuracy_ci_95[1] * 100)}%`
                  : ''"
              >
                GSM8K {{ Math.round(run.suites.gsm8k.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.mmlu" class="h-badge quality-badge"
                :class="run.suites.mmlu.accuracy >= 0.7 ? 'good' : run.suites.mmlu.accuracy >= 0.5 ? 'mid' : 'bad'"
                :title="run.suites.mmlu.accuracy_ci_95
                  ? `95% CI: ${Math.round(run.suites.mmlu.accuracy_ci_95[0] * 100)}%–${Math.round(run.suites.mmlu.accuracy_ci_95[1] * 100)}%`
                  : ''"
              >
                MMLU {{ Math.round(run.suites.mmlu.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.humaneval" class="h-badge quality-badge"
                :class="run.suites.humaneval.accuracy >= 0.7 ? 'good' : run.suites.humaneval.accuracy >= 0.5 ? 'mid' : 'bad'"
                :title="run.suites.humaneval.accuracy_ci_95
                  ? `95% CI: ${Math.round(run.suites.humaneval.accuracy_ci_95[0] * 100)}%–${Math.round(run.suites.humaneval.accuracy_ci_95[1] * 100)}%`
                  : ''"
              >
                HumanEval {{ Math.round(run.suites.humaneval.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.math" class="h-badge quality-badge"
                :class="run.suites.math.accuracy >= 0.7 ? 'good' : run.suites.math.accuracy >= 0.5 ? 'mid' : 'bad'"
              >
                MATH {{ Math.round(run.suites.math.accuracy * 100) }}%
              </span>
              <span v-if="run.suites?.ifeval" class="h-badge quality-badge"
                :class="run.suites.ifeval.accuracy >= 0.7 ? 'good' : run.suites.ifeval.accuracy >= 0.5 ? 'mid' : 'bad'"
              >
                IFEval {{ Math.round(run.suites.ifeval.accuracy * 100) }}%
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
        <p>Run your first benchmark from the Run Tests tab — results appear here automatically.</p>
      </div>
    </div>

    <!-- ── ADVISOR TAB ───────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Advisor'" class="tab-body advisor-tab">

      <div class="advisor-layout">
        <!-- Left: task selector + model selection -->
        <div class="advisor-left">
          <div class="panel-header">
            <div class="panel-title">What are you building?</div>
          </div>

          <div class="advisor-tasks">
            <button
              v-for="task in ADVISOR_TASKS"
              :key="task.id"
              class="advisor-task-btn"
              :class="{ active: advisorTask === task.id }"
              :disabled="advisorRunning"
              @click="advisorTask = task.id"
            >{{ task.label }}</button>
          </div>

          <div class="bench-section-label" style="margin-top:var(--space-4)">Models to evaluate</div>
          <div v-if="cachedModels.length === 0" class="bench-no-models">
            No downloaded models — download one on the Models page.
          </div>
          <template v-else>
            <!-- Search + filter bar -->
            <div class="model-filter-bar" style="margin-bottom:8px">
              <div class="model-search-wrap">
                <svg class="model-search-icon" viewBox="0 0 16 16" fill="none"><circle cx="6.5" cy="6.5" r="4" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                <input
                  v-model="modelSearch"
                  class="model-search-input"
                  placeholder="Search models…"
                  :disabled="advisorRunning"
                />
                <button v-if="modelSearch" class="model-search-clear" @click="modelSearch = ''" :disabled="advisorRunning">×</button>
              </div>
              <div class="model-filter-row">
                <select v-model="modelSizeFilter" class="model-filter-select" :disabled="advisorRunning">
                  <option value="all">All sizes</option>
                  <option value="<4">&lt; 4 GB</option>
                  <option value="4-8">4 – 8 GB</option>
                  <option value="8-16">8 – 16 GB</option>
                  <option value=">16">&gt; 16 GB</option>
                </select>
                <select v-model="modelQuantFilter" class="model-filter-select" :disabled="advisorRunning">
                  <option value="all">All quant</option>
                  <option v-for="q in availableQuants" :key="q" :value="q">{{ q }}</option>
                </select>
              </div>
              <div class="model-filter-actions">
                <span class="model-filter-count">{{ filteredCachedModels.length }} of {{ cachedModels.length }}</span>
                <button class="model-filter-link" :disabled="advisorRunning" @click="selectAllAdvisorModels">All</button>
                <button class="model-filter-link" :disabled="advisorRunning" @click="clearAdvisorModels">None</button>
              </div>
            </div>
            <div v-if="filteredCachedModels.length === 0" class="bench-no-models">
              No models match the current filters.
            </div>
            <div v-else class="bench-model-list">
              <label
                v-for="m in filteredCachedModels"
                :key="m.id"
                class="bench-check"
                :class="{ checked: advisorModels.includes(m.id) }"
              >
                <input type="checkbox" :disabled="advisorRunning" :checked="advisorModels.includes(m.id)" @change="toggleAdvisorModel(m.id)" />
                <div class="bench-check-info">
                  <span class="bench-check-label mono">{{ m.id.split('/').pop() }}</span>
                  <span class="bench-check-desc">{{ m.id.split('/')[0] }} · {{ m.size_gb?.toFixed(1) ?? '?' }} GB · {{ m.quantization }}</span>
                </div>
              </label>
            </div>
          </template>

          <div class="bench-run-row" style="margin-top:var(--space-4)">
            <AppButton
              :disabled="advisorRunning || !serverStore.isRunning || advisorModels.length === 0"
              @click="runAdvisorAnalysis"
            >
              <span v-if="advisorRunning" class="spin" style="margin-right:6px" />
              {{ advisorRunning ? 'Analysing…' : 'Analyse Models' }}
            </AppButton>
            <AppButton v-if="advisorRunning" variant="secondary" @click="stopAdvisor">Stop</AppButton>
          </div>
        </div>

        <!-- Right: results -->
        <div class="advisor-right">
          <!-- Idle state -->
          <div v-if="!advisorRunning && !advisorDone && advisorLines.length === 0" class="advisor-idle">
            <div class="cs-icon">
              <svg viewBox="0 0 20 20" fill="currentColor" width="28" height="28" aria-hidden="true">
                <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
              </svg>
            </div>
            <template v-if="!serverStore.isRunning">
              <p>Start the inference server on the <strong>Serve</strong> page, then return here to analyse models.</p>
            </template>
            <template v-else-if="advisorModels.length === 0">
              <p>Select one or more models on the left, then click <strong>Analyse Models</strong>.</p>
            </template>
            <template v-else>
              <p>Select a task type and models, then click <strong>Analyse Models</strong> to run targeted benchmarks and get a recommendation.</p>
            </template>
            <div class="cs-tags">
              <span class="cs-tag">Quality scores</span>
              <span class="cs-tag">Speed measurement</span>
              <span class="cs-tag">Model ranking</span>
            </div>
          </div>

          <!-- Live log -->
          <div v-if="advisorLines.length > 0" class="inline-log-wrap">
            <pre class="quality-log">{{ advisorLines.join('') }}</pre>
          </div>

          <!-- Rankings -->
          <div v-if="advisorDone && advisorRankings.length > 0" class="advisor-rankings">
            <div class="advisor-rankings-title">
              Recommendation for <strong>{{ advisorTaskDef.label }}</strong>
            </div>
            <div
              v-for="(result, idx) in advisorRankings"
              :key="result.id"
              class="advisor-rank-row"
              :class="{ 'rank-winner': idx === 0 }"
            >
              <div class="rank-medal">{{ idx === 0 ? '🥇' : idx === 1 ? '🥈' : '🥉' }}</div>
              <div class="rank-info">
                <div class="rank-name mono">{{ result.label }}</div>
                <div class="rank-rec">{{ result.recommendation }}</div>
              </div>
              <div class="rank-scores">
                <div v-if="result.quality > 0" class="rank-score-item">
                  <span class="rank-score-val" :class="result.quality >= 0.7 ? 'good' : result.quality >= 0.4 ? 'mid' : 'bad'">
                    {{ Math.round(result.quality * 100) }}%
                  </span>
                  <span class="rank-score-lbl">quality</span>
                </div>
                <div v-if="result.speedRaw > 0" class="rank-score-item">
                  <span class="rank-score-val">{{ result.speedRaw.toFixed(1) }}</span>
                  <span class="rank-score-lbl">tok/s</span>
                </div>
                <div class="rank-score-item">
                  <span class="rank-score-val overall">{{ Math.round(result.score * 100) }}%</span>
                  <span class="rank-score-lbl">score</span>
                </div>
              </div>
            </div>

            <div v-if="advisorRankings[0]" class="advisor-winner-note">
              <strong>{{ advisorRankings[0].label }}</strong> is the best fit for {{ advisorTaskDef.label.replace(/^.+ /, '') }}.
              <template v-if="advisorRankings[0].speedRaw > 0">
                It generates at {{ advisorRankings[0].speedRaw.toFixed(1) }} tok/s
                <template v-if="advisorRankings[0].quality > 0">
                  with {{ Math.round(advisorRankings[0].quality * 100) }}% accuracy.
                </template>
              </template>
            </div>
          </div>

          <div v-else-if="advisorDone && advisorRankings.length === 0" class="advisor-idle">
            <p>No benchmark results to rank. Try running with more models or a different task type.</p>
          </div>
        </div>
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
  font-size: 24px;
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

/* Pulsing dot shown on "Run Tests" tab while a benchmark is running */
.tab-run-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--si-400);
  margin-left: 5px;
  vertical-align: middle;
  animation: tab-dot-pulse 1.2s ease-in-out infinite;
}
@keyframes tab-dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.7); }
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
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.mcard-val {
  font-size: 20px;
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
  font-size: 13px;
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
  font-size: 13px;
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
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  flex: 1;
}

.panel-model {
  font-size: 13px;
  color: var(--tx-muted);
}

.panel-count {
  font-size: 13px;
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

/* ── Confidence interval display ────────────────────────────────────────── */
.ci-range {
  font-size: 11px;
  font-weight: 400;
  margin-left: 2px;
  vertical-align: super;
}

/* ── Quality scores inline (Run Tests tab) ──────────────────────────────── */
.qsi-ci {
  font-size: 11px;
  color: var(--tx-muted);
  margin-top: -1px;
}

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
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  border-bottom: 1px solid var(--bd-default);
  white-space: nowrap;
}

.data-table th.num { text-align: right; }

.data-table th.sortable {
  cursor: pointer;
  user-select: none;
  transition: color var(--transition-fast);
}
.data-table th.sortable:hover { color: var(--tx-primary); }
.data-table th.sortable.active { color: var(--si-300); }

.sort-arrow { margin-left: 4px; font-size: 10px; }
th.asc .sort-arrow::after { content: '▲'; }
th.desc .sort-arrow::after { content: '▼'; }
th.sortable:not(.active) .sort-arrow::after { content: '▽'; opacity: .3; }

.data-table td {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  color: var(--tx-secondary);
}

.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,.012); }
.data-table .num { text-align: right; }
.data-table .mono { font-family: var(--font-mono); font-size: 14px; }
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
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: 3px;
}

.cache-val {
  font-size: 14px;
  color: var(--tx-secondary);
  word-break: break-all;
}

.cache-note {
  grid-column: 1 / -1;
  padding: var(--space-2) var(--space-4);
  font-size: 12px;
  color: var(--tx-muted);
  background: var(--bg-surface);
  border-top: 1px solid var(--bd-subtle);
}

/* ── Benchmark tab ───────────────────────────────────────────────────────── */
.bench-config { padding: 0; }
.bench-cols {
  display: grid;
  grid-template-columns: 1fr 1px 1fr;
  align-items: start;
}
.bench-col { padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.bench-col-divider { background: var(--bd-default); align-self: stretch; }
.bench-col-locked { opacity: 0.4; pointer-events: none; }

.bench-step {
  display: flex; align-items: center; gap: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--bd-subtle);
}
.bench-step-num {
  width: 20px; height: 20px; border-radius: 50%;
  border: 1px solid var(--bd-default);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: var(--tx-secondary);
  flex-shrink: 0;
}
.bench-step-title {
  font-size: 12px; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: var(--tx-muted);
}
.bench-needs-model {
  font-size: 12px; color: var(--cu-500); font-style: italic; margin-left: auto;
}
.bench-section-label {
  font-size: 12px; font-weight: 700; letter-spacing: .07em;
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
.bench-check-label { font-weight: 600; font-size: 15px; color: var(--tx-primary); }
.bench-check-desc { font-size: 13px; color: var(--tx-muted); }

.bench-model-list { display: flex; flex-direction: column; gap: 6px; }
.bench-no-models { font-size: 14px; color: var(--tx-muted); padding: 8px 0; }

/* Model search + filter bar */
.model-filter-bar { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.model-search-wrap {
  display: flex; align-items: center; gap: 6px;
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: 7px; padding: 0 10px; height: 34px;
  transition: border-color 0.15s;
}
.model-search-wrap:focus-within { border-color: var(--si-400); }
.model-search-icon { width: 14px; height: 14px; color: var(--tx-muted); flex-shrink: 0; }
.model-search-input {
  flex: 1; background: none; border: none; outline: none;
  font-size: 14px; color: var(--tx-primary);
}
.model-search-input::placeholder { color: var(--tx-muted); }
.model-search-clear {
  background: none; border: none; cursor: pointer; color: var(--tx-muted);
  font-size: 16px; line-height: 1; padding: 0 2px;
  transition: color 0.15s;
}
.model-search-clear:hover { color: var(--tx-primary); }
.model-filter-row { display: flex; gap: 8px; }
.model-filter-select {
  flex: 1; background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: 6px; color: var(--tx-primary); padding: 4px 8px; font-size: 13px;
  cursor: pointer; transition: border-color 0.15s;
}
.model-filter-select:focus { border-color: var(--si-400); outline: none; }
.model-filter-actions {
  display: flex; align-items: center; gap: 10px;
}
.model-filter-count { font-size: 12px; color: var(--tx-muted); flex: 1; }
.model-filter-link {
  background: none; border: none; cursor: pointer; font-size: 12px;
  color: var(--si-400); padding: 0; text-decoration: underline; text-underline-offset: 2px;
  transition: opacity 0.15s;
}
.model-filter-link:hover { opacity: 0.75; }
.model-filter-link:disabled { opacity: 0.4; cursor: default; }
.bench-model-badge {
  font-size: 12px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
  padding: 2px 6px; border-radius: 4px; background: color-mix(in srgb, var(--si-400) 15%, transparent);
  color: var(--si-400); flex-shrink: 0;
}

.bench-opts-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.opt-label { font-size: 14px; color: var(--tx-secondary); display: flex; align-items: center; gap: 8px; }
.opt-select {
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: 6px; color: var(--tx-primary); padding: 4px 8px; font-size: 14px;
}

.bench-mode-row { display: flex; flex-direction: column; gap: 6px; }
.bench-engine-row { margin-bottom: 16px; }
.bench-engine-select {
  width: 100%; height: 34px; padding: 0 10px;
  background: var(--bg-elevated); border: 1px solid var(--bd);
  border-radius: 6px; color: var(--tx); font-size: 13px; cursor: pointer;
}
.bench-engine-select:disabled { opacity: 0.6; cursor: not-allowed; }
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
  font-size: 13px; border-radius: 99px; padding: 2px 8px; font-weight: 600;
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
  font-size: 15px; color: var(--tx-muted); padding: 4px 0;
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
.sri-val { font-size: 24px; font-weight: 700; color: var(--tx-primary); line-height: 1.2; }
.sri-label { font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); }

/* Quality log + inline scores */
.quality-log {
  background: rgba(0,0,0,.35); color: var(--tx-secondary);
  font-family: var(--font-mono); font-size: 13px; line-height: 1.6;
  padding: 10px 12px; margin: 0; max-height: 240px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-word; border-radius: 0;
}

.quality-scores-inline {
  display: flex; gap: 12px; flex-wrap: wrap; padding: 8px 0 4px;
}
.qsi { text-align: center; min-width: 64px; }
.qsi-name { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); margin-bottom: 2px; }
.qsi-score { font-size: 22px; font-weight: 700; }
.qsi-score.good { color: #4ade80; }
.qsi-score.mid  { color: #f59e0b; }
.qsi-score.bad  { color: #f87171; }
.qsi-detail { font-size: 12px; color: var(--tx-muted); }
.qsi-overall .qsi-score { font-size: 26px; }
.qsi-speed-row {
  width: 100%; display: flex; gap: 16px; justify-content: center; flex-wrap: wrap;
  padding-top: 10px; margin-top: 8px; border-top: 1px solid var(--bd-subtle);
}
.qsi-speed-stat { display: flex; align-items: baseline; gap: 4px; }
.qsi-speed-val { font-size: 17px; font-weight: 600; color: var(--tx-primary); font-variant-numeric: tabular-nums; }
.qsi-speed-lbl { font-size: 12px; color: var(--tx-muted); }

/* ── History tab ─────────────────────────────────────────────────────────── */
.history-toolbar {
  display: flex; align-items: center;
  justify-content: space-between; gap: 12px;
}
.history-actions { display: flex; gap: 8px; }
.saved-count {
  font-size: 13px; font-weight: 700; letter-spacing: .07em;
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
  font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  background: color-mix(in srgb, var(--si-400) 15%, transparent);
  color: var(--si-400); border-radius: 99px; padding: 1px 7px;
}

.history-model { font-size: 15px; font-weight: 600; font-family: var(--font-mono); color: var(--tx-primary); }
.history-time { font-size: 13px; color: var(--tx-muted); }

.history-badges { display: flex; gap: 6px; flex-wrap: wrap; }

.h-badge {
  display: inline-flex; align-items: center;
  font-size: 12px; font-weight: 600;
  padding: 2px 7px; border-radius: var(--r-pill);
  border: 1px solid var(--bd-default);
}

.speed-badge { color: var(--si-400); background: color-mix(in srgb, var(--si-400) 8%, transparent); border-color: color-mix(in srgb, var(--si-400) 25%, transparent); }
.quality-badge.good { color: #4ade80; background: rgba(74,222,128,.08); border-color: rgba(74,222,128,.2); }
.quality-badge.mid  { color: #f59e0b; background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.2); }
.quality-badge.bad  { color: #f87171; background: rgba(248,113,113,.08); border-color: rgba(248,113,113,.2); }
.overall-badge { color: var(--tx-secondary); background: var(--bg-elevated); }
.dim-badge { color: var(--tx-muted); background: var(--bg-elevated); }
.thinking-badge { color: #818cf8; background: rgba(129,140,248,.08); border-color: rgba(129,140,248,.25); }
.kv-badge { color: #38bdf8; background: rgba(56,189,248,.08); border-color: rgba(56,189,248,.25); }
.engine-badge { color: #fb923c; background: rgba(251,146,60,.08); border-color: rgba(251,146,60,.25); }

/* Engine pill (inline, non-badge usage in tables) */
.engine-pill {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 600; font-family: var(--font-mono);
  padding: 1px 6px; border-radius: var(--r-pill);
  color: #fb923c; background: rgba(251,146,60,.08); border: 1px solid rgba(251,146,60,.25);
}
.stale-warn { color: #f59e0b; font-size: 11px; margin-left: 3px; cursor: help; }

/* Type pill */
.type-pill {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
  padding: 1px 6px; border-radius: var(--r-pill);
  border: 1px solid transparent;
}
.type-pill.custom  { color: #a78bfa; background: rgba(167,139,250,.1); border-color: rgba(167,139,250,.3); }
.type-pill.speed   { color: var(--si-400); background: color-mix(in srgb, var(--si-400) 8%, transparent); border-color: color-mix(in srgb, var(--si-400) 25%, transparent); }
.type-pill.quality { color: #34d399; background: rgba(52,211,153,.08); border-color: rgba(52,211,153,.25); }

/* Detail panel */
.detail-panel { margin-bottom: var(--space-4); }
.detail-body { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); }
.detail-summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-2) var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--bd-default);
}
.detail-section { display: flex; flex-direction: column; gap: var(--space-2); }
.detail-section-title { font-size: 13px; font-weight: 700; color: var(--tx-muted); text-transform: uppercase; letter-spacing: .05em; }
.detail-settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-1) var(--space-4);
}
.detail-kv { display: flex; align-items: baseline; gap: var(--space-2); min-width: 0; }
.detail-k { font-size: 13px; color: var(--tx-muted); white-space: nowrap; flex-shrink: 0; min-width: 110px; }
.detail-v { font-size: 13px; color: var(--tx-primary); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-cell { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--tx-secondary); }
.row-error td { color: var(--tx-muted); }
.error-text { color: #f87171; font-size: 12px; }

.history-row-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }

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
  font-size: 18px; font-weight: 700;
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
  font-size: 13px; font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-muted);
}

.cs-note {
  font-size: 14px;
  color: var(--tx-muted);
  font-style: italic;
  margin: 0;
}

/* ── Shared ──────────────────────────────────────────────────────────────── */
.mono { font-family: var(--font-mono); }
.dim  { color: var(--tx-muted); }

.icon-btn {
  background: none; border: none; cursor: pointer;
  color: var(--tx-muted); font-size: 15px; padding: 4px 6px;
  border-radius: var(--r-sm); line-height: 1;
  transition: color 0.15s, background 0.15s;
}
.icon-btn:hover { color: var(--tx-secondary); background: var(--bg-elevated); }
.icon-btn.danger:hover { color: #f87171; }

/* ── Bench run name input ────────────────────────────────────────────────── */
.bench-name-input {
  width: 100%;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--bd-default);
  background: var(--bg-elevated);
  color: var(--tx-primary);
  font-size: 15px;
  font-family: inherit;
}
.bench-name-input:disabled { opacity: 0.5; }
.opt-hint { font-size: 13px; color: var(--tx-muted); font-weight: 400; }
.thinking-toggle-row {
  display: flex; align-items: center; gap: 7px;
  font-size: 14px; color: var(--tx-secondary); margin-top: 8px; cursor: pointer;
  user-select: none;
}
.thinking-toggle-row.disabled { opacity: 0.5; cursor: default; }
.thinking-toggle-row input[type="checkbox"] { cursor: pointer; accent-color: var(--accent); }
.badge-pending { background: var(--bg-elevated); color: var(--tx-secondary); }
.inline-log-wrap { margin-top: var(--space-3); }

/* ── History filter bar ──────────────────────────────────────────────────── */
.history-filter-bar { display: flex; gap: var(--space-3); align-items: center; margin-bottom: var(--space-3); }
.history-search { flex: 1; padding: 6px 10px; border-radius: var(--r-sm); border: 1px solid var(--bd-default); background: var(--bg-elevated); color: var(--tx-primary); font-size: 15px; font-family: inherit; }
.hf-type-btns { display: flex; gap: 4px; }
.hf-btn { padding: 4px 10px; border-radius: var(--r-sm); border: 1px solid var(--bd-default); background: var(--bg-elevated); color: var(--tx-secondary); font-size: 14px; cursor: pointer; font-family: inherit; }
.hf-btn.active { background: var(--si-400); color: #fff; border-color: var(--si-400); }
.history-label { font-size: 13px; color: var(--tx-muted); font-style: italic; }

/* ── Compare bar charts ──────────────────────────────────────────────────── */
.compare-charts { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-4); border-top: 1px solid var(--bd-default); margin-top: var(--space-3); }
.compare-chart-group { display: flex; flex-direction: column; gap: var(--space-2); }
.compare-chart-title { font-size: 14px; font-weight: 600; color: var(--tx-secondary); text-transform: uppercase; letter-spacing: .04em; }
.compare-bar-row { display: grid; grid-template-columns: 160px 1fr 60px; gap: var(--space-2); align-items: center; }
.compare-bar-label { font-size: 14px; color: var(--tx-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compare-bar-track { height: 8px; background: var(--bg-elevated); border-radius: 4px; overflow: hidden; }
.compare-bar-fill { height: 100%; border-radius: 4px; transition: width .4s ease; }
.compare-bar-fill.speed-fill { background: #a78bfa; }
.compare-bar-fill.quality-fill { background: #34d399; }
.compare-bar-val { font-size: 14px; font-weight: 600; color: var(--tx-primary); text-align: right; }

/* ── Chart range buttons ─────────────────────────────────────────────────── */
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-2); }
.chart-range-btns { display: flex; gap: 2px; }
.chart-range-btn { padding: 2px 8px; font-size: 13px; border-radius: var(--r-sm); border: 1px solid var(--bd-default); background: var(--bg-elevated); color: var(--tx-secondary); cursor: pointer; font-family: inherit; }
.chart-range-btn.active { background: var(--si-400); color: #fff; border-color: var(--si-400); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}

/* ── Performance Settings Override ──────────────────────────────────────── */
.perf-toggle-row {
  display: flex; align-items: center; gap: var(--space-2);
  cursor: pointer; margin: var(--space-3) 0 0; user-select: none;
}
.perf-chevron { color: var(--tx-muted); transition: transform .15s; flex-shrink: 0; }
.perf-chevron.open { transform: rotate(180deg); }
.perf-override-badge {
  font-size: 13px; padding: 1px 7px; border-radius: 999px;
  background: rgba(var(--si-rgb), .15); color: var(--si-400); font-weight: 600;
}
.perf-settings-panel {
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: var(--r-md); padding: var(--space-3); margin-top: var(--space-2);
  display: flex; flex-direction: column; gap: var(--space-3);
}
.perf-row { display: flex; align-items: flex-start; flex-wrap: wrap; gap: var(--space-1); }
.perf-row-inline { align-items: center; gap: var(--space-2); }
.perf-toggle { display: flex; align-items: center; gap: var(--space-2); cursor: pointer; flex-shrink: 0; }
.perf-label { font-size: var(--text-sm); color: var(--tx-primary); font-weight: 500; }
.perf-hint { font-size: 13px; color: var(--tx-muted); margin-left: var(--space-1); }
.perf-desc {
  flex-basis: 100%; margin: 0; font-size: 12px; color: var(--tx-muted); line-height: 1.55;
  padding-left: 22px;
}
.perf-link { color: var(--tx-accent, #6366f1); text-decoration: none; white-space: nowrap; }
.perf-link:hover { text-decoration: underline; }
.perf-bits-row {
  flex-basis: 100%; display: flex; align-items: center; gap: var(--space-2);
  padding-left: 22px; margin-top: var(--space-1);
}
.perf-num-input {
  width: 68px; padding: 3px 8px; font-size: var(--text-sm);
  background: var(--bg-base); border: 1px solid var(--bd-default); border-radius: var(--r-sm);
  color: var(--tx-primary); font-family: var(--font-mono);
}
.perf-unit { font-size: 13px; color: var(--tx-muted); }
.perf-warn { font-size: 13px; color: var(--cl-warning, #f59e0b); margin-top: var(--space-1); }
.perf-error { font-size: 13px; color: var(--cl-error, #ef4444); }
.perf-reset-btn {
  align-self: flex-start; font-size: 13px; padding: 3px 10px;
  border: 1px solid var(--bd-default); border-radius: var(--r-sm);
  background: var(--bg-base); color: var(--tx-secondary); cursor: pointer;
}
.perf-reset-btn:hover { color: var(--tx-primary); }

/* ── Advisor Tab ─────────────────────────────────────────────────────────── */
.advisor-tab { display: flex; flex-direction: column; }
.advisor-layout { display: grid; grid-template-columns: 280px 1fr; gap: var(--space-5); align-items: start; }
@media (max-width: 720px) { .advisor-layout { grid-template-columns: 1fr; } }

.advisor-left {
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: var(--r-lg); padding: var(--space-4);
}
.advisor-right {
  background: var(--bg-elevated); border: 1px solid var(--bd-default);
  border-radius: var(--r-lg); padding: var(--space-4); min-height: 300px;
}

.advisor-tasks { display: flex; flex-direction: column; gap: var(--space-1); margin-top: var(--space-3); }
.advisor-task-btn {
  display: block; width: 100%; text-align: left;
  padding: var(--space-2) var(--space-3); border-radius: var(--r-md);
  border: 1px solid transparent; background: transparent;
  color: var(--tx-secondary); font-size: var(--text-sm); cursor: pointer;
  font-family: inherit; transition: background .1s;
}
.advisor-task-btn:hover { background: var(--bg-hover); color: var(--tx-primary); }
.advisor-task-btn.active {
  background: rgba(var(--si-rgb), .12); border-color: rgba(var(--si-rgb), .3);
  color: var(--si-400); font-weight: 600;
}
.advisor-idle {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: var(--space-3); padding: var(--space-5);
  color: var(--tx-secondary); font-size: var(--text-sm);
}

.advisor-rankings { display: flex; flex-direction: column; gap: var(--space-2); }
.advisor-rankings-title { font-size: var(--text-sm); color: var(--tx-muted); margin-bottom: var(--space-2); }
.advisor-rank-row {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-3); border-radius: var(--r-md);
  border: 1px solid var(--bd-default); background: var(--bg-base);
}
.rank-winner { border-color: rgba(var(--si-rgb), .4); background: rgba(var(--si-rgb), .05); }
.rank-medal { font-size: 24px; flex-shrink: 0; }
.rank-info { flex: 1; min-width: 0; }
.rank-name { font-size: var(--text-sm); font-weight: 600; color: var(--tx-primary); }
.rank-rec { font-size: 13px; color: var(--tx-muted); margin-top: 2px; }
.rank-scores { display: flex; gap: var(--space-3); flex-shrink: 0; }
.rank-score-item { display: flex; flex-direction: column; align-items: center; }
.rank-score-val { font-size: var(--text-sm); font-weight: 700; font-family: var(--font-mono); color: var(--tx-primary); }
.rank-score-val.good { color: #22c55e; }
.rank-score-val.mid  { color: #f59e0b; }
.rank-score-val.bad  { color: #ef4444; }
.rank-score-val.overall { color: var(--si-400); }
.rank-score-lbl { font-size: 11px; color: var(--tx-muted); }
.advisor-winner-note {
  margin-top: var(--space-3); padding: var(--space-3); border-radius: var(--r-md);
  background: rgba(var(--si-rgb), .08); font-size: var(--text-sm); color: var(--tx-secondary);
  border: 1px solid rgba(var(--si-rgb), .2);
}

/* ── Custom Prompts Benchmark ─────────────────────────────────────────────── */
.custom-prompts-list {
  display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2);
}
.custom-prompt-row {
  display: flex; align-items: flex-start; gap: var(--space-2);
}
.custom-prompt-num {
  font-size: 12px; font-family: var(--font-mono); color: var(--tx-muted);
  min-width: 20px; padding-top: 8px; text-align: right; flex-shrink: 0;
}
.custom-prompt-input {
  flex: 1; padding: var(--space-2) var(--space-3);
  background: var(--bg-base); border: 1px solid var(--bd-default);
  border-radius: var(--r-md); color: var(--tx-primary);
  font-size: var(--text-sm); font-family: inherit;
  resize: vertical; min-height: 52px; line-height: 1.5;
}
.custom-prompt-input:focus { outline: none; border-color: var(--si-400); }
.custom-prompt-input:disabled { opacity: .55; }
.custom-prompt-remove {
  padding: 4px 8px; font-size: 16px; line-height: 1;
  border: 1px solid var(--bd-default); border-radius: var(--r-sm);
  background: transparent; color: var(--tx-muted); cursor: pointer;
  margin-top: 6px; flex-shrink: 0;
}
.custom-prompt-remove:hover:not(:disabled) { color: #f87171; border-color: #f87171; }
.custom-prompt-remove:disabled { opacity: .35; cursor: default; }
.custom-prompt-add {
  align-self: flex-start; margin-top: var(--space-2);
  padding: 5px 12px; font-size: var(--text-sm);
  border: 1px dashed var(--bd-default); border-radius: var(--r-md);
  background: transparent; color: var(--tx-muted); cursor: pointer;
  font-family: inherit; transition: color .1s, border-color .1s;
}
.custom-prompt-add:hover:not(:disabled) { color: var(--si-400); border-color: var(--si-400); }
.custom-prompt-add:disabled { opacity: .4; cursor: default; }

.bench-phase-card--wide { width: 100%; }
.custom-log { max-height: 200px; overflow-y: auto; margin-bottom: var(--space-3); }
.custom-results-wrap { overflow-x: auto; margin-top: var(--space-2); }
.custom-results-table { width: 100%; }
.custom-prompt-cell {
  max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  cursor: default;
}
.row-error td { color: var(--tx-muted); font-style: italic; }
</style>
