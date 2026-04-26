// SPDX-License-Identifier: Apache-2.0
/**
 * Benchmark favorites store — persists named benchmark runs to localStorage.
 *
 * A "favorite" captures the full results array plus the config used, so the
 * user can restore any past run by clicking it in the configure panel.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { BenchmarkResult, BenchmarkConfig } from '@/stores/models'

export interface SavedBenchmark {
  id: string
  name: string
  savedAt: string
  config: BenchmarkConfig
  results: BenchmarkResult[]
  models: string[]
}

const STORAGE_KEY = 'vllm-benchmark-favorites'

function load(): SavedBenchmark[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as SavedBenchmark[]) : []
  } catch {
    return []
  }
}

function persist(items: SavedBenchmark[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
}

export const useBenchmarkFavoritesStore = defineStore('benchmarkFavorites', () => {
  const favorites = ref<SavedBenchmark[]>(load())

  function save(results: BenchmarkResult[], config: BenchmarkConfig, name?: string) {
    const models = results.map(r => r.model_id)
    const autoName = name?.trim() ||
      models.map(m => (m.split('/').pop() ?? m)).join(', ')

    const entry: SavedBenchmark = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: autoName,
      savedAt: new Date().toISOString(),
      config: { ...config },
      results: results.map(r => ({ ...r })),
      models,
    }

    favorites.value = [entry, ...favorites.value]
    persist(favorites.value)
    return entry
  }

  function remove(id: string) {
    favorites.value = favorites.value.filter(f => f.id !== id)
    persist(favorites.value)
  }

  function rename(id: string, name: string) {
    const entry = favorites.value.find(f => f.id === id)
    if (entry) {
      entry.name = name.trim() || entry.name
      persist(favorites.value)
    }
  }

  return { favorites, save, remove, rename }
})
