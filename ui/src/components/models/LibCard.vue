<!--
  LibCard — card representing a locally-cached model in the Models library view.

  Props:
  - modelId: HuggingFace repo ID (e.g. "mlx-community/Qwen3-8B-4bit")
  - sizeGb: disk size of the model in gigabytes
  - quantization: short quantization label (e.g. "4-bit", "8-bit")
  - active: true when this model is currently loaded in the inference server
  - cached: true when the model is already downloaded to local HF cache

  Emits (internal): routes to /serve to load the model via serverStore.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'
import { useModelsStore } from '@/stores/models'
import { useServerStore } from '@/stores/server'

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
const serverStore = useServerStore()
const router = useRouter()

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
const isRestarting = computed(() => modelsStore.serverRestartingFor === props.modelId)

const quantLabel = computed(() => {
  const q = props.quantization
  return q === 'unknown' ? '—' : q
})

const fitInfo = computed(() => {
  const avail = serverStore.memory?.available_gb
  if (!avail || !props.sizeGb) return null
  const ratio = props.sizeGb / avail
  if (ratio < 0.5)  return { label: 'Fits great', color: 'var(--ph-400)' }
  if (ratio < 0.75) return { label: 'Fits well',  color: 'var(--cu-300)' }
  if (ratio < 0.90) return { label: 'Tight fit',  color: 'var(--cu-500)' }
  return { label: 'Too large', color: 'var(--cr-400)' }
})

/** Best benchmark result for this model from history, for the inline badge. */
const bestBench = computed(() => modelsStore.bestBenchmarkPerModel.get(props.modelId) ?? null)
</script>

<template>
  <div class="lib-card" :class="{ 'is-active': active }">
    <!-- Column 1: Model name + quantization + badges -->
    <div class="card-col-model">
      <a :href="hfUrl" target="_blank" rel="noopener" class="model-link" :title="modelId">
        <span class="org-prefix">{{ org }}/</span><span class="model-name">{{ shortName }}</span>
      </a>
      <span class="meta-chip q-chip">{{ quantLabel }}</span>
      <AppBadge v-if="isRestarting" variant="warning" size="sm">Restarting…</AppBadge>
      <AppBadge v-else-if="active" variant="success" size="sm">Serving</AppBadge>
    </div>

    <!-- Column 2: Size · Fit + benchmark -->
    <div class="card-col-meta">
      <span class="meta-chip">{{ sizeGb.toFixed(1) }} GB</span>
      <template v-if="fitInfo && !active">
        <span class="meta-sep">·</span>
        <span class="fit-chip" :style="{ color: fitInfo.color }">● {{ fitInfo.label }}</span>
      </template>
      <template v-if="bestBench && cached">
        <span class="meta-sep">·</span>
        <button class="bench-badge" @click.stop="router.push('/benchmarks')" title="View in Benchmarks">
          {{ bestBench.avg_tps.toFixed(1) }} t/s
        </button>
      </template>
    </div>

    <!-- Column 3: Actions -->
    <div class="card-col-actions">
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
  display: grid;
  grid-template-columns: 2fr 1.5fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
  border-left: 3px solid transparent;
  transition: background var(--transition-fast), border-left-color var(--transition-fast);
  min-height: 48px;
}

.lib-card:last-child { border-bottom: none; }
.lib-card:hover { background: rgba(255, 255, 255, .018); }

.lib-card.is-active {
  background: var(--ac-bg);
  border-left-color: var(--si-500);
}

.card-col-model {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  overflow: hidden;
}

.card-col-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--tx-secondary);
  font-size: 13px;
  font-family: var(--font-mono);
  justify-content: flex-start;
}

.card-col-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  justify-content: flex-end;
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
  font-size: 14px;
  color: var(--tx-secondary);
  font-weight: 500;
}

.meta-sep {
  color: var(--tx-muted);
  font-size: 13px;
  margin: 0 1px;
}

.fit-chip {
  font-size: 13px;
  font-weight: 500;
}

.bench-badge {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--si-300);
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  border-radius: var(--r-pill);
  padding: 1px 7px;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.bench-badge:hover { background: rgba(91,106,208,.18); border-color: var(--si-400); }

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
  font-size: 13px;
  color: var(--tx-secondary);
  min-width: 32px;
  text-align: right;
}
</style>
