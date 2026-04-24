<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  unit?: string
  /** copper warning above this percent value (0–100). Used for memory. */
  warnAbove?: number
  /** treat as a percentage for color logic */
  isPercent?: boolean
}>()
</script>

<template>
  <div class="metric-card">
    <div class="metric-label">{{ label }}</div>
    <div class="metric-row">
      <span
        class="metric-value"
        :class="{
          warn: isPercent && warnAbove !== undefined && Number(value) > warnAbove,
          nominal: isPercent && warnAbove !== undefined && Number(value) <= warnAbove
        }"
      >{{ value }}</span>
      <span v-if="unit" class="metric-unit">{{ unit }}</span>
    </div>
  </div>
</template>

<style scoped>
.metric-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.metric-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.metric-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
}

.metric-value {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: 700;
  letter-spacing: -.5px;
  color: var(--tx-primary);
  transition: color var(--transition-slow);
}
.metric-value.warn    { color: var(--cu-400); }
.metric-value.nominal { color: var(--tx-primary); }

.metric-unit {
  font-size: var(--text-sm);
  color: var(--tx-tertiary);
  font-family: var(--font-mono);
}
</style>
