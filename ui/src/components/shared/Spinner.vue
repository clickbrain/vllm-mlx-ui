<!--
  Spinner — animated loading indicator.

  Props:
  - size: diameter in px (default: 18)
  - color: CSS color or token (default: var(--si-500))

  Usage:
    <Spinner :size="24" />
    <Spinner size="sm" />  <!-- shorthand for 14px -->
-->
<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  size?: number | 'sm' | 'md' | 'lg'
  color?: string
}>(), {
  size: 18,
  color: 'var(--si-500)',
})

const diameter = computed(() => {
  if (typeof props.size === 'number') return props.size
  return { sm: 14, md: 18, lg: 24 }[props.size] ?? 18
})
</script>

<template>
  <span
    class="spinner"
    :style="{
      width: diameter + 'px',
      height: diameter + 'px',
      borderWidth: Math.max(1.5, diameter / 8) + 'px',
      borderTopColor: color,
    }"
    role="status"
    aria-label="Loading"
  />
</template>

<style scoped>
.spinner {
  display: inline-block;
  border: 2px solid var(--bd-emphasis);
  border-top-color: var(--si-500);
  border-radius: 50%;
  animation: spin .6s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
