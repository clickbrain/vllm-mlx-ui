<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useModelsStore } from '@/stores/models'
import TabBar from '@/components/models/TabBar.vue'
import LibCard from '@/components/models/LibCard.vue'
import DownloadQueueCard from '@/components/models/DownloadQueueCard.vue'
import HFSearchResult from '@/components/models/HFSearchResult.vue'
import BenchmarkPanel from '@/components/models/BenchmarkPanel.vue'
import AppButton from '@/components/shared/AppButton.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'

const modelsStore = useModelsStore()

const tabs = ['Library', 'Find', 'Benchmark'] as const
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
  if (sortMode.value === 'name') return [...list].sort((a, b) => a.id.localeCompare(b.id))
  if (sortMode.value === 'size') return [...list].sort((a, b) => b.size_gb - a.size_gb)
  return list
})

// Find tab
const searchInput = ref('')
const mlxOnly = ref(true)

async function doSearch() {
  await modelsStore.searchHF(searchInput.value.trim(), mlxOnly.value)
}

function handleSearchKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') doSearch()
}

// LibCard action handlers
async function handleLoad(modelId: string) {
  try { await modelsStore.loadModel(modelId) }
  catch { /* actionError shown via store */ }
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

onMounted(() => { modelsStore.fetchModels() })
</script>

<template>
  <div class="models-view">
    <!-- Download queue — shown when downloads are active -->
    <DownloadQueueCard />

    <!-- Tab bar -->
    <div class="view-header">
      <TabBar
        :tabs="['Library', 'Find', 'Benchmark']"
        :model-value="activeTab"
        @update:model-value="v => activeTab = v as TabName"
      />
      <!-- Swarms tab reserved for Kilroy integration -->
    </div>

    <!-- Library tab -->
    <div v-if="activeTab === 'Library'" class="tab-content">
      <!-- Error bar -->
      <div v-if="modelsStore.actionError" class="error-banner">
        ⚠ {{ modelsStore.actionError }}
        <button class="error-dismiss" @click="modelsStore.actionError = null">✕</button>
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
          placeholder="Search HuggingFace… (empty = top downloads)"
          @keydown="handleSearchKeydown"
        />
        <div class="scope-toggle">
          <button
            class="scope-btn"
            :class="{ active: mlxOnly }"
            @click="mlxOnly = true"
          >MLX only</button>
          <button
            class="scope-btn"
            :class="{ active: !mlxOnly }"
            @click="mlxOnly = false"
          >All of HuggingFace</button>
        </div>
        <AppButton variant="primary" size="sm" :loading="modelsStore.searching" @click="doSearch">
          Search
        </AppButton>
      </div>

      <div v-if="modelsStore.actionError" class="error-banner">
        ⚠ {{ modelsStore.actionError }}
        <button class="error-dismiss" @click="modelsStore.actionError = null">✕</button>
      </div>

      <div v-if="modelsStore.searching" class="empty-state">
        <div class="spinner" />
        <span class="empty-label">Searching…</span>
      </div>
      <div v-else-if="modelsStore.searchResults.length > 0" class="results-list">
        <div class="results-header-row">
          <span class="col-model">Model</span>
          <span class="col-stats">Downloads / Likes</span>
          <span class="col-action" />
        </div>
        <HFSearchResult
          v-for="r in modelsStore.searchResults"
          :key="r.id"
          :id="r.id"
          :downloads="r.downloads"
          :likes="r.likes"
          :is_mlx="r.is_mlx"
          :tags="r.tags"
          @download="handleDownload(r.id)"
        />
      </div>
      <div v-else-if="modelsStore.searchQuery !== '' || modelsStore.searchResults.length === 0 && !modelsStore.actionError" class="empty-state">
        <span class="empty-label">{{ modelsStore.searchQuery ? 'No results found' : 'Click Search to browse top MLX models' }}</span>
      </div>
    </div>

    <!-- Benchmark tab -->
    <div v-else-if="activeTab === 'Benchmark'" class="tab-content">
      <BenchmarkPanel />
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
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-canvas);
  padding-bottom: var(--space-1);
  margin-bottom: calc(-1 * var(--space-1));
}

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

.col-stats {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  min-width: 140px;
  text-align: right;
}

.col-action { min-width: 80px; }

/* Library search + sort */
.lib-search-wrap {
  width: 180px;
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

/* Spinner */
@keyframes spin { to { transform: rotate(360deg); } }

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--bd-emphasis);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
</style>

