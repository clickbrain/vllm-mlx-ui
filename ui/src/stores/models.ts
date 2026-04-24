import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

export interface Model {
  id: string
  name: string
  size_gb: number
  quantization: string
  cached: boolean
  active: boolean
}

export interface HFModel {
  modelId: string
  downloads: number
  likes: number
  isMlx: boolean
  tags: string[]
}

export interface DownloadQueueItem {
  id: string
  name: string
  progress: number
  status: 'queued' | 'downloading' | 'done' | 'error'
}

export interface BenchmarkResult {
  model_id: string
  avg_tps: number
  median_tps: number
  min_tps: number
  max_tps: number
  runs: number
}

export interface BenchmarkConfig {
  prompt: string
  runs: number
  max_tokens: number
}

export const useModelsStore = defineStore('models', () => {
  const models = ref<Model[]>([])
  const loading = ref(false)

  // HF search
  const searchQuery = ref('')
  const searchResults = ref<HFModel[]>([])
  const searching = ref(false)

  // Download queue
  const downloadQueue = ref<DownloadQueueItem[]>([])
  const pollIntervals: Record<string, number> = {}

  // Benchmark
  const benchmarkResults = ref<BenchmarkResult[] | null>(null)
  const benchmarking = ref(false)

  async function fetchModels() {
    loading.value = true
    try {
      models.value = await api.get<Model[]>('/models')
    } finally {
      loading.value = false
    }
  }

  async function downloadModel(modelId: string) {
    await api.post<void>('/models/download', { model_id: modelId })
    const existing = downloadQueue.value.find(q => q.id === modelId)
    if (!existing) {
      const name = modelId.split('/').pop() ?? modelId
      downloadQueue.value.push({ id: modelId, name, progress: 0, status: 'queued' })
    }
    pollDownloadStatus(modelId)
  }

  function pollDownloadStatus(modelId: string) {
    if (pollIntervals[modelId]) return

    const interval = window.setInterval(async () => {
      try {
        const status = await api.get<{ status: string; progress: number }>(
          `/models/download_status/${encodeURIComponent(modelId)}`
        )
        const item = downloadQueue.value.find(q => q.id === modelId)
        if (item) {
          item.progress = status.progress ?? 0
          item.status = status.status as DownloadQueueItem['status']
        }
        if (status.status === 'done' || status.status === 'error') {
          window.clearInterval(interval)
          delete pollIntervals[modelId]
          if (status.status === 'done') {
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
    await api.post<void>('/server/load', { model_id: modelId })
    await fetchModels()
  }

  async function deleteModel(modelId: string) {
    await api.delete<void>(`/models/${encodeURIComponent(modelId)}`)
    models.value = models.value.filter(m => m.id !== modelId)
  }

  async function searchHF(query: string) {
    searchQuery.value = query
    searching.value = true
    try {
      searchResults.value = await api.get<HFModel[]>(`/models/search?q=${encodeURIComponent(query)}`)
    } finally {
      searching.value = false
    }
  }

  async function runBenchmark(modelIds: string[], config: BenchmarkConfig) {
    benchmarking.value = true
    benchmarkResults.value = null
    try {
      await api.post<void>('/benchmark', { model_ids: modelIds, config })
      await fetchBenchmarkResults()
    } finally {
      benchmarking.value = false
    }
  }

  async function fetchBenchmarkResults() {
    benchmarkResults.value = await api.get<BenchmarkResult[]>('/benchmark/results')
  }

  return {
    models,
    loading,
    searchQuery,
    searchResults,
    searching,
    downloadQueue,
    benchmarkResults,
    benchmarking,
    fetchModels,
    downloadModel,
    pollDownloadStatus,
    loadModel,
    deleteModel,
    searchHF,
    runBenchmark,
    fetchBenchmarkResults,
  }
})
