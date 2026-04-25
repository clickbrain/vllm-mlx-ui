import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'

interface ServerStatus {
  running: boolean
  healthy: boolean
  pid: number | null
}

interface Metrics {
  status: string
  model: string | null
  uptime_s: number
  num_running: number
  num_waiting: number
  total_requests_processed: number
  total_completion_tokens: number
  metal: { active_memory_gb: number | null; peak_memory_gb: number | null }
}

interface MemoryStats {
  total_gb: number
  available_gb: number
  used_gb: number
  percent: number
  pressure: 'low' | 'medium' | 'high' | 'critical' | 'unknown'
}

interface ServerConfig {
  model?: string
  port?: number
  host?: string
  max_tokens?: number
  context_size?: number
}

export const useServerStore = defineStore('server', () => {
  const status = ref<ServerStatus | null>(null)
  const metrics = ref<Metrics | null>(null)
  const memory = ref<MemoryStats | null>(null)
  const config = ref<ServerConfig | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isRunning = computed(() => status.value?.running ?? false)
  const memoryPercent = computed(() => memory.value?.percent ?? 0)
  const underPressure = computed(() => memoryPercent.value > 75)

  // Derived display values combining status + metrics + config
  const modelId = computed(() => metrics.value?.model ?? config.value?.model ?? null)
  const uptimeSeconds = computed(() => metrics.value?.uptime_s ?? 0)
  const tps = computed<number | null>(() => {
    const m = metrics.value
    if (!m || !m.total_completion_tokens || !m.uptime_s || m.uptime_s < 1) return null
    return Math.round(m.total_completion_tokens / m.uptime_s * 10) / 10
  })
  const baseUrl = computed(() => {
    if (!isRunning.value) return null
    const port = config.value?.port ?? 8080
    return `http://localhost:${port}/v1`
  })

  async function fetchStatus() {
    try {
      status.value = await api.get<ServerStatus>('/status')
      error.value = null
    } catch (e) {
      error.value = String(e)
      status.value = { running: false, healthy: false, pid: null }
    }
  }

  async function fetchMetrics() {
    if (!isRunning.value) return
    try {
      const m = await api.get<Metrics>('/metrics')
      if (m && Object.keys(m).length) metrics.value = m
    } catch {
      // silent — metrics are best-effort while server is starting
    }
  }

  async function fetchConfig() {
    try {
      config.value = await api.get<ServerConfig>('/config')
    } catch {
      // silent
    }
  }

  async function fetchMemory() {
    try {
      memory.value = await api.get<MemoryStats>('/memory/stats')
    } catch {
      // silent
    }
  }

  async function startServer() {
    loading.value = true
    try {
      await api.post('/start')
      await fetchStatus()
    } finally { loading.value = false }
  }

  async function stopServer() {
    loading.value = true
    try {
      await api.post('/stop')
      metrics.value = null
      await fetchStatus()
    } finally { loading.value = false }
  }

  async function fetchLogs(lines = 200): Promise<string[]> {
    try {
      const r = await api.get<{ lines: string[] }>(`/logs?lines=${lines}`)
      return r.lines ?? []
    } catch { return [] }
  }

  async function saveConfig(updates: Partial<ServerConfig>) {
    await api.post('/config', { ...config.value, ...updates })
    await fetchConfig()
  }

  function startPolling(intervalMs = 3000): () => void {
    fetchStatus()
    fetchMemory()
    fetchConfig()
    const id = setInterval(() => {
      fetchStatus()
      fetchMemory()
      fetchConfig()
      if (isRunning.value) fetchMetrics()
    }, intervalMs)
    return () => clearInterval(id)
  }

  async function releaseMemory() {
    try { await api.post('/memory/release') }
    catch { /* silent */ }
  }

  async function shutdown() {
    await api.post('/shutdown', {})
  }

  async function restart() {
    await api.post('/restart', {})
  }

  async function clearCache(cacheType: string) {
    await api.delete(`/cache/${cacheType}`)
  }

  return {
    status, metrics, memory, config, loading, error,
    isRunning, memoryPercent, underPressure,
    modelId, uptimeSeconds, tps, baseUrl,
    fetchStatus, fetchMetrics, fetchConfig, fetchMemory,
    startServer, stopServer, fetchLogs, startPolling, releaseMemory, saveConfig,
    shutdown, restart, clearCache,
  }
})

