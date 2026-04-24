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
  switch: []
  load: []
  delete: []
  download: []
}>()

const modelsStore = useModelsStore()

const shortName = computed(() => props.modelId.split('/').pop() ?? props.modelId)

const queueItem = computed(() =>
  modelsStore.downloadQueue.find(q => q.id === props.modelId)
)

const isDownloading = computed(() =>
  queueItem.value?.status === 'downloading' || queueItem.value?.status === 'queued'
)
</script>

<template>
  <div class="lib-card" :class="{ 'is-active': active }">
    <div class="card-left">
      <span class="model-name">{{ shortName }}</span>
      <div class="badge-row">
        <AppBadge variant="neutral" size="sm">{{ quantization }}</AppBadge>
        <AppBadge v-if="active" variant="success" size="sm">Serving</AppBadge>
      </div>
    </div>

    <div class="card-right">
      <span class="size-label">{{ sizeGb.toFixed(1) }} GB</span>
      <div class="actions">
        <template v-if="active">
          <AppButton variant="secondary" size="sm" @click="emit('switch')">Switch</AppButton>
        </template>
        <template v-else-if="cached">
          <AppButton variant="primary" size="sm" @click="emit('load')">Load</AppButton>
          <AppButton variant="ghost" size="sm" class="btn-delete" @click="emit('delete')">Delete</AppButton>
        </template>
        <template v-else>
          <div v-if="isDownloading" class="progress-wrap">
            <div class="progress-track">
              <div
                class="progress-fill"
                :style="{ width: `${queueItem?.progress ?? 0}%` }"
              />
            </div>
            <span class="progress-pct">{{ Math.round(queueItem?.progress ?? 0) }}%</span>
          </div>
          <AppButton v-else variant="primary" size="sm" @click="emit('download')">Download</AppButton>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lib-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  border-left: 2px solid transparent;
  transition:
    background var(--transition-fast),
    border-left-color var(--transition-fast);
}

.lib-card:last-child { border-bottom: none; }
.lib-card:hover { background: rgba(255, 255, 255, .012); }

.lib-card.is-active {
  background: var(--ac-bg);
  border-left-color: var(--si-500);
}

.card-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  flex: 1;
}

.model-name {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge-row {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}

.card-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}

.size-label {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--tx-muted);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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
  color: var(--tx-muted);
  min-width: 32px;
  text-align: right;
}
</style>
