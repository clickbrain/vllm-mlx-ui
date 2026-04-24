<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  label: string
  value: string
  copyable?: boolean
  dimWhenEmpty?: boolean
}>()

const copied = ref(false)

async function copy() {
  if (!props.value || props.value === '—') return
  await navigator.clipboard.writeText(props.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}
</script>

<template>
  <div class="endpoint-card" :class="{ dim: dimWhenEmpty && (!value || value === '—') }">
    <div class="card-label">{{ label }}</div>
    <div class="card-row">
      <span class="card-value">{{ value || '—' }}</span>
      <button v-if="copyable && value && value !== '—'" class="copy-btn" :class="{ copied }" @click="copy" :title="copied ? 'Copied!' : 'Copy'">
        <svg v-if="!copied" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="13" height="13">
          <rect x="5" y="5" width="9" height="9" rx="1.5"/>
          <path d="M11 5V3.5A1.5 1.5 0 009.5 2H3.5A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" width="13" height="13">
          <path d="M3 8l3.5 3.5L13 4.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.endpoint-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  transition: border-color var(--transition-fast);
}
.endpoint-card:hover { border-color: var(--bd-emphasis); }
.endpoint-card.dim { opacity: .5; }

.card-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 24px;
}

.card-value {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.copy-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--tx-tertiary);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}
.copy-btn:hover {
  background: var(--bg-elevated);
  color: var(--tx-primary);
  border-color: var(--bd-emphasis);
}
.copy-btn.copied {
  color: var(--ph-500);
  border-color: rgba(34, 197, 94, .3);
  background: rgba(34, 197, 94, .06);
}
</style>
