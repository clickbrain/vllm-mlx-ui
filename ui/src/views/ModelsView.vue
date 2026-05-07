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
import { ref, computed, onMounted, onActivated, watch } from 'vue'
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

const modelsStore = useModelsStore()
const serverStore = useServerStore()
const router = useRouter()

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
const filterDownloadsMax = ref<number>(1000000)
const filterLikesMin = ref<number>(0)
const filterLikesMax = ref<number>(10000)
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
  modelsStore.searchHF(query, true, 0, 'last_modified')
}

const isRestarting = computed(() => modelsStore.serverRestartingFor)

// Server-side sort columns (require a new HF fetch)
const SERVER_SORT_COLS = new Set<SortCol>(['downloads', 'likes', 'last_modified'])

function toggleSort(col: SortCol) {
  if (sortCol.value === col) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortCol.value = col
    sortDir.value = 'desc'
  }
  if (SERVER_SORT_COLS.has(col)) {
    // Re-fetch with new server sort
    modelsStore.searchHF(searchInput.value.trim(), true, 0, col)
  }
}

function sortArrow(col: SortCol) {
  if (sortCol.value !== col) return '↕'
  return sortDir.value === 'desc' ? '↓' : '↑'
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

  // Likes range filter
  list = list.filter(r => r.likes >= filterLikesMin.value && r.likes <= filterLikesMax.value)

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

async function doSearch() {
  sortCol.value = 'last_modified'
  sortDir.value = 'desc'
  await modelsStore.searchHF(searchInput.value.trim(), true, 0, 'last_modified')
}

async function loadMore() {
  const serverSort = SERVER_SORT_COLS.has(sortCol.value) ? sortCol.value : 'last_modified'
  await modelsStore.searchHFMore(serverSort)
}

// Preload newest mlx-community models when Find tab is opened for the first time
const trendingLoaded = ref(false)
function onFindTabActivated() {
  if (!trendingLoaded.value && modelsStore.searchResults.length === 0) {
    trendingLoaded.value = true
    sortCol.value = 'last_modified'
    sortDir.value = 'desc'
    modelsStore.searchHF('', true, 0, 'last_modified')
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
      <!-- Company quick-search chips -->
      <div class="company-filter-row" role="group" aria-label="Browse models by company">
        <span class="company-row-label">Browse by:</span>
        <button
          v-for="c in COMPANY_FILTERS"
          :key="c.query"
          class="company-chip"
          :class="{ active: searchInput === c.query }"
          @click="searchCompany(c.query)"
        >{{ c.label }}</button>
      </div>

      <div class="find-search-row">
        <input
          v-model="searchInput"
          type="text"
          class="search-input"
          placeholder="Search models… (empty = newest MLX models)"
          aria-label="Search HuggingFace models"
          @keydown.enter="doSearch"
        />
        <AppButton variant="primary" size="sm" :loading="modelsStore.searching" @click="doSearch">
          Search
        </AppButton>
      </div>
      
      <div class="mlx-note">
        ✓ Search results show only MLX-compatible models
      </div>

       <!-- Options row: filters and hide-downloaded -->
      <div class="find-options-row">
        <!-- Fit filter with quick checkbox -->
        <div class="filter-group">
          <span class="filter-label">Fit level:</span>
          <label class="fit-quick-toggle">
            <input type="checkbox" v-model="filterFitOnly" />
            <span>Only models that fit</span>
          </label>
          <div v-if="!filterFitOnly" class="fit-checkboxes">
            <label class="filter-checkbox">
              <input type="checkbox" :checked="hasFitLevel('perfect')" @change="toggleFitLevel('perfect')" />
              <span>🟢 Fits great (&lt;50%)</span>
            </label>
            <label class="filter-checkbox">
              <input type="checkbox" :checked="hasFitLevel('good')" @change="toggleFitLevel('good')" />
              <span>🟡 Fits well (50-75%)</span>
            </label>
            <label class="filter-checkbox">
              <input type="checkbox" :checked="hasFitLevel('marginal')" @change="toggleFitLevel('marginal')" />
              <span>🟠 Tight fit (75-90%)</span>
            </label>
            <label class="filter-checkbox">
              <input type="checkbox" :checked="hasFitLevel('too_tight')" @change="toggleFitLevel('too_tight')" />
              <span>🔴 Too large (&gt;90%)</span>
            </label>
          </div>
        </div>

        <!-- Size range filter -->
        <div class="filter-group">
          <span class="filter-label">Size (GB):</span>
          <div class="range-inputs">
            <input type="number" v-model.number="filterSizeMin" min="0" max="200" class="range-input" placeholder="min" />
            <span class="range-dash">–</span>
            <input type="number" v-model.number="filterSizeMax" min="0" max="200" class="range-input" placeholder="max" />
          </div>
          <input type="range" v-model.number="filterSizeMin" min="0" max="200" class="range-slider" />
          <input type="range" v-model.number="filterSizeMax" min="0" max="200" class="range-slider" />
        </div>

        <!-- Downloads range filter -->
        <div class="filter-group">
          <span class="filter-label">Downloads:</span>
          <div class="range-inputs">
            <input type="number" v-model.number="filterDownloadsMin" min="0" max="1000000" class="range-input range-input-small" placeholder="min" />
            <span class="range-dash">–</span>
            <input type="number" v-model.number="filterDownloadsMax" min="0" max="1000000" class="range-input range-input-small" placeholder="max" />
          </div>
        </div>

        <!-- Likes range filter -->
        <div class="filter-group">
          <span class="filter-label">Likes:</span>
          <div class="range-inputs">
            <input type="number" v-model.number="filterLikesMin" min="0" max="10000" class="range-input range-input-small" placeholder="min" />
            <span class="range-dash">–</span>
            <input type="number" v-model.number="filterLikesMax" min="0" max="10000" class="range-input range-input-small" placeholder="max" />
          </div>
        </div>

        <div class="toolbar-spacer" />
        <label class="hide-downloaded-toggle">
          <input type="checkbox" v-model="hideDownloaded" />
          <span>Hide downloaded</span>
        </label>
      </div>

      <div v-if="modelsStore.actionError" class="error-banner">
        ⚠ {{ modelsStore.actionError }}
        <button class="error-dismiss" @click="modelsStore.actionError = null">✕</button>
      </div>

      <div v-if="modelsStore.searching && !modelsStore.searchResults.length" class="empty-state">
        <div class="spinner" />
        <span class="empty-label">Loading trending models…</span>
      </div>
      <div v-else-if="displayedSearchResults.length > 0" class="results-list">
        <!-- Sortable column headers -->
        <div class="results-header-row">
          <button class="col-model col-sortable" :class="{ 'col-active': sortCol === 'model' }" @click="toggleSort('model')">
            Model <span class="sort-arrow">{{ sortArrow('model') }}</span>
          </button>
          <button class="col-fit col-sortable" :class="{ 'col-active': sortCol === 'size' }" @click="toggleSort('size')">
            Fit / Size <span class="sort-arrow">{{ sortArrow('size') }}</span>
          </button>
          <button class="col-date col-sortable" :class="{ 'col-active': sortCol === 'last_modified' }" @click="toggleSort('last_modified')">
            Last Modified <span class="sort-arrow">{{ sortArrow('last_modified') }}</span>
          </button>
          <button class="col-downloads col-sortable" :class="{ 'col-active': sortCol === 'downloads' }" @click="toggleSort('downloads')">
            Downloads <span class="sort-arrow">{{ sortArrow('downloads') }}</span>
          </button>
          <button class="col-likes col-sortable" :class="{ 'col-active': sortCol === 'likes' }" @click="toggleSort('likes')">
            Likes <span class="sort-arrow">{{ sortArrow('likes') }}</span>
          </button>
          <span class="col-action" />
        </div>
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
          @download="handleDownload(r.id)"
        />
        <div v-if="modelsStore.searchHasMore" class="load-more-row">
          <AppButton variant="ghost" size="sm" :loading="modelsStore.searching" @click="loadMore">
            Load more…
          </AppButton>
        </div>
      </div>
      <div v-else-if="!modelsStore.searching && !modelsStore.actionError" class="empty-state">
        <span class="empty-label">No results found</span>
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

/* Find tab */
.find-search-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.search-input {
  flex: 1;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  padding: 7px 12px;
  transition: border-color var(--transition-fast);
}

.search-input::placeholder { color: var(--tx-muted); }

.search-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.scope-toggle {
  display: flex;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  overflow: hidden;
  flex-shrink: 0;
}

.scope-btn {
  padding: 6px 12px;
  background: transparent;
  border: none;
  color: var(--tx-tertiary);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
}

.scope-btn:first-child { border-right: 1px solid var(--bd-default); }

.scope-btn:hover:not(.active) {
  background: var(--bg-elevated);
  color: var(--tx-secondary);
}

.scope-btn.active {
  background: var(--ac-bg);
  color: var(--si-300);
  font-weight: 500;
}

.results-list {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.results-header-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-default);
  background: var(--bg-elevated);
}

.col-model {
  flex: 1;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.col-fit {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 90px;
  text-align: right;
}

.col-downloads,
.col-likes,
.col-trending {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 72px;
  text-align: right;
  flex-shrink: 0;
}

/* Sortable header buttons */
.col-sortable {
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  padding: 2px 4px;
  border-radius: var(--r-sm);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color var(--transition-fast), background var(--transition-fast);
  user-select: none;
}
.col-sortable:hover { color: var(--tx-secondary); background: var(--bg-elevated); }
.col-sortable.col-active { color: var(--si-300); }
.col-sortable:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 1px;
}

.sort-arrow {
  font-size: 12px;
  opacity: 0.7;
}
.col-sortable.col-active .sort-arrow { opacity: 1; }

.col-action { min-width: 80px; }

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

/* Hide-downloaded toggle */
.hide-downloaded-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 14px;
  color: var(--tx-secondary);
  cursor: pointer;
  user-select: none;
}
.hide-downloaded-toggle input { accent-color: var(--si-500); cursor: pointer; }

/* Company quick-search chip row */
.company-filter-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.company-row-label {
  font-size: 13px;
  color: var(--tx-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  font-weight: 600;
  flex-shrink: 0;
  margin-right: var(--space-1);
}

.company-chip {
  padding: 3px 10px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  color: var(--tx-secondary);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
}

.company-chip:hover:not(.active) {
  background: var(--bg-elevated);
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}
.company-chip:focus-visible {
  outline: 2px solid var(--si-500);
  outline-offset: 2px;
}
.company-chip.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}

/* Filter row */
.find-options-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.filter-label {
  font-size: 13px;
  color: var(--tx-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  margin-right: 2px;
  white-space: nowrap;
}

.filter-btn {
  padding: 2px 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
  white-space: nowrap;
}

.filter-btn:hover:not(.active) {
  background: var(--bg-elevated);
  color: var(--tx-secondary);
  border-color: var(--bd-default);
}

.filter-btn.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}

.filter-btn.fit-perfect.active  { background: rgba(74,222,128,.1); border-color: rgba(74,222,128,.3); color: var(--ph-400); }
.filter-btn.fit-good.active     { background: rgba(250,204,21,.1); border-color: rgba(250,204,21,.3); color: #facc15; }
.filter-btn.fit-marginal.active { background: rgba(249,115,22,.1); border-color: rgba(249,115,22,.3); color: #f97316; }
.filter-btn.fit-too-tight.active{ background: rgba(239,68,68,.1);  border-color: rgba(239,68,68,.3);  color: var(--cr-400); }

/* Fix col header button padding so widths match data cells */
.col-downloads.col-sortable,
.col-likes.col-sortable,
.col-trending.col-sortable {
  padding: 0 2px;
  justify-content: flex-end;
}

/* Load more row */
.load-more-row {
  display: flex;
  justify-content: center;
  padding: var(--space-3);
  border-top: 1px solid var(--bd-subtle);
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

/* MLX note */
.mlx-note {
  font-size: 13px;
  color: var(--tx-muted);
  padding: 0 var(--space-2);
}

/* Fit quick toggle */
.fit-quick-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  font-size: 14px;
  color: var(--tx-secondary);
  user-select: none;
}

.fit-quick-toggle input {
  cursor: pointer;
}

/* Fit level checkboxes */
.fit-checkboxes {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.filter-checkbox {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  font-size: 13px;
  color: var(--tx-secondary);
  user-select: none;
}

.filter-checkbox input {
  cursor: pointer;
}

/* Range slider inputs */
.range-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: var(--space-1) 0;
}

.range-input {
  width: 70px;
  padding: 4px 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-primary);
  font-size: 13px;
  font-family: var(--font-mono);
  transition: border-color var(--transition-fast);
}

.range-input-small {
  width: 60px;
}

.range-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 2px rgba(91, 106, 208, .12);
}

.range-dash {
  color: var(--tx-muted);
  font-size: 13px;
}

.range-slider {
  width: 100%;
  height: 4px;
  margin: var(--space-1) 0;
  border-radius: 2px;
  background: var(--bd-default);
  -webkit-appearance: none;
  appearance: none;
  cursor: pointer;
}

.range-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--si-500);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.range-slider::-webkit-slider-thumb:hover {
  background: var(--si-400);
}

.range-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--si-500);
  cursor: pointer;
  border: none;
  transition: background var(--transition-fast);
}

.range-slider::-moz-range-thumb:hover {
  background: var(--si-400);
}

/* Date column */
.col-date {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 100px;
  text-align: right;
  flex-shrink: 0;
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

</style>

