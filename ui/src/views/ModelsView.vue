<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useModelsStore } from '@/stores/models'
import TabBar from '@/components/models/TabBar.vue'
import LibCard from '@/components/models/LibCard.vue'
import DownloadQueueCard from '@/components/models/DownloadQueueCard.vue'
import HFSearchResult from '@/components/models/HFSearchResult.vue'
import BenchmarkPanel from '@/components/models/BenchmarkPanel.vue'
import AppButton from '@/components/shared/AppButton.vue'

const modelsStore = useModelsStore()

const tabs = ['Library', 'Find', 'Benchmark'] as const
type TabName = typeof tabs[number]
const activeTab = ref<TabName>('Library')

// Library filter + sort
const libraryFilter = ref<'all' | 'cached' | 'active'>('all')
const sortMode = ref<'name' | 'size' | 'recent'>('name')
const sortModes = ['name', 'size', 'recent'] as const

function cycleSort() {
  const idx = sortModes.indexOf(sortMode.value)
  sortMode.value = sortModes[(idx + 1) % sortModes.length]
}

const sortLabel = computed(() =>
  ({ name: 'Name ↕', size: 'Size ↕', recent: 'Recent ↕' }[sortMode.value])
)

const filteredModels = computed(() => {
  let list = modelsStore.models
  if (libraryFilter.value === 'cached') list = list.filter(m => m.cached)
  if (libraryFilter.value === 'active') list = list.filter(m => m.active)
  if (sortMode.value === 'name') return [...list].sort((a, b) => a.id.localeCompare(b.id))
  if (sortMode.value === 'size') return [...list].sort((a, b) => b.size_gb - a.size_gb)
  return list
})

// Find tab
const searchInput = ref('')
const mlxOnly = ref(true)

async function doSearch() {
  const q = searchInput.value.trim()
  if (!q) return
  const query = mlxOnly.value ? `${q} mlx` : q
  await modelsStore.searchHF(query)
}

function handleSearchKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') doSearch()
}

// LibCard action handlers
async function handleLoad(modelId: string) {
  try { await modelsStore.loadModel(modelId) }
  catch (err) { console.error('Load failed', err) }
}

async function handleDelete(modelId: string) {
  if (!confirm(`Delete ${modelId}?`)) return
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
      <div class="library-toolbar">
        <div class="filter-chips">
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'all' }"
            @click="libraryFilter = 'all'"
          >All</button>
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'cached' }"
            @click="libraryFilter = 'cached'"
          >Cached</button>
          <button
            class="filter-chip"
            :class="{ active: libraryFilter === 'active' }"
            @click="libraryFilter = 'active'"
          >Active</button>
        </div>
        <button class="sort-btn" @click="cycleSort">{{ sortLabel }}</button>
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
          @switch="handleLoad(m.id)"
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
          placeholder="Search HuggingFace…"
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
          :key="r.modelId"
          :model-id="r.modelId"
          :downloads="r.downloads"
          :likes="r.likes"
          :is-mlx="r.isMlx"
          :tags="r.tags"
          @download="handleDownload(r.modelId)"
        />
      </div>
      <div v-else-if="modelsStore.searchQuery !== ''" class="empty-state">
        <span class="empty-label">No results found</span>
      </div>
      <div v-else class="empty-state">
        <span class="empty-label">Search for a model to get started</span>
      </div>
    </div>

    <!-- Benchmark tab -->
    <div v-else-if="activeTab === 'Benchmark'" class="tab-content">
      <BenchmarkPanel />
    </div>
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
  justify-content: space-between;
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

