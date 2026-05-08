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
  last_modified?: string
  total_ram_gb?: number
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

const dateFormatted = computed(() => {
  if (!props.last_modified) return null
  try {
    const date = new Date(props.last_modified)
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return null
  }
})

const shortName = computed(() => {
  const parts = props.id.split('/')
  return parts.length > 1 ? parts.slice(1).join('/') : props.id
})

const orgName = computed(() => {
  const parts = props.id.split('/')
  return parts.length > 1 ? parts[0] : null
})

const sizeLabel = computed(() => {
  if (!props.size_gb) return null
  return `${props.size_gb.toFixed(1)} GB`
})

const fitInfo = computed(() => {
  const map: Record<string, { label: string; color: string; barColor: string }> = {
    perfect:   { label: 'Fits great', color: 'var(--ph-400)', barColor: 'var(--ph-400)' },
    good:      { label: 'Fits well',  color: 'var(--cu-300)', barColor: 'var(--cu-300)' },
    marginal:  { label: 'Tight fit',  color: 'var(--cu-500)', barColor: 'var(--cu-500)' },
    too_tight: { label: 'Too large',  color: 'var(--cr-400)', barColor: 'var(--cr-400)' },
  }
  return props.fit_level ? (map[props.fit_level] ?? null) : null
})

const fitPercent = computed(() => {
  if (!props.size_gb || !props.total_ram_gb || props.total_ram_gb <= 0) return 0
  return Math.min(props.size_gb / props.total_ram_gb, 1)
})
</script>

<template>
  <div class="hf-result">
    <div class="result-body">
      <!-- Top row: model name + MLX badge + download button -->
      <div class="result-top">
        <div class="result-id-group">
          <span v-if="orgName" class="result-org">{{ orgName }}/</span>
          <span class="result-name">{{ shortName }}</span>
          <AppBadge v-if="is_mlx" variant="info" size="sm">MLX</AppBadge>
        </div>
        <AppButton variant="secondary" size="sm" @click="emit('download')">Download</AppButton>
      </div>

      <!-- Fit gauge: model size vs RAM bar -->
      <div v-if="sizeLabel && fitInfo" class="fit-gauge-row">
        <div class="fit-gauge-track">
          <div
            class="fit-gauge-fill"
            :style="{ width: `${fitPercent * 100}%`, background: fitInfo.barColor }"
          />
        </div>
        <div class="fit-gauge-labels">
          <span class="fit-size">{{ sizeLabel }}</span>
          <span class="fit-pct">{{ Math.round(fitPercent * 100) }}% of {{ total_ram_gb?.toFixed(0) }} GB</span>
          <span class="fit-tag" :style="{ color: fitInfo.color }">{{ fitInfo.label }}</span>
        </div>
      </div>
      <div v-else-if="sizeLabel" class="fit-gauge-row">
        <div class="fit-gauge-track">
          <div class="fit-gauge-fill fit-gauge-unknown" style="width: 30%" />
        </div>
        <div class="fit-gauge-labels">
          <span class="fit-size">{{ sizeLabel }}</span>
          <span class="fit-tag fit-unknown">Unknown fit</span>
        </div>
      </div>

      <!-- Metadata row: downloads, likes, date -->
      <div class="result-meta">
        <span class="meta-stat">
          <svg class="meta-icon" viewBox="0 0 16 16" fill="currentColor" width="12" height="12"><path d="M8 1a6 6 0 100 12A6 6 0 008 1zM7 4h2v5H7V4zm0 6h2v2H7v-2z"/></svg>
          {{ downloadsFormatted }} downloads
        </span>
        <span class="meta-stat">
          <svg class="meta-icon" viewBox="0 0 16 16" fill="currentColor" width="12" height="12"><path d="M8 1.5l1.76 3.57 3.94.57-2.85 2.78.67 3.93L8 10.46l-3.52 1.85.67-3.93L2.3 5.64l3.94-.57L8 1.5z"/></svg>
          {{ likesFormatted }}
        </span>
        <span v-if="dateFormatted" class="meta-stat">{{ dateFormatted }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hf-result {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.hf-result:hover {
  border-color: var(--bd-emphasis);
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}

.result-body {
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* Top row */
.result-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.result-id-group {
  display: flex;
  align-items: baseline;
  gap: 2px;
  min-width: 0;
  overflow: hidden;
}
.result-org {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-tertiary);
  white-space: nowrap;
}
.result-name {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 600;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Fit gauge */
.fit-gauge-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.fit-gauge-track {
  flex: 1;
  height: 6px;
  background: var(--bd-subtle);
  border-radius: 3px;
  overflow: hidden;
  max-width: 160px;
}
.fit-gauge-fill {
  height: 100%;
  border-radius: 3px;
  transition: width .2s ease;
}
.fit-gauge-unknown {
  background: var(--tx-tertiary);
  opacity: 0.4;
}
.fit-gauge-labels {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 12px;
  white-space: nowrap;
}
.fit-size {
  font-family: var(--font-mono);
  color: var(--tx-primary);
  font-weight: 600;
}
.fit-pct {
  color: var(--tx-tertiary);
  font-family: var(--font-mono);
}
.fit-tag {
  font-weight: 600;
}
.fit-unknown {
  color: var(--tx-tertiary);
}

/* Meta row */
.result-meta {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.meta-stat {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--tx-tertiary);
  font-family: var(--font-mono);
}
.meta-icon {
  opacity: 0.6;
}
</style>
