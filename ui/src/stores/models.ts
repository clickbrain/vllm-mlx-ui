import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import { useServerStore } from './server'

export interface Model {
  id: string
  name: string
  size_gb: number
  quantization: string
  cached: boolean
  active: boolean
}

export interface HFModel {
  id: string
  downloads: number
  likes: number
  is_mlx: boolean
  tags: string[]
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
}

export interface BenchmarkHistoryEntry {
  id: number
  timestamp: string
  model_id: string
  avg_tps: number
}

export interface BenchmarkConfig {
  prompt: string
  runs: number
  max_tokens: number
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

export const useModelsStore = defineStore('models', () => {
  const serverStore = useServerStore()
  const models = ref<Model[]>([])
  const loading = ref(false)

  const searchQuery = ref('')
  const searchResults = ref<HFModel[]>([])
  const searching = ref(false)

  const downloadQueue = ref<DownloadQueueItem[]>([])
  const pollIntervals: Record<string, number> = {}

  const benchmarkResults = ref<BenchmarkResult[] | null>(null)
  const benchmarkHistory = ref<BenchmarkHistoryEntry[]>([])
  const benchmarking = ref(false)
  const benchmarkRunning = ref(false)
  const loadingModelId = ref<string | null>(null)
  const actionError = ref<string | null>(null)

  async function fetchModels() {
    loading.value = true
    try {
      const activeModel = serverStore.modelId
      const raw = await api.get<Array<{ id: string; size_gb: number; size_bytes?: number }>>('/models/cached')
      models.value = raw.map(m => ({
        id: m.id,
        name: m.id.split('/').pop() ?? m.id,
        size_gb: m.size_gb,
        quantization: deriveQuantization(m.id),
        cached: true,
        active: m.id === activeModel,
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
        window.clearInterval(interval)
        delete pollIntervals[modelId]
      }
    }, 2000)

    pollIntervals[modelId] = interval
  }

  async function loadModel(modelId: string) {
    loadingModelId.value = modelId
    actionError.value = null
    try {
      await api.post<void>('/server/load', { model_id: modelId })
      await fetchModels()
      await serverStore.fetchStatus()
      await serverStore.fetchConfig()
    } catch (e) {
      actionError.value = String(e)
      throw e
    } finally {
      loadingModelId.value = null
    }
  }

  async function deleteModel(modelId: string) {
    await api.delete<void>(`/models/${encodeURIComponent(modelId)}`)
    models.value = models.value.filter(m => m.id !== modelId)
  }

  async function searchHF(query: string, mlxOnly = false) {
    searchQuery.value = query
    searching.value = true
    actionError.value = null
    try {
      const params = new URLSearchParams()
      if (query.trim()) params.set('q', query.trim())
      if (mlxOnly) params.set('tags', 'mlx')
      params.set('limit', '40')
      const results = await api.get<Array<HFModel & { error?: string }>>(`/models/search?${params}`)
      searchResults.value = results.filter(r => !r.error)
      if (searchResults.value.length === 0 && results.length > 0 && results[0].error) {
        actionError.value = `Search error: ${results[0].error}`
      }
    } catch (e) {
      actionError.value = String(e)
      searchResults.value = []
    } finally {
      searching.value = false
    }
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
    // Server returns stored benchmark records; map to our shape
    benchmarkResults.value = raw.map(r => ({
      model_id: String(r.model ?? r.model_id ?? ''),
      avg_tps: Number(r.avg_tps ?? r.tokens_per_second ?? 0),
      median_tps: Number(r.median_tps ?? r.avg_tps ?? 0),
      min_tps: Number(r.min_tps ?? 0),
      max_tps: Number(r.max_tps ?? r.avg_tps ?? 0),
      runs: Number(r.runs ?? r.num_runs ?? 1),
    }))
    benchmarkHistory.value = raw.map((r, idx) => ({
      id: Number(r.id ?? idx),
      timestamp: String(r.timestamp ?? r.created_at ?? ''),
      model_id: String(r.model ?? r.model_id ?? ''),
      avg_tps: Number(r.avg_tps ?? r.tokens_per_second ?? 0),
    }))
  }

  async function deleteBenchmarkResult(id: number) {
    await api.delete(`/benchmarks/${id}`)
    await fetchBenchmarkResults()
  }

  return {
    models, loading,
    searchQuery, searchResults, searching,
    downloadQueue,
    benchmarkResults, benchmarkHistory, benchmarking, benchmarkRunning,
    loadingModelId, actionError,
    fetchModels, downloadModel, pollDownloadStatus,
    loadModel, deleteModel,
    searchHF,
    runBenchmark, fetchBenchmarkResults, deleteBenchmarkResult,
  }
})

