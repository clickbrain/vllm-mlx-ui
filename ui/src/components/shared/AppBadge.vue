<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral'
  size?: 'sm' | 'md'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'neutral',
  size: 'md',
})

const classes = computed(() => ['badge', `badge-${props.variant}`, `badge-${props.size}`])
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: var(--r-pill);
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
  line-height: 1;
  border: 1px solid transparent;
}

.badge-sm {
  padding: 2px 7px;
  font-size: 10px;
}
.badge-md {
  padding: 3px 9px;
  font-size: 11px;
}

/* success — phosphor */
.badge-success {
  color: var(--ph-400);
  background: rgba(34, 197, 94, .08);
  border-color: rgba(34, 197, 94, .20);
}

/* warning — copper */
.badge-warning {
  color: var(--cu-300);
  background: rgba(217, 119, 6, .08);
  border-color: rgba(217, 119, 6, .20);
}

/* error — ruby */
.badge-error {
  color: var(--cr-300);
  background: rgba(239, 68, 68, .08);
  border-color: rgba(239, 68, 68, .20);
}

/* info — silicon */
.badge-info {
  color: var(--si-300);
  background: rgba(91, 106, 208, .08);
  border-color: rgba(91, 106, 208, .20);
}

/* neutral — muted */
.badge-neutral {
  color: var(--tx-muted);
  background: var(--bg-elevated);
  border-color: var(--bd-default);
}
</style>
