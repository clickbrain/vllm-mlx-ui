// SPDX-License-Identifier: Apache-2.0
/**
 * Models store — manages cached models, HuggingFace search, download queue, and benchmarks.
 *
 * Fit level thresholds (model size as % of available RAM):
 *   FIT_PERFECT  < 50 %
 *   FIT_GOOD     50–75 %
 *   FIT_MARGINAL 75–90 %
 *   FIT_TOO_TIGHT > 90 %
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { useServerStore } from './server'

export interface Model {
  id: string
  name: string
  size_gb: number
  quantization: string
  cached: boolean
  active: boolean
  engine?: string   // set for engine-discovered models (e.g. ds4)
  source?: string   // "engine" for engine-discovered, undefined for HF cache
}

export interface HFModel {
  id: string
  downloads: number
  likes: number
  is_mlx: boolean
  tags: string[]
  last_modified?: string
  created_at?: string     // HF repo creation date — use for recency (more reliable than last_modified)
  size_gb?: number
  fit_level?: string  // perfect | good | marginal | too_tight
  trending_score?: number
  family_data?: FamilyData | null
}

export interface DownloadQueueItem {
  id: string
  name: string
  progress: number
  status: 'queued' | 'downloading' | 'done' | 'error'
  error?: string
}

export interface BenchmarkResult {
  model_id: string
  avg_tps: number
  median_tps: number
  min_tps: number
  max_tps: number
  runs: number
  avg_ttft_ms?: number
}

export interface HardwareFingerprint {
  chip: string
  chip_gen: string
  total_ram_gb: number
  os_version: string
  python_version: string
  mlx_version: string
  dashboard_version: string
}

export interface QualitySuiteResult {
  correct: number
  total: number
  accuracy: number
  accuracy_ci_95?: [number, number]
}

export interface PerPromptResult {
  prompt: string
  ttft_ms?: number
  tps?: number
  total_ms?: number
  tokens?: number
  error?: string
}

export interface ServerSettingsSnapshot {
  kv_cache_quantization?: boolean
  kv_cache_quantization_bits?: number
  use_paged_cache?: boolean
  continuous_batching?: boolean
  gpu_memory_utilization?: number
  enable_prefix_cache?: boolean
  ssd_cache_dir?: string
  ssd_cache_max_gb?: number
}

export interface BenchmarkHistoryEntry {
  id: number
  timestamp: string
  model_id: string
  avg_tps: number
  avg_ttft_ms?: number
  benchmark_type?: 'speed' | 'quality' | 'custom'
  overall_score?: number
  suites?: Record<string, QualitySuiteResult>
  label?: string
  max_tokens?: number
  enable_thinking?: boolean
  server_settings?: ServerSettingsSnapshot
  per_prompt?: PerPromptResult[]
  custom_prompts?: string[]
  dashboard_version?: string
  engine_id?: string
  hardware?: HardwareFingerprint
}

export interface BenchmarkScores {
  mmlu?: number
  humaneval?: number
  math?: number
  gpqa?: number
  ifeval?: number
  source: 'fallback' | 'leaderboard' | 'none'
  matched_key?: string
}

export interface FamilyScores {
  mmlu?: number | null
  humaneval?: number | null
  math?: number | null
  gpqa?: number | null
  ifeval?: number | null
}

export interface FamilyData {
  family_key: string
  family_name: string
  release_date: string
  arch_type: string
  param_count_b: number
  tier: number
  scores: FamilyScores
  confidence: string
}

function deriveQuantization(modelId: string): string {
  const id = modelId.toLowerCase()
  if (id.includes('8bit') || id.includes('8-bit') || id.includes('q8')) return '8-bit'
  if (id.includes('6bit') || id.includes('6-bit') || id.includes('q6')) return '6-bit'
  if (id.includes('4bit') || id.includes('4-bit') || id.includes('q4')) return '4-bit'
  if (id.includes('3bit') || id.includes('3-bit') || id.includes('q3')) return '3-bit'
  if (id.includes('2bit') || id.includes('2-bit') || id.includes('q2')) return '2-bit'
  if (id.includes('fp16') || id.includes('float16')) return 'fp16'
  if (id.includes('bf16') || id.includes('bfloat16')) return 'bf16'
  return 'unknown'
}

/**
 * Classify model size against total unified memory.
 * Returns keys matching HFSearchResult's fitInfo map: perfect | good | marginal | too_tight
 * @param sizeGb   Model file size in GB
 * @param totalGb  Total system unified memory in GB (hardware spec)
 */
function computeFitLevel(sizeGb: number, totalGb: number): string {
  if (!totalGb || totalGb <= 0) return 'unknown'
  const pct = (sizeGb / totalGb) * 100
  if (pct < 50) return 'perfect'
  if (pct < 75) return 'good'
  if (pct < 90) return 'marginal'
  return 'too_tight'
}

export const useModelsStore = defineStore('models', () => {
  const serverStore = useServerStore()
  const models = ref<Model[]>([])
  const loading = ref(false)

  const searchQuery = ref('')
  const searchResults = ref<HFModel[]>([])
  const searching = ref(false)
  const searchOffset = ref(0)
  const searchHasMore = ref(false)
  const mlxOnly = ref(true)

  const downloadQueue = ref<DownloadQueueItem[]>([])
  const pollIntervals: Record<string, number> = {}

  const benchmarkResults = ref<BenchmarkResult[] | null>(null)
  const benchmarkHistory = ref<BenchmarkHistoryEntry[]>([])
  const benchmarking = ref(false)
  const benchmarkRunning = ref(false)
  const loadingModelId = ref<string | null>(null)
  const actionError = ref<string | null>(null)
  const serverRestartingFor = ref<string | null>(null)
  /** Set when backend returns needs_install; App.vue global modal reads this */
  const pendingInstall = ref<{ engineId: string; engineName: string; modelId: string } | null>(null)
  const modelScores = ref<Record<string, BenchmarkScores>>({})

  async function fetchModels() {
    loading.value = true
    try {
      const activeModel = serverStore.modelId
      const raw = await api.get<Array<{ id: string; size_gb: number; size_bytes?: number; engine?: string; source?: string }>>('/models/cached')
      models.value = raw.map(m => ({
        id: m.id,
        name: m.id.split('/').pop() ?? m.id,
        size_gb: m.size_gb,
        quantization: deriveQuantization(m.id),
        cached: true,
        active: m.id === activeModel,
        engine: m.engine,
        source: m.source,
      }))
    } finally {
      loading.value = false
    }
  }

  async function downloadModel(modelId: string, token = '') {
    const hfToken = token || localStorage.getItem('vmui_hf_token') || ''
    // Guard: don't start a duplicate download
    const existing = downloadQueue.value.find(q => q.id === modelId)
    if (existing && (existing.status === 'queued' || existing.status === 'downloading')) return

    await api.post<void>('/models/download', { model_id: modelId, token: hfToken })
    const name = modelId.split('/').pop() ?? modelId
    if (!existing) {
      downloadQueue.value.push({ id: modelId, name, progress: 0, status: 'queued' })
    }
    pollDownloadStatus(modelId)
  }

  function pollDownloadStatus(modelId: string) {
    if (pollIntervals[modelId]) return

    const interval = window.setInterval(async () => {
      try {
        const s = await api.get<{
          status: string
          error: string | null
          bytes_downloaded: number
          total_bytes: number
        }>(`/models/download_status/${encodeURIComponent(modelId)}`)

        const item = downloadQueue.value.find(q => q.id === modelId)
        if (item) {
          item.status = s.status as DownloadQueueItem['status']
          item.error = s.error ?? undefined
          item.progress = s.total_bytes > 0
            ? Math.round((s.bytes_downloaded / s.total_bytes) * 100)
            : (s.status === 'done' ? 100 : 0)
        }

        if (s.status === 'done' || s.status === 'error') {
          window.clearInterval(interval)
          delete pollIntervals[modelId]
          if (s.status === 'done') {
            setTimeout(() => {
              downloadQueue.value = downloadQueue.value.filter(q => q.id !== modelId)
              fetchModels()
            }, 1500)
          }
        }
      } catch {
        // Don't clear the interval on a transient network error — keep the
        // item visible and retry on the next tick.
      }
    }, 2000)

    pollIntervals[modelId] = interval
  }

  /** Re-attach polling for any downloads that are still in-progress but have
   *  no active poll interval (e.g. after navigating away and back). */
  function resumeActiveDownloadPolls() {
    for (const item of downloadQueue.value) {
      if (item.status === 'queued' || item.status === 'downloading') {
        pollDownloadStatus(item.id)
      }
    }
  }

  async function loadModel(modelId: string) {
    loadingModelId.value = modelId
    actionError.value = null
    try {
      const result = await api.post<{ ok?: boolean; restarted?: boolean; model?: string; engine_id?: string; needs_install?: string }>('/server/load', { model_id: modelId })

      // Backend says a required engine isn't installed — surface the global install modal.
      // Server state hasn't changed, so don't fetch config/status/models.
      if (result?.needs_install) {
        const knownNames: Record<string, string> = {
          'lightning-mlx': 'Lightning MLX',
          'rapid-mlx': 'Rapid MLX',
          'vllm-mlx': 'vLLM MLX',
          'ds4': 'DeepSeek V4 Flash (ds4)',
        }
        pendingInstall.value = {
          engineId: result.needs_install,
          engineName: knownNames[result.needs_install] ?? result.needs_install,
          modelId,
        }
        return result
      }

      await serverStore.fetchConfig()
      await serverStore.fetchStatus()
      await fetchModels()
      if (result.restarted) {
        serverRestartingFor.value = modelId
        // Poll until server is running again (max 90s)
        await new Promise<void>(resolve => {
          let elapsed = 0
          const poll = setInterval(async () => {
            elapsed += 2
            await serverStore.fetchStatus()
            await serverStore.fetchMetrics()
            if (serverStore.isRunning || elapsed >= 90) {
              clearInterval(poll)
              serverRestartingFor.value = null
              await fetchModels() // re-fetch to update active flag with real metrics
              resolve()
            }
          }, 2000)
        })
      }
      return result
    } catch (e) {
      actionError.value = String(e)
      throw e
    } finally {
      loadingModelId.value = null
    }
  }

  function clearPendingInstall() {
    pendingInstall.value = null
  }

  async function retryLoadAfterInstall() {
    const modelId = pendingInstall.value?.modelId
    pendingInstall.value = null
    if (modelId) await loadModel(modelId)
  }

  async function deleteModel(modelId: string) {
    await api.delete<void>(`/models/${encodeURIComponent(modelId)}`)
    models.value = models.value.filter(m => m.id !== modelId)
  }

    async function searchHF(query: string, mlxOnlyFlag = false, offset = 0, sort = 'downloads', append = false, limit = 50, direction: 'asc' | 'desc' = 'desc') {
    if (!append) {
      searchQuery.value = query
      searchOffset.value = 0
    }
    searching.value = true
    actionError.value = null
    try {
      const params = new URLSearchParams()
      if (query.trim()) params.set('q', query.trim())
      if (mlxOnlyFlag) params.set('tags', 'mlx')
      params.set('limit', String(limit))
      params.set('offset', String(offset))
      params.set('sort', sort)
      params.set('direction', direction)
      const resp = await api.get<{ results: Array<HFModel & { error?: string }>; has_more: boolean }>(`/models/search?${params}`)
      const results = resp.results.filter(r => !r.error)
      // Annotate each result with fit_level based on total RAM (hardware spec)
      const totalGb = serverStore.memory?.total_gb ?? 0
      const annotated = results.map(r => ({
        ...r,
        fit_level: r.size_gb ? computeFitLevel(r.size_gb, totalGb) : undefined,
      }))
      searchHasMore.value = resp.has_more
      searchOffset.value = offset + results.length
      if (append) {
        searchResults.value = [...searchResults.value, ...annotated]
      } else {
        searchResults.value = annotated
      }
      if (!append && searchResults.value.length === 0 && resp.results.length > 0 && resp.results[0].error) {
        actionError.value = `Search error: ${resp.results[0].error}`
      }
    } catch (e) {
      actionError.value = String(e)
      if (!append) searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  async function searchHFMore(sort = 'downloads', direction: 'asc' | 'desc' = 'desc') {
    await searchHF(searchQuery.value, mlxOnly.value, searchOffset.value, sort, true, 50, direction)
  }

  async function runBenchmark(modelIds: string[], cfg: BenchmarkConfig) {
    benchmarking.value = true
    benchmarkRunning.value = true
    try {
      await api.post<void>('/benchmark/run', { model_ids: modelIds, config: cfg })
      // Poll until done
      await new Promise<void>(resolve => {
        const poll = setInterval(async () => {
          try {
            const s = await api.get<{ running: boolean }>('/benchmark/status')
            if (!s.running) {
              clearInterval(poll)
              resolve()
            }
          } catch { clearInterval(poll); resolve() }
        }, 3000)
      })
      await fetchBenchmarkResults()
    } finally {
      benchmarking.value = false
      benchmarkRunning.value = false
    }
  }

  async function fetchBenchmarkResults() {
    const raw = await api.get<Array<Record<string, unknown>>>('/benchmarks')

    /**
     * The API returns tokens_per_second as an object:
     *   { generation_mean, generation_max, processing_mean, total_throughput }
     * ttft_ms is also an object: { mean, min, max, p50, p95 }
     * tpot_ms: { mean, min, max }
     * We must extract sub-fields — Number({...}) yields NaN.
     */
    function parseTps(r: Record<string, unknown>): {
      avg_tps: number; median_tps: number; min_tps: number; max_tps: number
    } {
      const raw = r.tokens_per_second
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        const t = raw as Record<string, number>
        return {
          avg_tps: t.generation_mean ?? t.total_throughput ?? 0,
          median_tps: t.generation_mean ?? 0,
          min_tps: t.processing_mean ?? t.generation_mean ?? 0,
          max_tps: t.generation_max ?? t.generation_mean ?? 0,
        }
      }
      // Quality benchmark results store speed under overall_speed.avg_tokens_per_sec
      if (r.overall_speed && typeof r.overall_speed === 'object' && !Array.isArray(r.overall_speed)) {
        const os = r.overall_speed as Record<string, number>
        const tps = os.avg_tokens_per_sec ?? 0
        return { avg_tps: tps, median_tps: tps, min_tps: tps, max_tps: tps }
      }
      // Older quality results: speed nested per-suite — average across suites
      if (r.suites && typeof r.suites === 'object' && !Array.isArray(r.suites)) {
        const suites = r.suites as Record<string, Record<string, unknown>>
        const tpsVals = Object.values(suites)
          .map(s => (s.speed as Record<string, number> | undefined)?.avg_tokens_per_sec)
          .filter((v): v is number => typeof v === 'number' && v > 0)
        if (tpsVals.length > 0) {
          const tps = tpsVals.reduce((a, b) => a + b, 0) / tpsVals.length
          return { avg_tps: tps, median_tps: tps, min_tps: tps, max_tps: tps }
        }
      }
      // Flat numeric fallback for older or custom records
      const flat = Number(r.avg_tps ?? r.tokens_per_second ?? 0)
      return {
        avg_tps: flat,
        median_tps: Number(r.median_tps ?? flat),
        min_tps: Number(r.min_tps ?? 0),
        max_tps: Number(r.max_tps ?? flat),
      }
    }

    function parseTtft(r: Record<string, unknown>): number | undefined {
      const raw = r.ttft_ms
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        return (raw as Record<string, number>).mean
      }
      if (r.avg_ttft_ms !== undefined) return Number(r.avg_ttft_ms)
      // Quality benchmark results store TTFT under overall_speed.avg_ttft_ms
      if (r.overall_speed && typeof r.overall_speed === 'object' && !Array.isArray(r.overall_speed)) {
        const os = r.overall_speed as Record<string, number>
        if (os.avg_ttft_ms !== undefined) return Number(os.avg_ttft_ms)
      }
      // Older quality results: TTFT nested per-suite — average across suites
      if (r.suites && typeof r.suites === 'object' && !Array.isArray(r.suites)) {
        const suites = r.suites as Record<string, Record<string, unknown>>
        const ttftVals = Object.values(suites)
          .map(s => (s.speed as Record<string, number> | undefined)?.avg_ttft_ms)
          .filter((v): v is number => typeof v === 'number' && v > 0)
        if (ttftVals.length > 0)
          return ttftVals.reduce((a, b) => a + b, 0) / ttftVals.length
      }
      return undefined
    }

    benchmarkResults.value = raw
      .filter(r => (r.model ?? r.model_id ?? '') !== '')
      .map(r => {
        const tps = parseTps(r)
        return {
          model_id: String(r.model ?? r.model_id ?? ''),
          ...tps,
          runs: Number(r.runs ?? r.num_runs ?? 1),
          avg_ttft_ms: parseTtft(r),
        }
      })

    benchmarkHistory.value = raw.map((r, idx) => {
      const tps = parseTps(r)
      const benchType: BenchmarkHistoryEntry['benchmark_type'] =
        (r.benchmark_type as BenchmarkHistoryEntry['benchmark_type']) ??
        (r.suites ? 'quality' : r.custom_prompts ? 'custom' : 'speed')
      const entry: BenchmarkHistoryEntry = {
        id: Number(r.id ?? idx),
        timestamp: String(r.timestamp ?? r.created_at ?? ''),
        model_id: String(r.model ?? r.model_id ?? ''),
        avg_tps: tps.avg_tps,
        avg_ttft_ms: parseTtft(r),
        benchmark_type: benchType,
        label: r.label ? String(r.label) : undefined,
        max_tokens: r.max_tokens != null ? Number(r.max_tokens) : undefined,
        enable_thinking: r.enable_thinking != null ? Boolean(r.enable_thinking) : undefined,
        server_settings: r.server_settings ?? undefined,
        per_prompt: Array.isArray(r.per_prompt) ? r.per_prompt : undefined,
        custom_prompts: Array.isArray(r.custom_prompts) ? r.custom_prompts : undefined,
        dashboard_version: r.dashboard_version ? String(r.dashboard_version) : undefined,
        engine_id: r.server_settings?.engine_id
          ? String(r.server_settings.engine_id)
          : r.engine_id ? String(r.engine_id) : undefined,
      }
      if (r.suites) {
        entry.overall_score = Number(r.overall_score ?? 0)
        entry.suites = r.suites as Record<string, QualitySuiteResult>
      }
      return entry
    })
  }

  async function deleteBenchmarkResult(id: number) {
    await api.delete(`/benchmarks/${id}`)
    await fetchBenchmarkResults()
  }

  async function clearAllBenchmarks() {
    await api.delete('/benchmarks')
    benchmarkResults.value = null
    benchmarkHistory.value = []
  }

  async function fetchModelScores(ids: string[]) {
    if (!ids.length) return
    try {
      const raw = await api.post<Record<string, BenchmarkScores>>('/models/scores', { ids })
      modelScores.value = { ...modelScores.value, ...raw }
    } catch (e) {
      // Non-fatal: badges just won't appear
    }
  }

  function clearAllDownloadPolls() {
    for (const id of Object.keys(pollIntervals)) {
      window.clearInterval(pollIntervals[id])
      delete pollIntervals[id]
    }
  }

  /** Best (highest avg_tps) benchmark result per model_id, for display in library cards. */
  const bestBenchmarkPerModel = computed(() => {
    const map = new Map<string, BenchmarkHistoryEntry>()
    for (const entry of benchmarkHistory.value) {
      const existing = map.get(entry.model_id)
      if (!existing || entry.avg_tps > existing.avg_tps)
        map.set(entry.model_id, entry)
    }
    return map
  })

  return {
    models, loading,
    searchQuery, searchResults, searching, searchOffset, searchHasMore, mlxOnly,
    downloadQueue,
    benchmarkResults, benchmarkHistory, benchmarking, benchmarkRunning,
    bestBenchmarkPerModel,
    modelScores,
    loadingModelId, actionError, serverRestartingFor, pendingInstall,
    fetchModels, downloadModel, pollDownloadStatus, resumeActiveDownloadPolls, clearAllDownloadPolls,
    loadModel, deleteModel, clearPendingInstall, retryLoadAfterInstall,
    searchHF, searchHFMore,
    fetchModelScores,
    runBenchmark, fetchBenchmarkResults, deleteBenchmarkResult, clearAllBenchmarks,
  }
})

