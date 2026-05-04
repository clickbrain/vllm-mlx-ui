// SPDX-License-Identifier: Apache-2.0
/**
 * Server store — manages inference server status, metrics, memory, and config.
 *
 * Polling strategy (startPolling):
 *   - status, memory, config: every 3 s always
 *   - metrics: every 3 s only while server is running
 *
 * Key derived values:
 *   - tps: returns 0 (not null) when server is running but has processed no tokens yet,
 *     so the UI can display "0.0 tok/s" instead of "—"
 *   - metricsError: set when metrics fetch fails; cleared on next success
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'

interface ServerStatus {
  running: boolean
  healthy: boolean
  pid: number | null
  crash_log?: string
  /** Health data from the inference server's /health endpoint */
  health?: {
    model_type?: 'llm' | 'mllm'
    model_name?: string
    [key: string]: unknown
  }
}

export interface Metrics {
  status: string
  model: string | null
  uptime_s: number
  num_running: number
  num_waiting: number
  total_requests_processed: number
  total_prompt_tokens: number
  total_completion_tokens: number
  metal: { active_memory_gb: number | null; peak_memory_gb: number | null }
  /** Live list of active request objects (optional, presence depends on server version) */
  requests?: Array<{ id: string; model: string; tokens_generated: number; elapsed_s: number }>
}

interface MemoryStats {
  total_gb: number
  available_gb: number
  used_gb: number
  percent: number
  pressure: 'low' | 'medium' | 'high' | 'critical' | 'unknown'
}

export interface ServerConfig {
  model?: string
  engine_id?: string
  port?: number
  host?: string
  max_tokens?: number
  context_size?: number
  startup_model_behavior?: 'auto' | 'ask' | 'none'
  api_key?: string
  hf_token?: string
  offline_mode?: boolean
  auto_model_switch?: boolean
}

export const useServerStore = defineStore('server', () => {
  const status = ref<ServerStatus | null>(null)
  const metrics = ref<Metrics | null>(null)
  const memory = ref<MemoryStats | null>(null)
  const config = ref<ServerConfig | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const crashLog = ref<string | null>(null)
  /** Set when /metrics fetch fails; cleared on next successful fetch */
  const metricsError = ref(false)
  /** Ring buffer of sampled metrics — max 120 entries (~10 min at 5 s interval) */
  const metricsHistory = ref<Array<{
    time: string; active: number; queued: number; total: number; memory_gb: number
  }>>([])
  const MAX_HISTORY = 120

  /**
   * The active inference engine id (e.g. 'vllm-mlx' or 'rapid-mlx').
   * Populated from the /poll runtime field or config fallback.
   */
  const engineId = computed(() => config.value?.engine_id ?? 'vllm-mlx')


  const memoryPercent = computed(() => memory.value?.percent ?? 0)
  const underPressure = computed(() => memoryPercent.value > 75)

  // Derived display values combining status + metrics + config
  const modelId = computed(() => metrics.value?.model ?? config.value?.model ?? null)
  const uptimeSeconds = computed(() => metrics.value?.uptime_s ?? 0)
  const numRunning = computed(() => metrics.value?.num_running ?? 0)
  const numWaiting = computed(() => metrics.value?.num_waiting ?? 0)
  const totalRequests = computed(() => metrics.value?.total_requests_processed ?? 0)
  const totalPromptTokens = computed(() => metrics.value?.total_prompt_tokens ?? 0)
  const totalCompletionTokens = computed(() => metrics.value?.total_completion_tokens ?? 0)
  const metalMemoryGb = computed(() => metrics.value?.metal?.active_memory_gb ?? null)
  const peakMemoryGb = computed(() => metrics.value?.metal?.peak_memory_gb ?? null)

  /**
   * True when the loaded model supports image/video inputs (mlx-vlm / MLLM).
   * Derived from the health endpoint's model_type field ("mllm" vs "llm").
   */
  const isMultimodal = computed(() => status.value?.health?.model_type === 'mllm')

  /**
   * Returns tokens/sec as a number.
   * Returns 0 (not null) when server is running but no tokens processed yet,
   * so the UI shows "0.0 tok/s" rather than "—".
   * Returns null only when the server is not running (no metrics available).
   */
  const tps = computed<number | null>(() => {
    if (!isRunning.value) return null
    const m = metrics.value
    if (!m || m.uptime_s < 1) return 0
    if (!m.total_completion_tokens) return 0
    return Math.round(m.total_completion_tokens / m.uptime_s * 10) / 10
  })

  const baseUrl = computed(() => {
    if (!isRunning.value) return null
    const port = config.value?.port ?? 8080
    return `http://localhost:${port}/v1`
  })

  async function fetchStatus() {
    try {
      const s = await api.get<ServerStatus>('/status')
      status.value = s
      // Capture crash log when process died; clear it when running
      if (s.running) {
        crashLog.value = null
      } else if (s.crash_log) {
        crashLog.value = s.crash_log
      }
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
      if (m && Object.keys(m).length) {
        metrics.value = m
        metricsError.value = false
        // Append to history ring buffer
        metricsHistory.value.push({
          time: new Date().toISOString(),
          active: m.num_running ?? 0,
          queued: m.num_waiting ?? 0,
          total: m.total_requests_processed ?? 0,
          memory_gb: m.metal?.active_memory_gb ?? 0,
        })
        if (metricsHistory.value.length > MAX_HISTORY)
          metricsHistory.value = metricsHistory.value.slice(-MAX_HISTORY)
      }
    } catch {
      // Metrics are best-effort during server startup; flag for UI staleness indicator
      metricsError.value = true
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
    crashLog.value = null
    try {
      await api.post('/start')
      // Poll until running — inference server takes 30–90 s to boot a model
      const deadline = Date.now() + 120_000
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 2500))
        await fetchStatus()
        if (isRunning.value) break
        if (crashLog.value) break  // crash detected — abort early
      }
    } finally { loading.value = false }
  }

  async function stopServer() {
    loading.value = true
    try {
      await api.post('/stop')
      metrics.value = null
      metricsError.value = false
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

  async function fetchCacheStats(): Promise<Record<string, unknown> | null> {
    try { return await api.get<Record<string, unknown>>('/cache/stats') }
    catch { return null }
  }

  /**
   * Single batched fetch: returns status, metrics, memory, config in one HTTP call.
   * Falls back to individual fetches for older servers without /poll.
   */
  async function fetchAllBatched() {
    try {
      const r = await api.get<{
        status: ServerStatus;
        metrics: Metrics | Record<string, never>;
        memory: MemoryStats;
        config: ServerConfig;
        runtime?: { engine_id?: string; model?: string; started_at?: string };
      }>('/poll')

      // Status
      status.value = r.status
      if (r.status.running) {
        crashLog.value = null
      } else if (r.status.crash_log) {
        crashLog.value = r.status.crash_log
      }
      error.value = null

      // Metrics
      if (r.metrics && Object.keys(r.metrics).length) {
        metrics.value = r.metrics as Metrics
        metricsError.value = false
        metricsHistory.value.push({
          time: new Date().toISOString(),
          active: (r.metrics as Metrics).num_running ?? 0,
          queued: (r.metrics as Metrics).num_waiting ?? 0,
          total: (r.metrics as Metrics).total_requests_processed ?? 0,
          memory_gb: (r.metrics as Metrics).metal?.active_memory_gb ?? 0,
        })
        if (metricsHistory.value.length > MAX_HISTORY)
          metricsHistory.value = metricsHistory.value.slice(-MAX_HISTORY)
      }

      // Memory
      memory.value = r.memory

      // Config — merge runtime.engine_id into config so engineId computed stays fresh
      config.value = r.runtime?.engine_id
        ? { ...r.config, engine_id: r.runtime.engine_id }
        : r.config
    } catch {
      // Fallback: if /poll doesn't exist (old server), do individual fetches
      await fetchStatus()
      if (isRunning.value) await fetchMetrics()
      await fetchMemory()
      await fetchConfig()
    }
  }

  /**
   * Starts background polling for all server state.
   * Pauses when the tab is hidden (user switches away) to save CPU/network,
   * resumes when the tab becomes visible again.
   * Returns a cleanup function to stop polling entirely.
   */
  function startPolling(intervalMs = 3000): () => void {
    let currentInterval: ReturnType<typeof setInterval> = setInterval(() => {
      fetchAllBatched()
    }, intervalMs)

    // Initial fetch
    fetchAllBatched()

    const onVisibilityChange = () => {
      if (document.hidden) {
        clearInterval(currentInterval)
      } else {
        // Resume: immediate fetch then restart interval
        fetchAllBatched()
        currentInterval = setInterval(() => {
          fetchAllBatched()
        }, intervalMs)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      clearInterval(currentInterval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }

  async function releaseMemory() {
    try { await api.post('/memory/release') }
    catch { /* silent */ }
  }

  async function shutdown() {
    await api.post('/shutdown', {})
  }

  async function toggleServer() {
    if (isRunning.value) {
      await stopServer()
    } else {
      await startServer()
    }
  }

  async function restart() {
    await api.post('/restart', {})
  }

  async function clearCache(cacheType: string) {
    await api.delete(`/cache/${cacheType}`)
  }

  return {
    status, metrics, memory, config, loading, error, crashLog, metricsError, metricsHistory,
    isRunning, memoryPercent, underPressure, isMultimodal, engineId,
    modelId, uptimeSeconds, tps, baseUrl,
    numRunning, numWaiting, totalRequests, totalPromptTokens, totalCompletionTokens,
    metalMemoryGb, peakMemoryGb,
    fetchStatus, fetchMetrics, fetchConfig, fetchMemory, fetchCacheStats,
    startServer, stopServer, toggleServer, fetchLogs, startPolling, releaseMemory, saveConfig,
    shutdown, restart, clearCache,
  }
})

