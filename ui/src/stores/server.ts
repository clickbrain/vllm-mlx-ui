import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'

interface ServerStatus {
  running: boolean
  model: string | null
  uptime: number
  tokens_per_sec: number
}

interface MemoryStats {
  total_gb: number
  used_gb: number
  percent: number
  pressure: 'normal' | 'warning' | 'critical'
}

export const useServerStore = defineStore('server', () => {
  const status = ref<ServerStatus | null>(null)
  const memory = ref<MemoryStats | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isRunning = computed(() => status.value?.running ?? false)
  const memoryPercent = computed(() => memory.value?.percent ?? 0)
  const underPressure = computed(() => memoryPercent.value > 75)

  async function fetchStatus() {
    try {
      status.value = await api.get<ServerStatus>('/status')
    } catch (e) {
      error.value = String(e)
    }
  }

  async function fetchMemory() {
    try {
      memory.value = await api.get<MemoryStats>('/memory/stats')
    } catch {
      // silent — memory gauge shows stale data
    }
  }

  async function startServer() {
    loading.value = true
    try { await api.post('/server/start') } finally { loading.value = false }
  }

  async function stopServer() {
    loading.value = true
    try { await api.post('/server/stop') } finally { loading.value = false }
  }

  function startPolling(intervalMs = 3000): () => void {
    fetchStatus()
    fetchMemory()
    const id = setInterval(() => { fetchStatus(); fetchMemory() }, intervalMs)
    return () => clearInterval(id)
  }

  return {
    status, memory, loading, error,
    isRunning, memoryPercent, underPressure,
    fetchStatus, fetchMemory, startServer, stopServer, startPolling
  }
})
