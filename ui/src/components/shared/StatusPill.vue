<!--
  StatusPill — compact inline indicator for server/process lifecycle states.

  Props:
  - status: 'running' | 'stopped' | 'loading' | 'error'

  Renders a coloured dot + label. Colour mapping is controlled by CSS
  .status-pill--{status} classes defined in this component's scoped styles.

  Usage: <StatusPill :status="serverStore.status" />
-->
<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  status: 'running' | 'stopped' | 'loading' | 'error'
}

const props = defineProps<Props>()

const label = computed<string>(() => ({
  running: 'Running',
  stopped: 'Stopped',
  loading: 'Loading',
  error:   'Error',
}[props.status]))
</script>

<template>
  <span class="status-pill" :class="`status-pill--${status}`">
    <span class="status-pill-dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
  border-radius: var(--r-pill);
  padding: 3px 9px 3px 7px;
  border: 1px solid transparent;
}

.status-pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Running */
.status-pill--running {
  color: var(--ph-300);
  background: rgba(34, 197, 94, .06);
  border-color: rgba(34, 197, 94, .14);
}
.status-pill--running .status-pill-dot {
  background: var(--ph-400);
  box-shadow: 0 0 0 2px rgba(34, 197, 94, .15);
}

/* Stopped */
.status-pill--stopped {
  color: var(--tx-muted);
  background: var(--bg-elevated);
  border-color: var(--bd-default);
}
.status-pill--stopped .status-pill-dot {
  background: var(--g-600);
}

/* Loading */
.status-pill--loading {
  color: var(--si-300);
  background: rgba(91, 106, 208, .08);
  border-color: rgba(91, 106, 208, .20);
}
.status-pill--loading .status-pill-dot {
  background: var(--si-500);
  animation: pulse .9s ease infinite;
}

/* Error */
.status-pill--error {
  color: var(--cr-300);
  background: rgba(239, 68, 68, .08);
  border-color: rgba(239, 68, 68, .20);
}
.status-pill--error .status-pill-dot {
  background: var(--cr-500);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: .35; }
}
</style>
