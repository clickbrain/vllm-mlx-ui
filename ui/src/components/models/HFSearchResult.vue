<script setup lang="ts">
import { computed } from 'vue'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'
import type { ModelBadge } from '@/composables/useModelScoring'

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
  /** Currently available (free) unified memory in GB */
  available_ram_gb?: number
  /** Best-choice badges for this model — one per use case won */
  badges?: ModelBadge[]
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
  if (!props.last_modified) return 'Date unknown'
  try {
    const date = new Date(props.last_modified)
    if (Number.isNaN(date.getTime())) return 'Date unknown'
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return 'Date unknown'
  }
})

const hfUrl = computed(() => `https://huggingface.co/${props.id}`)

const shortName = computed(() => {
  const parts = props.id.split('/')
  return parts.length > 1 ? parts.slice(1).join('/') : props.id
})

const orgName = computed(() => {
  const parts = props.id.split('/')
  return parts.length > 1 ? parts[0] : null
})

const sizeLabel = computed(() => {
  if (!props.size_gb) return '—'
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

/**
 * Warn when the model fits the hardware (total RAM) but won't load right now
 * because there isn't enough free memory.
 */
const availableWarning = computed(() => {
  if (!props.size_gb || !props.available_ram_gb) return null
  if (props.fit_level === 'too_tight') return null
  const free = props.available_ram_gb
  if (props.size_gb <= free) return null
  return `${free.toFixed(1)} GB free now — close apps to load`
})

const hasSizeEstimate = computed(() => props.size_gb != null)

const hasBadges = computed(() => props.badges && props.badges.length > 0)
const capabilityTags = computed(() => {
  const id = props.id.toLowerCase()
  const hfTags = props.tags.map(t => t.toLowerCase())
  const caps: Array<{ label: string; style: string }> = []

  const paramMatch = id.match(/[._\-/](\d+(?:\.\d+)?)\s*b(?:[._\-/]|$)/) ??
                     id.match(/^(\d+(?:\.\d+)?)\s*b(?:[._\-/]|$)/)
  if (paramMatch) {
    caps.push({ label: `${paramMatch[1]}B`, style: 'param' })
  }

  const quantPatterns = [
    [/\b(bf16|bfloat16)\b/, 'bf16'],
    [/\b(fp16|float16)\b/, 'fp16'],
    [/\b(4bit|4-bit|q4)\b/, '4-bit'],
    [/\b(8bit|8-bit|q8)\b/, '8-bit'],
    [/\b(2bit|2-bit|q2)\b/, '2-bit'],
    [/\b(3bit|3-bit|q3)\b/, '3-bit'],
    [/\b(6bit|6-bit|q6)\b/, '6-bit'],
  ] as Array<[RegExp, string]>
  for (const [re, label] of quantPatterns) {
    if (re.test(id)) {
      caps.push({ label, style: 'quant' })
      break
    }
  }

  const allText = id + ' ' + hfTags.join(' ')
  if (/instruct|chat|assistant/.test(allText)) caps.push({ label: 'Instruct', style: 'cap' })
  if (/vision|vl\b|vlm|multimodal|image/.test(allText)) caps.push({ label: 'Vision', style: 'vision' })
  if (/code|coding|coder|starcoder|deepseek-coder/.test(allText)) caps.push({ label: 'Code', style: 'code' })
  if (/thinking|reasoning|reason|qwq|deepseek-r/.test(allText)) caps.push({ label: 'Thinking', style: 'think' })
  if (/embed|embedding/.test(allText)) caps.push({ label: 'Embed', style: 'cap' })
  if (/audio|speech|whisper/.test(allText)) caps.push({ label: 'Audio', style: 'cap' })

  return caps
})
</script>

<template>
  <div class="hf-result" :class="{ 'hf-result--badged': hasBadges }">
    <!-- Best Choice badges — one stripe per use case won -->
    <div v-if="hasBadges" class="badge-banners">
      <div
        v-for="badge in badges"
        :key="badge.useCase"
        class="badge-banner"
        :style="{ '--badge-color': badge.color }"
      >
        <span class="badge-label">{{ badge.label }}</span>
        <span class="badge-reason">{{ badge.reason }}</span>
      </div>
    </div>

    <div class="result-body">
      <!-- Top row: model name + MLX badge + download button -->
      <div class="result-top">
        <div class="result-id-group">
          <a :href="hfUrl" target="_blank" rel="noopener" class="model-link" :title="`View ${props.id} on HuggingFace`">
            <span v-if="orgName" class="result-org">{{ orgName }}/</span>
            <span class="result-name">{{ shortName }}</span>
            <svg class="external-icon" viewBox="0 0 16 16" fill="currentColor" width="12" height="12"><path d="M12 8v5a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5a1 1 0 0 0 0-2H3a3 3 0 0 0-3 3v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3V8a1 1 0 1 0-2 0zm3-6.5v.01L15 1a1 1 0 0 0-1-1H9.5a1 1 0 0 0 0 2h3.09L6.3 8.29a1 1 0 1 0 1.41 1.42L14 3.41V6.5a1 1 0 1 0 2 0V2a1 1 0 0 0-1-1z"/></svg>
          </a>
          <AppBadge v-if="is_mlx" variant="info" size="sm">MLX</AppBadge>
        </div>
        <AppButton variant="secondary" size="sm" @click="emit('download')">Download</AppButton>
      </div>

      <!-- Capability tags row -->
      <div v-if="capabilityTags.length > 0" class="cap-tags-row">
        <span
          v-for="tag in capabilityTags"
          :key="tag.label"
          class="cap-tag"
          :class="`cap-tag--${tag.style}`"
        >{{ tag.label }}</span>
      </div>

      <!-- Fit gauge: model size vs total RAM bar -->
      <div v-if="hasSizeEstimate && fitInfo" class="fit-gauge-row">
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
      <div v-else-if="hasSizeEstimate && !fitInfo" class="fit-gauge-row">
        <div class="fit-gauge-track">
          <div class="fit-gauge-fill fit-gauge-unknown" style="width: 30%" />
        </div>
        <div class="fit-gauge-labels">
          <span class="fit-size">{{ sizeLabel }}</span>
          <span class="fit-tag fit-unknown">Unknown fit</span>
        </div>
      </div>

      <!-- Available RAM warning (fits hardware but not right now) -->
      <div v-if="availableWarning" class="available-warning" role="alert">
        <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12" class="warn-icon"><path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.75 4h1.5v4.5h-1.5V5zm0 5.5h1.5V12h-1.5v-1.5z"/></svg>
        {{ availableWarning }}
      </div>

      <!-- Size estimate caveat -->
      <p v-if="hasSizeEstimate" class="fit-note">Estimated — actual usage varies by model architecture.</p>

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
        <span class="meta-stat">Updated: {{ dateFormatted }}</span>
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
  overflow: hidden;
}
.hf-result:hover {
  border-color: var(--bd-emphasis);
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}

/* Card with at least one badge gets a subtle accent border */
.hf-result--badged {
  border-color: rgba(91, 106, 208, 0.35);
  box-shadow: 0 0 0 1px rgba(91, 106, 208, 0.15);
}
.hf-result--badged:hover {
  box-shadow: 0 0 0 1px rgba(91, 106, 208, 0.25), 0 2px 8px rgba(0,0,0,.10);
}

/* Badge banners — one row per use-case win */
.badge-banners {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.badge-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 5px var(--space-4);
  background: color-mix(in srgb, var(--badge-color) 10%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--badge-color) 30%, transparent);
  font-size: 12px;
}
.badge-label {
  font-weight: 700;
  color: var(--badge-color);
  white-space: nowrap;
  letter-spacing: 0.02em;
}
.badge-reason {
  font-size: 11px;
  color: var(--tx-tertiary);
  margin-left: auto;
  text-align: right;
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
.model-link {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  text-decoration: none;
  min-width: 0;
  overflow: hidden;
}
.model-link:hover .result-org,
.model-link:hover .result-name {
  color: var(--si-300);
}
.model-link:hover .external-icon {
  opacity: 1;
}
.external-icon {
  flex-shrink: 0;
  opacity: 0.4;
  transition: opacity var(--transition-fast);
  position: relative;
  top: 1px;
}
.result-org {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-tertiary);
  white-space: nowrap;
  transition: color var(--transition-fast);
}
.result-name {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 600;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--transition-fast);
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

/* Available RAM warning */
.available-warning {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  background: rgba(234, 179, 8, 0.10);
  border: 1px solid rgba(234, 179, 8, 0.30);
  border-radius: var(--r-sm);
  font-size: 11.5px;
  color: #ca8a04;
  font-family: var(--font-mono);
}
.warn-icon { flex-shrink: 0; opacity: 0.8; }

.fit-note {
  font-size: 11.5px;
  color: var(--tx-muted);
  margin: 0;
  font-style: italic;
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

/* Capability tags */
.cap-tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.cap-tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 18px;
}
.cap-tag--param {
  background: var(--bg-subtle);
  color: var(--tx-secondary);
  border: 1px solid var(--bd-subtle);
  font-family: var(--font-mono);
}
.cap-tag--quant {
  background: rgba(91, 106, 208, 0.12);
  color: var(--si-300);
  border: 1px solid rgba(91, 106, 208, 0.25);
  font-family: var(--font-mono);
}
.cap-tag--cap {
  background: var(--bg-elevated);
  color: var(--tx-secondary);
  border: 1px solid var(--bd-default);
}
.cap-tag--vision {
  background: rgba(147, 112, 219, 0.12);
  color: #9370db;
  border: 1px solid rgba(147, 112, 219, 0.3);
}
.cap-tag--code {
  background: rgba(32, 178, 170, 0.12);
  color: #20b2aa;
  border: 1px solid rgba(32, 178, 170, 0.3);
}
.cap-tag--think {
  background: rgba(255, 165, 0, 0.12);
  color: #e69500;
  border: 1px solid rgba(255, 165, 0, 0.3);
}
</style>
