<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
  HFSearchResult — one result card from a HuggingFace model search.

  Props:
  - id: HuggingFace model repo ID (e.g. "mlx-community/Qwen3-8B-4bit")
  - downloads: total HF download count (abbreviated to k/M notation)
  - likes: HF "like" count
  - is_mlx: true when the model has the mlx tag (shows MLX badge)
  - tags: array of HF topic tags
  - size_gb: pre-download weight file size in GB (optional)
  - fit_level: 'perfect' | 'good' | 'marginal' | 'too_tight' from check_model_fit
  - trending_score: HF trendingScore (float, higher = more trending)

  Emits: download — user clicked the Download button
-->
<script setup lang="ts">
import { computed } from 'vue'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'

const props = defineProps<{
  id: string
  downloads: number
  likes: number
  is_mlx: boolean
  tags: string[]
  size_gb?: number
  fit_level?: string
  trending_score?: number
}>()

const emit = defineEmits<{
  download: []
}>()

function abbreviate(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

const downloadsFormatted = computed(() => abbreviate(props.downloads))
const likesFormatted = computed(() => abbreviate(props.likes))
const trendingFormatted = computed(() =>
  props.trending_score ? props.trending_score.toFixed(1) : null
)

const sizeLabel = computed(() => {
  if (!props.size_gb) return null
  return `~${props.size_gb.toFixed(1)} GB`
})

const fitInfo = computed(() => {
  const map: Record<string, { dot: string; label: string; color: string }> = {
    perfect:   { dot: '●', label: 'Fits great', color: 'var(--ph-400)' },
    good:      { dot: '●', label: 'Fits well',  color: '#facc15' },
    marginal:  { dot: '●', label: 'Tight fit',  color: '#f97316' },
    too_tight: { dot: '●', label: 'Too large',  color: 'var(--cr-400)' },
  }
  return props.fit_level ? (map[props.fit_level] ?? null) : null
})
</script>

<template>
  <div class="hf-result">
    <div class="result-id">
      <span class="model-id">{{ id }}</span>
      <AppBadge v-if="is_mlx" variant="info" size="sm">MLX</AppBadge>
    </div>
    <!-- Size / Fit column — aligns with col-fit header -->
    <div class="result-fit">
      <span v-if="sizeLabel" class="size-label">{{ sizeLabel }}</span>
      <span v-if="fitInfo" class="fit-pill" :style="{ color: fitInfo.color }">
        {{ fitInfo.dot }} {{ fitInfo.label }}
      </span>
      <span v-else-if="sizeLabel" class="fit-unknown">—</span>
    </div>
    <!-- Individual stat columns — each is a direct flex child to align with header -->
    <span class="stat stat-downloads">↓ {{ downloadsFormatted }}</span>
    <span class="stat stat-likes">♥ {{ likesFormatted }}</span>
    <span class="stat stat-trending">{{ trendingFormatted ?? '—' }}</span>
    <AppButton variant="secondary" size="sm" @click="emit('download')">Download</AppButton>
  </div>
</template>

<style scoped>
.hf-result {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  transition: background var(--transition-fast);
}

.hf-result:last-child { border-bottom: none; }
.hf-result:hover { background: rgba(255, 255, 255, .012); }

.result-id {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}

.model-id {
  font-family: var(--font-mono);
  font-size: 14.5px;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Aligns with .col-fit header */
.result-fit {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  min-width: 90px;
  flex-shrink: 0;
}

.size-label {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-secondary);
}

.fit-pill {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.fit-unknown {
  font-size: 13px;
  color: var(--tx-muted);
}

.stat {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--tx-muted);
  flex-shrink: 0;
  min-width: 72px;
  text-align: right;
}
</style>

