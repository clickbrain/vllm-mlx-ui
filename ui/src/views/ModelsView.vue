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
// server-sort: downloads, likes, trending — re-fetches from HF
// client-sort: model (name), size — sorts displayedSearchResults locally
type SortCol = 'model' | 'size' | 'downloads' | 'likes' | 'trending'
type SortDir = 'asc' | 'desc'
const sortCol = ref<SortCol>('trending')
const sortDir = ref<SortDir>('desc')

// Client-side filters
const filterFit = ref<'all' | 'perfect' | 'good' | 'marginal' | 'too_tight'>('all')
const filterMaxSizeGb = ref<number>(0) // 0 = no limit
const filterMinDownloads = ref<number>(0)
const filterMinLikes = ref<number>(0)

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
  sortCol.value = 'downloads'
  sortDir.value = 'desc'
  modelsStore.searchHF(query, modelsStore.mlxOnly, 0, 'downloads')
}

const isRestarting = computed(() => modelsStore.serverRestartingFor)

// Server-side sort columns (require a new HF fetch)
const SERVER_SORT_COLS = new Set<SortCol>(['downloads', 'likes', 'trending'])

function toggleSort(col: SortCol) {
  if (sortCol.value === col) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortCol.value = col
    sortDir.value = 'desc'
  }
  if (SERVER_SORT_COLS.has(col)) {
    // Re-fetch with new server sort
    modelsStore.searchHF(searchInput.value.trim(), modelsStore.mlxOnly, 0, col)
  }
}

function sortArrow(col: SortCol) {
  if (sortCol.value !== col) return '↕'
  return sortDir.value === 'desc' ? '↓' : '↑'
}

const displayedSearchResults = computed(() => {
  let list = modelsStore.searchResults
  if (hideDownloaded.value) {
    const cachedIds = new Set(modelsStore.models.map(m => m.id))
    list = list.filter(r => !cachedIds.has(r.id))
  }
  // Fit filter
  if (filterFit.value !== 'all') {
    list = list.filter(r => r.fit_level === filterFit.value)
  }
  // Max size filter
  if (filterMaxSizeGb.value > 0) {
    list = list.filter(r => !r.size_gb || r.size_gb <= filterMaxSizeGb.value)
  }
  // Min downloads filter
  if (filterMinDownloads.value > 0) {
    list = list.filter(r => r.downloads >= filterMinDownloads.value)
  }
  // Min likes filter
  if (filterMinLikes.value > 0) {
    list = list.filter(r => r.likes >= filterMinLikes.value)
  }
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
  sortCol.value = 'downloads'
  sortDir.value = 'desc'
  await modelsStore.searchHF(searchInput.value.trim(), modelsStore.mlxOnly, 0, 'downloads')
}

async function loadMore() {
  const serverSort = SERVER_SORT_COLS.has(sortCol.value) ? sortCol.value : 'downloads'
  await modelsStore.searchHFMore(serverSort)
}

// Preload trending mlx-community models when Find tab is opened for the first time
let trendingLoaded = false
function onFindTabActivated() {
  if (!trendingLoaded && modelsStore.searchResults.length === 0) {
    trendingLoaded = true
    sortCol.value = 'trending'
    sortDir.value = 'desc'
    modelsStore.searchHF('', true, 0, 'trending')
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
  catch (err) { console.error('Delete failed', err) }
}

async function handleDownload(modelId: string) {
  try { await modelsStore.downloadModel(modelId) }
  catch (err) { console.error('Download failed', err) }
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
        <div class="filter-chips">
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'all' }"
            @click="libraryFilter = 'all'"
          >All</button>
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'active' }"
            @click="libraryFilter = 'active'"
          >Active</button>
        </div>
        <div class="lib-search-wrap">
          <input
            v-model="librarySearch"
            type="text"
            class="lib-search-input"
            placeholder="Filter…"
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
        <LibCard
          v-for="m in filteredModels"
          :key="m.id"
          :model-id="m.id"
          :size-gb="m.size_gb"
          :quantization="m.quantization"
          :active="m.active"
          :cached="m.cached"
          @load="handleLoad(m.id)"
          @delete="handleDelete(m.id)"
          @download="handleDownload(m.id)"
        />
      </div>
    </div>

    <!-- Find tab -->
    <div v-else-if="activeTab === 'Find'" class="tab-content">
      <!-- Company quick-search chips -->
      <div class="company-filter-row">
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
          placeholder="Search models… (empty = trending mlx-community)"
          @keydown.enter="doSearch"
        />
        <div class="scope-toggle">
          <button
            class="scope-btn"
            :class="{ active: modelsStore.mlxOnly }"
            @click="modelsStore.mlxOnly = true"
          >MLX only</button>
          <button
            class="scope-btn"
            :class="{ active: !modelsStore.mlxOnly }"
            @click="modelsStore.mlxOnly = false"
          >All of HuggingFace</button>
        </div>
        <AppButton variant="primary" size="sm" :loading="modelsStore.searching" @click="doSearch">
          Search
        </AppButton>
      </div>

      <!-- Options row: hide-downloaded + result filters -->
      <div class="find-options-row">
        <div class="filter-group">
          <span class="filter-label">Fit:</span>
          <button class="filter-btn" :class="{ active: filterFit === 'all' }" @click="filterFit = 'all'">All</button>
          <button class="filter-btn fit-perfect" :class="{ active: filterFit === 'perfect' }" @click="filterFit = 'perfect'">Fits great</button>
          <button class="filter-btn fit-good" :class="{ active: filterFit === 'good' }" @click="filterFit = 'good'">Fits well</button>
          <button class="filter-btn fit-marginal" :class="{ active: filterFit === 'marginal' }" @click="filterFit = 'marginal'">Tight</button>
          <button class="filter-btn fit-too-tight" :class="{ active: filterFit === 'too_tight' }" @click="filterFit = 'too_tight'">Too large</button>
        </div>
        <div class="filter-group">
          <span class="filter-label">Size:</span>
          <button class="filter-btn" :class="{ active: filterMaxSizeGb === 0 }" @click="filterMaxSizeGb = 0">All</button>
          <button class="filter-btn" :class="{ active: filterMaxSizeGb === 3 }" @click="filterMaxSizeGb = 3">&lt;3 GB</button>
          <button class="filter-btn" :class="{ active: filterMaxSizeGb === 8 }" @click="filterMaxSizeGb = 8">&lt;8 GB</button>
          <button class="filter-btn" :class="{ active: filterMaxSizeGb === 20 }" @click="filterMaxSizeGb = 20">&lt;20 GB</button>
        </div>
        <div class="filter-group">
          <span class="filter-label">Min downloads:</span>
          <button class="filter-btn" :class="{ active: filterMinDownloads === 0 }" @click="filterMinDownloads = 0">All</button>
          <button class="filter-btn" :class="{ active: filterMinDownloads === 1000 }" @click="filterMinDownloads = 1000">1k+</button>
          <button class="filter-btn" :class="{ active: filterMinDownloads === 10000 }" @click="filterMinDownloads = 10000">10k+</button>
          <button class="filter-btn" :class="{ active: filterMinDownloads === 100000 }" @click="filterMinDownloads = 100000">100k+</button>
        </div>
        <div class="filter-group">
          <span class="filter-label">Min likes:</span>
          <button class="filter-btn" :class="{ active: filterMinLikes === 0 }" @click="filterMinLikes = 0">All</button>
          <button class="filter-btn" :class="{ active: filterMinLikes === 10 }" @click="filterMinLikes = 10">10+</button>
          <button class="filter-btn" :class="{ active: filterMinLikes === 100 }" @click="filterMinLikes = 100">100+</button>
          <button class="filter-btn" :class="{ active: filterMinLikes === 1000 }" @click="filterMinLikes = 1000">1k+</button>
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
          <button class="col-downloads col-sortable" :class="{ 'col-active': sortCol === 'downloads' }" @click="toggleSort('downloads')">
            Downloads <span class="sort-arrow">{{ sortArrow('downloads') }}</span>
          </button>
          <button class="col-likes col-sortable" :class="{ 'col-active': sortCol === 'likes' }" @click="toggleSort('likes')">
            Likes <span class="sort-arrow">{{ sortArrow('likes') }}</span>
          </button>
          <button class="col-trending col-sortable" :class="{ 'col-active': sortCol === 'trending' }" @click="toggleSort('trending')">
            Trending <span class="sort-arrow">{{ sortArrow('trending') }}</span>
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
          :trending_score="r.trending_score"
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
.col-sortable:hover { color: var(--tx-secondary); background: var(--bg-2); }
.col-sortable.col-active { color: var(--si-300); }

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
  background: var(--bg-2);
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
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
  background: var(--bg-2);
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
</style>

