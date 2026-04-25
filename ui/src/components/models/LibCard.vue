<script setup lang="ts">
import { computed } from 'vue'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'
import { useModelsStore } from '@/stores/models'

const props = defineProps<{
  modelId: string
  sizeGb: number
  quantization: string
  active: boolean
  cached: boolean
}>()

const emit = defineEmits<{
  load: []
  delete: []
  download: []
}>()

const modelsStore = useModelsStore()

const org = computed(() => props.modelId.split('/')[0] ?? '')
const shortName = computed(() => props.modelId.split('/').pop() ?? props.modelId)
const hfUrl = computed(() => `https://huggingface.co/${props.modelId}`)

const queueItem = computed(() =>
  modelsStore.downloadQueue.find(q => q.id === props.modelId)
)

const isDownloading = computed(() =>
  queueItem.value?.status === 'downloading' || queueItem.value?.status === 'queued'
)

const isLoading = computed(() => modelsStore.loadingModelId === props.modelId)

const quantLabel = computed(() => {
  const q = props.quantization
  return q === 'unknown' ? '—' : q
})
</script>

<template>
  <div class="lib-card" :class="{ 'is-active': active }">
    <div class="card-main">
      <div class="name-block">
        <a :href="hfUrl" target="_blank" rel="noopener" class="model-link" :title="modelId">
          <span class="org-prefix">{{ org }}/</span><span class="model-name">{{ shortName }}</span>
        </a>
        <AppBadge v-if="active" variant="success" size="sm">Serving</AppBadge>
      </div>
      <div class="meta-row">
        <span class="meta-chip">{{ quantLabel }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-chip">{{ sizeGb.toFixed(1) }} GB</span>
      </div>
    </div>

    <div class="card-actions">
      <template v-if="active">
        <AppButton variant="secondary" size="sm" :loading="isLoading" @click="emit('load')">↺ Reload</AppButton>
      </template>
      <template v-else-if="cached">
        <AppButton variant="primary" size="sm" :loading="isLoading" @click="emit('load')">Load</AppButton>
        <AppButton variant="ghost" size="sm" class="btn-delete" @click="emit('delete')">Delete</AppButton>
      </template>
      <template v-else>
        <div v-if="isDownloading" class="progress-wrap">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${queueItem?.progress ?? 0}%` }" />
          </div>
          <span class="progress-pct">{{ Math.round(queueItem?.progress ?? 0) }}%</span>
        </div>
        <AppButton v-else variant="secondary" size="sm" @click="emit('download')">↓ Download</AppButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.lib-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--bd-subtle);
  border-left: 3px solid transparent;
  transition: background var(--transition-fast), border-left-color var(--transition-fast);
}

.lib-card:last-child { border-bottom: none; }
.lib-card:hover { background: rgba(255, 255, 255, .018); }

.lib-card.is-active {
  background: var(--ac-bg);
  border-left-color: var(--si-500);
}

.card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.name-block {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.model-link {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-primary);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color var(--transition-fast);
  display: block;
  min-width: 0;
}

.model-link:hover { color: var(--si-300); }
.org-prefix { color: var(--tx-tertiary); font-weight: 400; }

.meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.meta-chip {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--tx-secondary);
  font-weight: 500;
}

.meta-sep {
  color: var(--tx-muted);
  font-size: 11px;
  margin: 0 1px;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.btn-delete:hover {
  color: var(--cr-300) !important;
  border-color: rgba(239, 68, 68, .30) !important;
  background: rgba(239, 68, 68, .06) !important;
}

.progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 120px;
}

.progress-track {
  flex: 1;
  height: 4px;
  background: var(--bg-elevated);
  border-radius: var(--r-pill);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--si-500);
  border-radius: var(--r-pill);
  transition: width .3s ease;
}

.progress-pct {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--tx-secondary);
  min-width: 32px;
  text-align: right;
}
</style>
