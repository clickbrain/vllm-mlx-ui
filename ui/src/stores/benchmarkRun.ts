// SPDX-License-Identifier: Apache-2.0
/**
 * Singleton Pinia store for active benchmark run state.
 *
 * Keeping this in a store (rather than component-local refs) ensures state
 * survives navigation regardless of KeepAlive behaviour. The polling timers
 * live at module level in BenchmarkView.vue but write into this store, so the
 * log / status remains visible when the user navigates away and returns.
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useBenchmarkRunStore = defineStore('benchmarkRun', () => {
  const benchRunning   = ref(false)
  const speedPhase     = ref<'idle' | 'running' | 'done' | 'error'>('idle')
  const qualityPhase   = ref<'idle' | 'running' | 'done' | 'error'>('idle')
  const qualityLines   = ref<string[]>([])
  const benchStopping  = ref(false)
  const qualityRunId   = ref<string | null>(null)
  const lastRunQuality = ref<Record<string, any> | null>(null)
  const lastRunSpeed   = ref<any | null>(null)
  const lastRunModel   = ref('')
  const lastRunTime    = ref('')

  return {
    benchRunning,
    speedPhase,
    qualityPhase,
    qualityLines,
    benchStopping,
    qualityRunId,
    lastRunQuality,
    lastRunSpeed,
    lastRunModel,
    lastRunTime,
  }
})
