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
import { ref, computed, onMounted, watch } from 'vue'
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
const hideDownloaded = ref(false)

// Column sort state: column key + direction
// server-sort: downloads, likes, trending — re-fetches from HF
// client-sort: model (name), size — sorts displayedSearchResults locally
type SortCol = 'model' | 'size' | 'downloads' | 'likes' | 'trending'
type SortDir = 'asc' | 'desc'
const sortCol = ref<SortCol>('trending')
const sortDir = ref<SortDir>('desc')

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

      <!-- Options row: hide-downloaded toggle -->
      <div class="find-options-row">
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
  font-size: 12px;
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
  font-size: 12px;
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
  font-size: 12px;
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

.find-options-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
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
  font-size: 12px;
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.col-fit {
  font-size: 11px;
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
  font-size: 11px;
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
  font-size: 10px;
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.lib-hdr-fit {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 120px;
  text-align: right;
}

.lib-hdr-note {
  font-size: 10px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--tx-muted);
  opacity: 0.6;
}

.lib-hdr-actions {
  font-size: 11px;
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
  font-size: 12px;
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
  font-size: 14px;
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
  font-size: 12px;
  color: var(--tx-secondary);
  cursor: pointer;
  user-select: none;
}
.hide-downloaded-toggle input { accent-color: var(--si-500); cursor: pointer; }

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

