<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  loading?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'secondary',
  size: 'md',
  loading: false,
  disabled: false,
})

const classes = computed(() => [
  'btn',
  `btn-${props.variant}`,
  `btn-${props.size}`,
  { 'btn-loading': props.loading },
])
</script>

<template>
  <button :class="classes" :disabled="disabled || loading" v-bind="$attrs">
    <span v-if="loading" class="btn-spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: inherit;
  font-weight: 500;
  border-radius: var(--r-md);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast),
    opacity var(--transition-fast);
  white-space: nowrap;
  outline: none;
  text-decoration: none;
}
.btn:focus-visible {
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .22);
}
.btn:disabled {
  opacity: .4;
  cursor: not-allowed;
}

/* Sizes */
.btn-sm {
  padding: 5px 10px;
  font-size: 12px;
  letter-spacing: .01em;
}
.btn-md {
  padding: 7px 14px;
  font-size: var(--text-sm);
}

/* Variants */
.btn-primary {
  background: var(--ac-primary);
  border: 1px solid var(--si-600);
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--ac-hover);
}

.btn-secondary {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-secondary);
}
.btn-secondary:hover:not(:disabled) {
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}

.btn-ghost {
  background: transparent;
  border: 1px solid transparent;
  color: var(--tx-secondary);
}
.btn-ghost:hover:not(:disabled) {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}

.btn-danger {
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .20);
  color: var(--cr-300);
}
.btn-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, .14);
  border-color: rgba(239, 68, 68, .32);
}

/* Spinner */
@keyframes spin { to { transform: rotate(360deg); } }
.btn-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin .6s linear infinite;
  flex-shrink: 0;
}
</style>
