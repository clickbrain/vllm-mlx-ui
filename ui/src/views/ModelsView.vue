<!--
  ModelsView — HuggingFace model library and local cache management.

  Three tabs:
  - Library: cached/downloaded models with load and delete actions
  - Search: HuggingFace search for MLX models with fit-check and download
  - Downloading: active download queue (visible when downloads are in progress)

  Fit levels (🟢🟡🟠🔴) reflect unified memory availability on the active machine,
  helping users choose models before downloading.
-->
<script setup lang="ts">
import { ref, computed, onMounted, onActivated, watch, defineOptions } from 'vue'

defineOptions({ name: 'ModelsView' })
import { useModelsStore } from '@/stores/models'
import { useServerStore } from '@/stores/server'
import { useRouter } from 'vue-router'
import { RecycleScroller } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import TabBar from '@/components/models/TabBar.vue'
import LibCard from '@/components/models/LibCard.vue'
import DownloadQueueCard from '@/components/models/DownloadQueueCard.vue'
import HFSearchResult from '@/components/models/HFSearchResult.vue'
import AppButton from '@/components/shared/AppButton.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { usePreferences } from '@/composables/usePreferences'
import { findBestChoices, type ModelBadge } from '@/composables/useModelScoring'

const modelsStore = useModelsStore()
const serverStore = useServerStore()
const router = useRouter()

const { selectedUseCase, maxAgeMonths } = usePreferences()

const tabs = ['Library', 'Find'] as const
type TabName = typeof tabs[number]
const activeTab = ref<TabName>('Library')

const confirmModal = ref<{ modelId: string; message: string } | null>(null)

// Library filter + sort + text search
const libraryFilter = ref<'all' | 'active'>('all')
const librarySearch = ref('')
const sortMode = ref<'name' | 'size'>('name')

const filteredModels = computed(() => {
  let list = modelsStore.models
  if (libraryFilter.value === 'active') list = list.filter(m => m.active)
  if (librarySearch.value.trim()) {
    const q = librarySearch.value.toLowerCase()
    list = list.filter(m => m.id.toLowerCase().includes(q))
  }
  // Pin active model to top
  return [...list].sort((a, b) => {
    if (a.active && !b.active) return -1
    if (!a.active && b.active) return 1
    if (sortMode.value === 'size') return b.size_gb - a.size_gb
    return a.id.localeCompare(b.id)
  })
})

// Find tab
const searchInput = ref('')
const hideDownloaded = ref(true)
const showFilters = ref(false)

// Client-side filters pending signal — set when filters need a deeper server re-fetch
// (client-side filter changes apply instantly via computed; this only gates the
// "Apply Filters" button which fetches a larger pool)
const filtersPending = ref(false)

function markFiltersDirty() {
  filtersPending.value = true
}

async function applyFilters() {
  const serverSort = SERVER_SORT_COLS.has(sortCol.value) ? sortCol.value : 'last_modified'
  await modelsStore.searchHF(searchInput.value.trim(), true, 0, serverSort, false, 100, sortDir.value)
  filtersPending.value = false
}

// Column sort state: column key + direction
// server-sort: downloads, likes, last_modified — re-fetches from HF
// client-sort: model (name), size — sorts displayedSearchResults locally
type SortCol = 'model' | 'size' | 'downloads' | 'likes' | 'last_modified'
type SortDir = 'asc' | 'desc'
const sortCol = ref<SortCol>('last_modified')
const sortDir = ref<SortDir>('desc')

// Client-side filters
const filterFitLevels = ref<Set<string>>(new Set())  // empty set = all fit levels
const filterSizeMin = ref<number>(0)
const filterSizeMax = ref<number>(200)  // reasonable max for Apple Silicon
const filterDownloadsMin = ref<number>(0)
const filterDownloadsMax = ref<number>(100_000_000)
const filterFitOnly = ref(false)  // quick checkbox: only "perfect" and "good"

// Quick-search by company/org
const COMPANY_FILTERS = [
  { label: 'Meta', query: 'meta-llama' },
  { label: 'Qwen', query: 'Qwen' },
  { label: 'Google', query: 'google' },
  { label: 'Microsoft', query: 'microsoft' },
  { label: 'Mistral', query: 'mistralai' },
  { label: 'Apple', query: 'apple' },
  { label: 'DeepSeek', query: 'deepseek-ai' },
  { label: 'MLX Community', query: 'mlx-community' },
] as const

function searchCompany(query: string) {
  searchInput.value = query
  sortCol.value = 'last_modified'
  sortDir.value = 'desc'
  modelsStore.searchHF(query, true, 0, 'last_modified', false, 50, 'desc').then(() => {
    modelsStore.fetchModelScores(modelsStore.searchResults.map(r => r.id))
  })
}

const isRestarting = computed(() => modelsStore.serverRestartingFor)

// Server-side sort columns (require a new HF fetch)
const SERVER_SORT_COLS = new Set<SortCol>(['downloads', 'likes', 'last_modified'])

function toggleSortDir() {
  sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  if (SERVER_SORT_COLS.has(sortCol.value as SortCol)) {
    modelsStore.searchHF(searchInput.value.trim(), true, 0, sortCol.value as string, false, 50, sortDir.value)
  }
}

function onSortChange() {
  sortDir.value = 'desc'
  if (SERVER_SORT_COLS.has(sortCol.value as SortCol)) {
    modelsStore.searchHF(searchInput.value.trim(), true, 0, sortCol.value as string, false, 50, sortDir.value)
  }
}

// Fit level filter helpers
function toggleFitLevel(level: string) {
  const current = filterFitLevels.value
  if (current.has(level)) {
    current.delete(level)
  } else {
    current.add(level)
  }
  filterFitLevels.value = new Set(current)
  markFiltersDirty()
}

function hasFitLevel(level: string): boolean {
  return filterFitLevels.value.has(level)
}

const displayedSearchResults = computed(() => {
  let list = modelsStore.searchResults

  // Filter out non-MLX models (always enforce MLX)
  list = list.filter(r => r.is_mlx)

  if (hideDownloaded.value) {
    const cachedIds = new Set(modelsStore.models.map(m => m.id))
    list = list.filter(r => !cachedIds.has(r.id))
  }

  // Fit filter with multi-select or quick-fit
  if (filterFitOnly.value) {
    // Quick filter: only perfect and good
    list = list.filter(r => r.fit_level === 'perfect' || r.fit_level === 'good')
  } else if (filterFitLevels.value.size > 0) {
    // Multi-select: OR logic
    list = list.filter(r => filterFitLevels.value.has(r.fit_level ?? ''))
  }

  // Size range filter
  list = list.filter(r => {
    if (!r.size_gb) return true  // show models with unknown size
    return r.size_gb >= filterSizeMin.value && r.size_gb <= filterSizeMax.value
  })

  // Downloads range filter
  list = list.filter(r => r.downloads >= filterDownloadsMin.value && r.downloads <= filterDownloadsMax.value)

  // Client-side sort (model name or size)
  if (sortCol.value === 'model') {
    const dir = sortDir.value === 'asc' ? 1 : -1
    list = [...list].sort((a, b) => dir * a.id.localeCompare(b.id))
  } else if (sortCol.value === 'size') {
    const dir = sortDir.value === 'asc' ? 1 : -1
    list = [...list].sort((a, b) => dir * ((a.size_gb ?? 0) - (b.size_gb ?? 0)))
  }
  return list
})

const preFilterCount = computed(() => modelsStore.searchResults.filter(r => r.is_mlx).length)

/**
 * Multi-signal Best Choice badges: one winner per use case.
 * Returns Map<modelId, ModelBadge[]> — each badge is a distinct use-case win.
 */
const bestChoices = computed((): Map<string, ModelBadge[]> => {
  if (modelsStore.searching) return new Map()
  const totalRam = serverStore.memory?.total_gb ?? 0
  return findBestChoices(
    displayedSearchResults.value,
    modelsStore.modelScores,
    totalRam,
    maxAgeMonths.value,
    selectedUseCase.value,
  )
})

async function doSearch() {
  sortCol.value = 'last_modified'
  sortDir.value = 'desc'
  filtersPending.value = false
  await modelsStore.searchHF(searchInput.value.trim(), true, 0, 'last_modified', false, 50, 'desc')
  modelsStore.fetchModelScores(modelsStore.searchResults.map(r => r.id))
}

async function loadMore() {
  const serverSort = SERVER_SORT_COLS.has(sortCol.value) ? sortCol.value : 'last_modified'
  await modelsStore.searchHFMore(serverSort, sortDir.value)
  modelsStore.fetchModelScores(modelsStore.searchResults.map(r => r.id))
}

// Preload newest mlx-community models when Find tab is opened for the first time
const trendingLoaded = ref(false)
function onFindTabActivated() {
  if (!trendingLoaded.value && modelsStore.searchResults.length === 0) {
    trendingLoaded.value = true
    sortCol.value = 'last_modified'
    sortDir.value = 'desc'
    modelsStore.searchHF('', true, 0, 'last_modified', false, 50, 'desc').then(() => {
      modelsStore.fetchModelScores(modelsStore.searchResults.map(r => r.id))
    })
  }
}

// Load toast state
const loadToast = ref<string | null>(null)
const loadError = ref<string | null>(null)

// Show crash log as error when it appears after a model switch
watch(() => serverStore.crashLog, (log) => {
  if (log) loadError.value = `Server crashed: ${log}`
})

// LibCard action handlers
async function handleLoad(modelId: string) {
  const modelName = modelId.split('/').pop() ?? modelId
  loadToast.value = `Switching to ${modelName}…`
  try {
    const result = await modelsStore.loadModel(modelId)
    if (!result?.restarted) {
      loadToast.value = 'Model loaded'
      setTimeout(() => { loadToast.value = null }, 3000)
    }
    // If restarted, serverRestartingFor handles the polling; clear toast when done
    if (result?.restarted) {
      const poll = setInterval(() => {
        if (!modelsStore.serverRestartingFor) {
          clearInterval(poll)
          loadToast.value = 'Model loaded'
          // Check for crash after restart
          if (serverStore.crashLog) loadError.value = `Server crashed: ${serverStore.crashLog}`
          setTimeout(() => { loadToast.value = null }, 3000)
        }
      }, 500)
    }
  } catch (err) {
    loadToast.value = null
    modelsStore.actionError = String(err)
  }
}

async function handleDelete(modelId: string) {
  confirmModal.value = {
    modelId,
    message: `Remove ${modelId.split('/').pop()} from local cache? This cannot be undone.`
  }
}

async function doDelete() {
  if (!confirmModal.value) return
  const modelId = confirmModal.value.modelId
  confirmModal.value = null
  try { await modelsStore.deleteModel(modelId) }
  catch (err) { modelsStore.actionError = `Failed to delete ${modelId}: ${String(err)}` }
}

async function handleDownload(modelId: string) {
  try { await modelsStore.downloadModel(modelId) }
  catch (err) { modelsStore.actionError = `Failed to download ${modelId}: ${String(err)}` }
}

onMounted(() => {
  modelsStore.actionError = null
  modelsStore.fetchModels()
  modelsStore.resumeActiveDownloadPolls()
})

// When navigating back to this tab (KeepAlive), refresh model list and
// re-attach any download polls that may have been interrupted.
onActivated(() => {
  modelsStore.fetchModels()
  modelsStore.resumeActiveDownloadPolls()
})

watch(activeTab, (tab) => {
  if (tab === 'Find') onFindTabActivated()
})
</script>

<template>
  <div class="models-view">
    <!-- Download queue — shown when downloads are active -->
    <DownloadQueueCard />

    <!-- Tab bar — sticky so it stays visible when scrolling -->
    <div class="view-header">
      <TabBar
        :tabs="['Library', 'Find']"
        :model-value="activeTab"
        @update:model-value="v => activeTab = v as TabName"
      />
      <button class="bench-link" @click="router.push('/benchmarks')">
        <svg viewBox="0 0 20 20" fill="currentColor" width="12" height="12" aria-hidden="true" style="flex-shrink:0">
          <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
        </svg>
        Benchmarks →
      </button>
    </div>

    <!-- Library tab -->
    <div v-if="activeTab === 'Library'" class="tab-content">
      <!-- Error bar -->
      <div v-if="modelsStore.actionError" class="error-banner">
        ⚠ {{ modelsStore.actionError }}
        <button class="error-dismiss" @click="modelsStore.actionError = null">✕</button>
      </div>

      <!-- Crash log error -->
      <div v-if="loadError" class="error-banner">
        ⚠ {{ loadError }}
        <button class="error-dismiss" @click="loadError = null">✕</button>
      </div>

      <!-- Restarting banner -->
      <div v-if="isRestarting" class="restart-banner">
        <div class="restart-spinner" />
        ⟳ Switching model — server restarting, please wait…
      </div>

      <!-- Load toast -->
      <div v-if="loadToast" class="toast-banner">
        {{ loadToast }}
      </div>

      <div class="library-toolbar">
        <div class="filter-chips" role="group" aria-label="Filter models">
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'all' }"
            :aria-pressed="libraryFilter === 'all'"
            @click="libraryFilter = 'all'"
          >All</button>
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'active' }"
            :aria-pressed="libraryFilter === 'active'"
            @click="libraryFilter = 'active'"
          >Active</button>
        </div>
        <div class="lib-search-wrap">
          <input
            v-model="librarySearch"
            type="text"
            class="lib-search-input"
            placeholder="Filter…"
            aria-label="Filter models by name"
          />
        </div>
        <div class="toolbar-spacer" />
        <div class="sort-group">
          <button class="sort-btn" :class="{ active: sortMode === 'name' }" @click="sortMode = 'name'">Name</button>
          <button class="sort-btn" :class="{ active: sortMode === 'size' }" @click="sortMode = 'size'">Size</button>
        </div>
      </div>

      <div v-if="modelsStore.loading" class="empty-state">
        <div class="spinner" />
        <span class="empty-label">Loading models…</span>
      </div>
      <div v-else-if="filteredModels.length === 0" class="empty-state-card">
        <p class="empty-title">No models downloaded yet</p>
        <p class="empty-desc">Use the Find tab to discover and download MLX models from HuggingFace.</p>
        <AppButton variant="secondary" size="sm" @click="activeTab = 'Find'">
          Go to Find
        </AppButton>
      </div>
      <div v-else class="model-list">
        <!-- Column headers -->
        <div class="lib-col-header">
          <span class="lib-hdr-model">Model</span>
          <span class="lib-hdr-fit">Size · Fit <span class="lib-hdr-note">(based on available RAM)</span></span>
          <span class="lib-hdr-actions">Actions</span>
        </div>
        <div class="virtual-scroller-wrapper">
          <RecycleScroller
            :items="filteredModels"
            :item-size="80"
            key-field="id"
            class="virtual-scroller"
            v-slot="{ item }"
          >
            <LibCard
              :model-id="item.id"
              :size-gb="item.size_gb"
              :quantization="item.quantization"
              :active="item.active"
              :cached="item.cached"
              @load="handleLoad(item.id)"
              @delete="handleDelete(item.id)"
              @download="handleDownload(item.id)"
            />
          </RecycleScroller>
        </div>
      </div>
    </div>

    <!-- Find tab -->
    <div v-else-if="activeTab === 'Find'" class="tab-content">

      <!-- Search bar -->
      <div class="find-search-row">
        <div class="search-input-wrapper">
          <svg class="search-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="8" cy="8" r="7" />
            <path d="M15 15l5 5" />
          </svg>
          <input
            v-model="searchInput"
            type="text"
            class="search-input"
            placeholder="Search all of HuggingFace… (e.g. 'Qwen 7B', 'mistral', 'deepseek')"
            aria-label="Search HuggingFace models"
            @keydown.enter="doSearch"
          />
          <AppButton variant="primary" size="sm" :loading="modelsStore.searching" @click="doSearch">
            Search
          </AppButton>
        </div>
        <p class="search-hint">
          Searches MLX-compatible models across all of HuggingFace
        </p>
      </div>

      <!-- Company quick-search chips -->
      <div class="company-filter-row" role="group" aria-label="Browse models by company">
        <span class="company-row-label">Browse:</span>
        <button
          v-for="c in COMPANY_FILTERS"
          :key="c.query"
          class="company-chip"
          :class="{ active: searchInput === c.query }"
          @click="searchCompany(c.query)"
        >{{ c.label }}</button>
      </div>

      <!-- Use-case selector bar (always visible) -->
      <div class="use-case-bar" role="group" aria-label="Filter Best Choice by use case">
        <span class="use-case-bar-label">Best for:</span>
        <button
          v-for="uc in (['chat', 'code', 'reasoning', 'vision'] as const)"
          :key="uc"
          class="use-case-pill"
          :class="[`uc-${uc}`, { active: selectedUseCase === uc }]"
          :aria-pressed="selectedUseCase === uc"
          @click="selectedUseCase = selectedUseCase === uc ? null : uc"
        >
          {{ { chat: '💬 Chat', code: '💻 Code', reasoning: '🧠 Reasoning', vision: '🖼️ Vision' }[uc] }}
        </button>
        <button
          v-if="selectedUseCase"
          class="use-case-clear"
          aria-label="Clear use case filter"
          @click="selectedUseCase = null"
        >✕ All</button>
        <div class="uc-spacer" />
        <label class="uc-age-label" title="Hide models older than this">
          <span class="uc-age-text">Max age:</span>
          <select v-model="maxAgeMonths" class="uc-age-select">
            <option :value="0">Any age</option>
            <option :value="6">6 months</option>
            <option :value="12">12 months</option>
            <option :value="18">18 months (default)</option>
            <option :value="24">24 months</option>
            <option :value="36">3 years</option>
          </select>
        </label>
      </div>

      <!-- Collapsible filters + sort toolbar -->
      <div class="find-toolbar">
        <button class="filter-toggle" @click="showFilters = !showFilters">
          <svg :class="['filter-chevron', { open: showFilters }]" viewBox="0 0 12 12" width="12" height="12" fill="currentColor">
            <path d="M4 2l4 4-4 4" />
          </svg>
          Filters
        </button>
        <div class="toolbar-spacer" />
        <div class="sort-select-group">
          <span class="sort-label">Sort:</span>
          <select v-model="sortCol" class="sort-select" @change="onSortChange">
            <option value="last_modified">Last Modified</option>
            <option value="downloads">Downloads</option>
            <option value="likes">Likes</option>
            <option value="model">Name</option>
            <option value="size">Size</option>
          </select>
          <button class="sort-dir-btn" @click="toggleSortDir" :title="sortDir === 'desc' ? 'Descending' : 'Ascending'">
            {{ sortDir === 'desc' ? '↓' : '↑' }}
          </button>
        </div>
        <label class="hide-downloaded-toggle">
          <input type="checkbox" v-model="hideDownloaded" />
          <span>Hide downloaded</span>
        </label>
      </div>

      <!-- Expanded filter panel -->
      <div v-if="showFilters" class="filter-panel">
        <div class="filter-row">
          <span class="filter-label">Fit:</span>
          <label class="filter-chip-check">
            <input type="checkbox" :checked="hasFitLevel('perfect')" @change="toggleFitLevel('perfect')" />
            <span class="chip-dot perfect">●</span> Perfect
          </label>
          <label class="filter-chip-check">
            <input type="checkbox" :checked="hasFitLevel('good')" @change="toggleFitLevel('good')" />
            <span class="chip-dot good">●</span> Good
          </label>
          <label class="filter-chip-check">
            <input type="checkbox" :checked="hasFitLevel('marginal')" @change="toggleFitLevel('marginal')" />
            <span class="chip-dot marginal">●</span> Tight
          </label>
          <label class="filter-chip-check">
            <input type="checkbox" :checked="hasFitLevel('too_tight')" @change="toggleFitLevel('too_tight')" />
            <span class="chip-dot too-tight">●</span> Too large
          </label>
          <label class="filter-chip-check">
            <input type="checkbox" v-model="filterFitOnly" @change="markFiltersDirty" />
            <span>Only those that fit</span>
          </label>
        </div>
        <div class="filter-row">
          <span class="filter-label">Size:</span>
          <div class="range-inputs">
            <input type="number" v-model.number="filterSizeMin" min="0" max="200" class="range-input" placeholder="min" @change="markFiltersDirty" />
            <span class="range-dash">–</span>
            <input type="number" v-model.number="filterSizeMax" min="0" max="200" class="range-input" placeholder="max" @change="markFiltersDirty" />
            <span class="range-unit">GB</span>
          </div>
        </div>
        <div class="filter-row">
          <span class="filter-label">Downloads:</span>
          <div class="range-inputs">
            <input type="number" v-model.number="filterDownloadsMin" min="0" class="range-input" placeholder="min" @input="filtersPending = true" />
            <span class="range-dash">–</span>
            <input type="number" v-model.number="filterDownloadsMax" min="0" class="range-input" placeholder="max" @input="filtersPending = true" />
          </div>
        </div>
        <div class="filter-apply-row">
          <AppButton variant="primary" size="sm" :disabled="!filtersPending" :loading="modelsStore.searching" @click="applyFilters">
            Apply Filters
          </AppButton>
        </div>
      </div>

      <!-- Filter summary -->
      <div v-if="preFilterCount > 0" class="filter-summary">
        <span v-if="displayedSearchResults.length === preFilterCount">
          {{ preFilterCount }} model{{ preFilterCount === 1 ? '' : 's' }} loaded
          <span v-if="modelsStore.searchHasMore"> · more available</span>
        </span>
        <span v-else>
          Showing {{ displayedSearchResults.length }} of {{ preFilterCount }} loaded models matching filters
          <span v-if="modelsStore.searchHasMore"> · <button class="link-btn" @click="loadMore">load more to find additional matches</button></span>
        </span>
      </div>

      <!-- Error -->
      <div v-if="modelsStore.actionError" class="error-banner">
        ⚠ {{ modelsStore.actionError }}
        <button class="error-dismiss" @click="modelsStore.actionError = null">✕</button>
      </div>

      <!-- Loading -->
      <div v-if="modelsStore.searching && !modelsStore.searchResults.length" class="empty-state">
        <div class="spinner" />
        <span class="empty-label">Searching HuggingFace…</span>
      </div>

      <!-- Results -->
      <div v-else-if="displayedSearchResults.length > 0" class="find-results">
        <HFSearchResult
          v-for="r in displayedSearchResults"
          :key="r.id"
          :id="r.id"
          :downloads="r.downloads"
          :likes="r.likes"
          :is_mlx="r.is_mlx"
          :tags="r.tags"
          :size_gb="r.size_gb"
          :fit_level="r.fit_level"
          :last_modified="r.last_modified"
          :total_ram_gb="serverStore.memory?.total_gb ?? 0"
          :available_ram_gb="serverStore.memory?.available_gb ?? 0"
          :badges="bestChoices.get(r.id) ?? []"
          @download="handleDownload(r.id)"
        />
        <div v-if="modelsStore.searchHasMore" class="load-more-row">
          <AppButton variant="ghost" size="sm" :loading="modelsStore.searching" @click="loadMore">
            Load more…
          </AppButton>
        </div>
        <!-- Hint when filters cut results significantly -->
        <div v-if="modelsStore.searchHasMore && displayedSearchResults.length < 5" class="filter-hint">
          ↑ Filters are hiding many results. <button class="link-btn" @click="loadMore">Load more</button> to find additional matches, or widen your filters.
        </div>
      </div>

      <!-- Empty: not yet searched -->
      <div v-else-if="!trendingLoaded && !modelsStore.searching && !modelsStore.actionError" class="empty-state">
        <span class="empty-label">Search above or browse by provider to discover models</span>
      </div>

      <!-- Empty: searched but no results or all filtered out -->
      <div v-else-if="!modelsStore.searching && !modelsStore.actionError" class="empty-state">
        <span v-if="preFilterCount > 0" class="empty-label">No models match the current filters — adjust filters or <button class="link-btn" @click="loadMore">load more</button></span>
        <span v-else class="empty-label">No models found — try a different search or provider</span>
      </div>
    </div>

    <ConfirmModal
      v-if="confirmModal"
      title="Remove Model"
      :message="confirmModal.message"
      confirm-label="Remove"
      :destructive="true"
      @confirm="doDelete"
      @cancel="confirmModal = null"
    />
  </div>
</template>

<style scoped>
.models-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-canvas);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--bd-subtle);
  margin-bottom: var(--space-1);
}

.bench-link {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 14px;
  color: var(--tx-muted);
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  padding: 4px 8px;
  border-radius: var(--r-md);
  transition: color var(--transition-fast), background var(--transition-fast);
  white-space: nowrap;
}
.bench-link:hover { color: var(--tx-secondary); background: var(--bg-elevated); }

.tab-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* Library toolbar */
.library-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.filter-chips {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}

.filter-chip {
  padding: 4px 12px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  color: var(--tx-tertiary);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.filter-chip:hover:not(.active) {
  border-color: var(--bd-emphasis);
  color: var(--tx-secondary);
}
.filter-chip:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}
.filter-chip.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}

.sort-btn {
  padding: 4px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  font-size: 14px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
}

.sort-btn:hover {
  color: var(--tx-secondary);
  border-color: var(--bd-default);
}
.sort-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}

/* Model list */
.model-list {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

/* Empty states */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-10) var(--space-6);
}

.empty-label {
  font-size: var(--text-sm);
  color: var(--tx-tertiary);
}

.empty-state-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-8) var(--space-6);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
  max-width: 480px;
  align-self: center;
  width: 100%;
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-primary);
}

.empty-desc {
  font-size: var(--text-sm);
  color: var(--tx-tertiary);
  line-height: 1.5;
}

/* ── Find tab ─────────────────────────────────────────────── */

/* Search bar */
.find-search-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.search-input-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-lg);
  background: var(--bg-input);
  flex: 1;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.search-input-wrapper:focus-within {
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}
.search-icon {
  width: 18px;
  height: 18px;
  color: var(--tx-muted);
  flex-shrink: 0;
}
.search-input-wrapper .search-input {
  border: none;
  padding: 0;
  background: transparent;
  color: var(--tx-primary);
  font-size: var(--text-base);
  flex: 1;
  outline: none;
}
.search-input::placeholder { color: var(--tx-tertiary); }
.search-hint {
  font-size: 12px;
  color: var(--tx-tertiary);
  margin: 0;
  padding: 0 var(--space-1);
}

/* Company chips */
.company-filter-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.company-filter-row::-webkit-scrollbar { display: none; }
.company-row-label {
  font-size: 12px;
  color: var(--tx-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .06em;
  flex-shrink: 0;
}
.company-chip {
  padding: 3px 11px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-pill);
  color: var(--tx-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
}
.company-chip:hover:not(.active) {
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}
.company-chip.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}
.company-chip:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}

/* Toolbar: filter toggle + sort + hide downloaded */
.find-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.filter-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--tx-secondary);
  font-size: 13px;
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--r-md);
  transition: background var(--transition-fast), color var(--transition-fast);
}
.filter-toggle:hover { background: var(--bg-elevated); color: var(--tx-primary); }
.filter-toggle:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}
.filter-chevron {
  transition: transform var(--transition-fast);
}
.filter-chevron.open {
  transform: rotate(90deg);
}
.sort-select-group {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.sort-label {
  font-size: 12px;
  color: var(--tx-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
}
.sort-select {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-sm);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 2px 24px 2px 8px;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7280'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 6px center;
  cursor: pointer;
}
.sort-select:focus {
  outline: none;
  border-color: var(--bd-focus);
}
.sort-dir-btn {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-sm);
  color: var(--tx-secondary);
  font-size: 14px;
  padding: 2px 8px;
  cursor: pointer;
  font-family: inherit;
  line-height: 1;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.sort-dir-btn:hover { border-color: var(--bd-emphasis); }
.sort-dir-btn:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}

.hide-downloaded-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
  color: var(--tx-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.hide-downloaded-toggle input { accent-color: var(--si-500); cursor: pointer; }

/* Expanded filter panel */
.filter-panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.filter-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.filter-label {
  font-size: 12px;
  color: var(--tx-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  min-width: 72px;
  flex-shrink: 0;
}
.filter-chip-check {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 13px;
  color: var(--tx-secondary);
  cursor: pointer;
  user-select: none;
}
.filter-chip-check input { accent-color: var(--si-500); cursor: pointer; }
.chip-dot { font-size: 12px; }
.chip-dot.perfect   { color: var(--ph-400); }
.chip-dot.good      { color: var(--cu-300); }
.chip-dot.marginal  { color: var(--cu-500); }
.chip-dot.too-tight { color: var(--cr-400); }

.range-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.range-input {
  width: 70px;
  padding: 3px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-sm);
  color: var(--tx-primary);
  font-size: 13px;
  font-family: var(--font-mono);
  transition: border-color var(--transition-fast);
}
.range-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 2px rgba(91, 106, 208, .12);
}
.range-dash { color: var(--tx-muted); font-size: 13px; }
.range-unit { font-size: 12px; color: var(--tx-tertiary); }

.filter-apply-row {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--space-1);
  border-top: 1px solid var(--bd-subtle);
}
.filter-summary {
  font-size: 12px;
  color: var(--tx-tertiary);
  text-align: center;
  padding: var(--space-1) 0;
}

.filter-hint {
  font-size: 12px;
  color: var(--tx-secondary);
  text-align: center;
  padding: var(--space-2);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
  border: 1px solid var(--bd-subtle);
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  font-size: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.link-btn:hover { opacity: 0.8; }

/* Results list */
.find-results {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* Load more row */
.load-more-row {
  display: flex;
  justify-content: center;
  padding: var(--space-3) 0;
}

/* Library column header row */
.lib-col-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-5);
  border-bottom: 1px solid var(--bd-default);
  background: var(--bg-elevated);
}

.lib-hdr-model {
  flex: 1;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.lib-hdr-fit {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 120px;
  text-align: right;
}

.lib-hdr-note {
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--tx-muted);
  opacity: 0.6;
}

.lib-hdr-actions {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 100px;
  text-align: right;
}

/* Library search + sort */
.lib-search-wrap {
  width: 140px;
  flex: none;
}

.lib-search-input {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  padding: 5px 10px;
  transition: border-color var(--transition-fast);
}

.lib-search-input::placeholder { color: var(--tx-muted); }
.lib-search-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.toolbar-spacer { flex: 1; }

.sort-group {
  display: flex;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  overflow: hidden;
  flex-shrink: 0;
}

.sort-btn {
  padding: 4px 10px;
  background: transparent;
  border: none;
  color: var(--tx-muted);
  font-size: 14px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.sort-btn:first-child { border-right: 1px solid var(--bd-default); }
.sort-btn:not(:first-child):not(:last-child) { border-right: 1px solid var(--bd-default); }
.sort-btn:hover:not(.active) { background: var(--bg-elevated); color: var(--tx-secondary); }
.sort-btn.active { background: var(--ac-bg); color: var(--si-300); font-weight: 600; }

/* Error banner */
.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--cr-300);
}

.error-dismiss {
  background: none;
  border: none;
  color: var(--cr-300);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  opacity: 0.7;
}
.error-dismiss:hover { opacity: 1; }

/* Restart banner */
.restart-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: rgba(245, 158, 11, .08);
  border: 1px solid rgba(245, 158, 11, .25);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--cu-400, #fbbf24);
}

@keyframes spin { to { transform: rotate(360deg); } }
.restart-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(245, 158, 11, .3);
  border-top-color: #f59e0b;
  border-radius: 50%;
  animation: spin .6s linear infinite;
  flex-shrink: 0;
}

/* Toast banner */
.toast-banner {
  padding: var(--space-2) var(--space-4);
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--si-300);
}

/* Spinner */
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--bd-emphasis);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin .6s linear infinite;
}

/* Virtual scroller wrapper fills remaining space */
.virtual-scroller-wrapper {
  flex: 1 1 0;
  min-height: 200px;
  overflow: hidden;
}

.virtual-scroller {
  height: 100%;
  overflow-y: auto;
}

/* ── Use-case selector bar ──────────────────────────────────── */
.use-case-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: var(--space-2) 0;
}
.use-case-bar-label {
  font-size: 12px;
  color: var(--tx-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .06em;
  flex-shrink: 0;
}
.use-case-pill {
  padding: 4px 12px;
  border-radius: var(--r-pill);
  border: 1px solid var(--bd-subtle);
  background: var(--bg-elevated);
  color: var(--tx-secondary);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
}
.use-case-pill:hover:not(.active) {
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}
.use-case-pill.uc-chat.active {
  background: var(--badge-chat-bg);
  border-color: var(--badge-chat);
  color: var(--badge-chat);
  font-weight: 600;
}
.use-case-pill.uc-code.active {
  background: var(--badge-code-bg);
  border-color: var(--badge-code);
  color: var(--badge-code);
  font-weight: 600;
}
.use-case-pill.uc-reasoning.active {
  background: var(--badge-reasoning-bg);
  border-color: var(--badge-reasoning);
  color: var(--badge-reasoning);
  font-weight: 600;
}
.use-case-pill.uc-vision.active {
  background: var(--badge-vision-bg);
  border-color: var(--badge-vision);
  color: var(--badge-vision);
  font-weight: 600;
}
.use-case-pill:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}
.use-case-clear {
  padding: 4px 10px;
  border-radius: var(--r-pill);
  border: 1px solid var(--bd-subtle);
  background: transparent;
  color: var(--tx-tertiary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
}
.use-case-clear:hover { color: var(--tx-secondary); border-color: var(--bd-emphasis); }
.uc-spacer { flex: 1; }
.uc-age-label {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.uc-age-text {
  font-size: 12px;
  color: var(--tx-tertiary);
  white-space: nowrap;
}
.uc-age-select {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-md);
  color: var(--tx-secondary);
  font-size: 12px;
  font-family: inherit;
  padding: 2px 6px;
  cursor: pointer;
  outline: none;
}
.uc-age-select:focus-visible { outline: 2px solid var(--si-500); outline-offset: 2px; }

</style>

