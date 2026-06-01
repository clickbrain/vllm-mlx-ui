<!--
  LibCard — rich card representing a locally-cached model in the Models library view.

  Surfaces a concise model overview: identity, memory fit, architecture,
  benchmark highlights, quality scores, and actions.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'
import { useModelsStore, type BenchmarkScores, type FamilyData } from '@/stores/models'
import { useServerStore } from '@/stores/server'

const props = defineProps<{
  modelId: string
  sizeGb: number
  quantization: string
  active: boolean
  cached: boolean
  familyData?: FamilyData | null
}>()

const emit = defineEmits<{
  load: []
  delete: []
  download: []
}>()

const modelsStore = useModelsStore()
const serverStore = useServerStore()
const router = useRouter()

const FAMILY_PATTERNS: Array<[RegExp, string]> = [
  [/mixtral/i, 'Mixtral'],
  [/mistral/i, 'Mistral'],
  [/llama/i, 'Llama'],
  [/qwen/i, 'Qwen'],
  [/gemma/i, 'Gemma'],
  [/deepseek/i, 'DeepSeek'],
  [/phi/i, 'Phi'],
  [/granite/i, 'Granite'],
  [/exaone/i, 'EXAONE'],
  [/ministral/i, 'Ministral'],
  [/smollm/i, 'SmolLM'],
  [/command[- ]?r/i, 'Command R'],
  [/glm/i, 'GLM'],
  [/yi/i, 'Yi'],
]

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function deriveFamilyLabel(value: string): string {
  for (const [pattern, label] of FAMILY_PATTERNS) {
    if (pattern.test(value)) return label
  }
  return titleCase(value.split(/[\s/-]+/)[0] || 'Model')
}

function formatQuantization(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (!normalized || normalized === 'unknown') return 'Unknown'
  if (/bf16|bfloat16/.test(normalized)) return 'BF16'
  if (/fp16|float16/.test(normalized)) return 'FP16'
  const bits = normalized.match(/(?:q|^)(\d)|([2468])-?bit/)
  const bit = bits?.[1] ?? bits?.[2]
  if (bit) return `Q${bit}`
  return value.toUpperCase()
}

function formatParamCount(value: number | null | undefined): string | null {
  if (value == null || value <= 0) return null
  if (value >= 1) return `${value.toFixed(value >= 10 ? 0 : 1).replace(/\.0$/, '')}B params`
  return `${Math.round(value * 1000)}M params`
}

function formatScore(value: number): string {
  return `${Math.round(value)}%`
}

const shortName = computed(() => props.modelId.split('/').pop() ?? props.modelId)
const hfUrl = computed(() => `https://huggingface.co/${props.modelId}`)
const queueItem = computed(() => modelsStore.downloadQueue.find(q => q.id === props.modelId))
const isDownloading = computed(() => queueItem.value?.status === 'downloading' || queueItem.value?.status === 'queued')
const isLoading = computed(() => modelsStore.loadingModelId === props.modelId)
const isRestarting = computed(() => modelsStore.serverRestartingFor === props.modelId)
const isMtplx = computed(() => props.modelId.toLowerCase().includes('mtplx'))
const quantLabel = computed(() => formatQuantization(props.quantization))

const familyLabel = computed(() => {
  const seed = props.familyData?.family_name || props.familyData?.arch_type || shortName.value
  return deriveFamilyLabel(seed)
})

const architectureLabel = computed(() => {
  if (props.familyData?.arch_type) return titleCase(props.familyData.arch_type)
  return familyLabel.value
})

const paramCountLabel = computed(() => {
  const fromFamily = formatParamCount(props.familyData?.param_count_b)
  if (fromFamily) return fromFamily
  const match = props.modelId.match(/(?:^|[\/_.-])(\d+(?:\.\d+)?)B(?:[\/_.-]|$)/i)
  if (!match) return null
  return `${match[1]}B params`
})

const sizeLabel = computed(() => `${props.sizeGb.toFixed(1)} GB`)

const fitInfo = computed(() => {
  const availableGb = serverStore.memory?.available_gb
  if (!availableGb || !props.sizeGb) {
    return {
      label: 'Unknown fit',
      detail: 'Waiting for memory data',
      tone: 'muted',
    }
  }

  const ratio = props.sizeGb / availableGb
  if (ratio < 0.5) {
    return { label: 'Fits great', detail: `${availableGb.toFixed(1)} GB free now`, tone: 'good' }
  }
  if (ratio < 0.75) {
    return { label: 'Fits well', detail: `${availableGb.toFixed(1)} GB free now`, tone: 'good' }
  }
  if (ratio < 0.9) {
    return { label: 'Tight fit', detail: `${availableGb.toFixed(1)} GB free now`, tone: 'warn' }
  }
  return { label: 'Likely too large', detail: `${availableGb.toFixed(1)} GB free now`, tone: 'danger' }
})

const modelScores = computed<BenchmarkScores | null>(() => modelsStore.modelScores[props.modelId] ?? null)
const qualityPills = computed(() => {
  const familyScores = props.familyData?.scores ?? {}
  const scores = modelScores.value ?? { source: 'none' }
  return [
    { label: 'MMLU', value: familyScores.mmlu ?? scores.mmlu },
    { label: 'HumanEval', value: familyScores.humaneval ?? scores.humaneval },
    { label: 'MATH', value: familyScores.math ?? scores.math },
    { label: 'IFEval', value: familyScores.ifeval ?? scores.ifeval },
  ].filter((item): item is { label: string; value: number } => item.value != null)
})

const benchmarksForModel = computed(() =>
  modelsStore.benchmarkHistory.filter(entry => entry.model_id === props.modelId)
)

const bestSpeedBenchmark = computed(() => {
  let best = null as typeof benchmarksForModel.value[number] | null
  for (const entry of benchmarksForModel.value) {
    if (entry.avg_tps <= 0) continue
    if (!best || entry.avg_tps > best.avg_tps) best = entry
  }
  return best
})

const bestQualityBenchmark = computed(() => {
  let best = null as typeof benchmarksForModel.value[number] | null
  for (const entry of benchmarksForModel.value) {
    if (entry.overall_score == null) continue
    if (!best || (entry.overall_score ?? 0) > (best.overall_score ?? 0)) best = entry
  }
  return best
})

const hasBenchmarks = computed(() => Boolean(bestSpeedBenchmark.value || bestQualityBenchmark.value))
const bestSpeedLabel = computed(() => bestSpeedBenchmark.value ? `${bestSpeedBenchmark.value.avg_tps.toFixed(1)} t/s` : '—')
const bestSpeedDetail = computed(() => {
  if (!bestSpeedBenchmark.value?.avg_ttft_ms) return 'Best recorded run'
  return `TTFT ${Math.round(bestSpeedBenchmark.value.avg_ttft_ms)} ms`
})
const qualityBenchmarkLabel = computed(() => {
  if (bestQualityBenchmark.value?.overall_score == null) return '—'
  return `${Math.round(bestQualityBenchmark.value.overall_score * 100)}%`
})
const qualityBenchmarkDetail = computed(() => {
  const suites = Object.keys(bestQualityBenchmark.value?.suites ?? {})
  if (!suites.length) return 'Quality benchmark'
  return `${suites.length} suite${suites.length === 1 ? '' : 's'}`
})
</script>

<template>
  <div class="lib-card" :class="{ 'is-active': active }">
    <div class="card-header">
      <div class="title-wrap">
        <a :href="hfUrl" target="_blank" rel="noopener" class="model-link" :title="modelId">
          <span class="model-name">{{ shortName }}</span>
          <svg class="external-icon" viewBox="0 0 16 16" fill="currentColor" width="12" height="12" aria-hidden="true"><path d="M12 8v5a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5a1 1 0 0 0 0-2H3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V8a1 1 0 1 0-2 0zm3-6.5v.01L15 1a1 1 0 0 0-1-1H9.5a1 1 0 0 0 0 2h3.09L6.3 8.29a1 1 0 1 0 1.41 1.42L14 3.41V6.5a1 1 0 1 0 2 0V2a1 1 0 0 0-1-1z"/></svg>
        </a>
        <div class="model-subtitle">{{ modelId }}</div>
      </div>
      <div class="header-badges">
        <AppBadge variant="neutral" size="sm">{{ familyLabel }}</AppBadge>
        <AppBadge variant="info" size="sm">{{ quantLabel }}</AppBadge>
        <span v-if="isMtplx" class="meta-pill meta-pill--accent">Lightning MLX</span>
      </div>
    </div>

    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Size on disk</div>
        <div class="metric-value mono">{{ sizeLabel }}</div>
        <div class="metric-detail">Local cache footprint</div>
      </div>
      <div class="metric-card" :class="`metric-card--${fitInfo.tone}`">
        <div class="metric-label">Memory estimate</div>
        <div class="metric-value">{{ fitInfo.label }}</div>
        <div class="metric-detail">{{ fitInfo.detail }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Architecture</div>
        <div class="metric-value">{{ architectureLabel }}</div>
        <div class="metric-detail">{{ paramCountLabel ?? 'Parameter count unknown' }}</div>
      </div>
    </div>

    <div v-if="hasBenchmarks" class="metrics-grid metrics-grid--benchmarks">
      <div class="metric-card metric-card--performance">
        <div class="metric-label">Best speed</div>
        <div class="metric-value mono">{{ bestSpeedLabel }}</div>
        <div class="metric-detail">{{ bestSpeedDetail }}</div>
      </div>
      <div class="metric-card metric-card--performance">
        <div class="metric-label">Quality benchmark</div>
        <div class="metric-value mono">{{ qualityBenchmarkLabel }}</div>
        <div class="metric-detail">{{ qualityBenchmarkDetail }}</div>
      </div>
    </div>
    <button v-else class="bench-empty" type="button" @click="router.push('/benchmarks')">
      <span class="bench-empty-label">No benchmark data yet</span>
      <span class="bench-empty-link">Run benchmarks →</span>
    </button>

    <div v-if="qualityPills.length" class="quality-row">
      <span class="quality-label">Quality scores</span>
      <div class="quality-pills">
        <span v-for="score in qualityPills" :key="score.label" class="score-pill mono">
          <span class="score-key">{{ score.label }}</span>
          <span class="score-val">{{ formatScore(score.value) }}</span>
        </span>
      </div>
    </div>

    <div class="card-footer">
      <div class="status-group">
        <AppBadge v-if="isRestarting" variant="warning" size="sm">Restarting</AppBadge>
        <AppBadge v-else-if="active" variant="success" size="sm">Serving</AppBadge>
        <AppBadge v-if="cached" variant="neutral" size="sm">Cached</AppBadge>
      </div>

      <div class="card-actions">
        <template v-if="active">
          <AppButton variant="secondary" size="sm" :loading="isLoading" @click="emit('load')">Reload</AppButton>
        </template>
        <template v-else-if="cached">
          <AppButton variant="primary" size="sm" :loading="isLoading" @click="emit('load')">Serve</AppButton>
          <AppButton variant="ghost" size="sm" class="btn-delete" @click="emit('delete')">Delete</AppButton>
        </template>
        <template v-else>
          <div v-if="isDownloading" class="progress-wrap">
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: `${queueItem?.progress ?? 0}%` }" />
            </div>
            <span class="progress-pct mono">{{ Math.round(queueItem?.progress ?? 0) }}%</span>
          </div>
          <AppButton v-else variant="secondary" size="sm" @click="emit('download')">Download</AppButton>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lib-card {
  box-sizing: border-box;
  height: 248px;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  background: var(--bg-surface);
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.lib-card:hover {
  background: color-mix(in srgb, var(--bg-elevated) 30%, var(--bg-surface));
}

.lib-card.is-active {
  background: color-mix(in srgb, var(--ac-bg) 65%, var(--bg-surface));
  border-color: var(--ac-border);
}

.card-header,
.card-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.card-footer {
  align-items: center;
  margin-top: auto;
}

.title-wrap {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.model-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--tx-primary);
  text-decoration: none;
}

.model-link:hover .model-name,
.model-link:hover .external-icon {
  color: var(--ac-hover);
  opacity: 1;
}

.model-name {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-subtitle {
  font-size: 12px;
  color: var(--tx-tertiary);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.external-icon {
  flex-shrink: 0;
  color: var(--tx-muted);
  opacity: 0.55;
  transition: opacity var(--transition-fast), color var(--transition-fast);
}

.header-badges,
.status-group,
.card-actions,
.quality-pills {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.meta-pill,
.score-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: var(--r-pill);
  border: 1px solid var(--bd-default);
  background: var(--bg-elevated);
  color: var(--tx-secondary);
  font-size: 12px;
}

.meta-pill--accent {
  color: var(--si-300);
  border-color: color-mix(in srgb, var(--si-500) 28%, transparent);
  background: color-mix(in srgb, var(--si-500) 10%, transparent);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-2);
}

.metrics-grid--benchmarks {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.metric-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: var(--r-md);
  border: 1px solid var(--bd-default);
  background: var(--bg-elevated);
}

.metric-card--good {
  border-color: color-mix(in srgb, var(--ph-400) 26%, var(--bd-default));
}

.metric-card--warn {
  border-color: color-mix(in srgb, var(--cu-400) 32%, var(--bd-default));
}

.metric-card--danger {
  border-color: color-mix(in srgb, var(--cr-500) 30%, var(--bd-default));
}

.metric-label,
.quality-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.metric-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-detail {
  font-size: 12px;
  color: var(--tx-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono,
.score-pill {
  font-family: var(--font-mono);
}

.bench-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
  padding: 10px 12px;
  border: 1px dashed var(--bd-emphasis);
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--bg-elevated) 40%, transparent);
  color: var(--tx-secondary);
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.bench-empty:hover {
  border-color: var(--ac-border);
  background: color-mix(in srgb, var(--ac-bg) 30%, var(--bg-elevated));
}

.bench-empty-label {
  font-size: 12px;
}

.bench-empty-link {
  font-size: 12px;
  font-weight: 700;
  color: var(--si-300);
}

.quality-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.score-key {
  color: var(--tx-tertiary);
}

.score-val {
  color: var(--tx-primary);
  font-weight: 700;
}

.btn-delete:hover {
  color: var(--cr-300) !important;
  border-color: color-mix(in srgb, var(--cr-500) 28%, transparent) !important;
  background: color-mix(in srgb, var(--cr-500) 10%, transparent) !important;
}

.progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 132px;
}

.progress-track {
  flex: 1;
  height: 5px;
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
  min-width: 36px;
  text-align: right;
  font-size: 12px;
  color: var(--tx-secondary);
}
</style>
