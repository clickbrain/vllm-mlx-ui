<!--
  TabBar — horizontally-arranged tab selector for multi-section views.

  Props:
  - tabs: string array of tab labels to render
  - modelValue (v-model): the currently active tab label

  Emits 'update:modelValue' on click so v-model wiring works.
  Renders with proper ARIA roles (tablist / tab) for accessibility.
-->
<script setup lang="ts">
defineProps<{
  tabs: string[]
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <div class="tab-bar" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab"
      role="tab"
      class="tab-pill"
      :class="{ active: modelValue === tab }"
      :aria-selected="modelValue === tab"
      @click="$emit('update:modelValue', tab)"
    >{{ tab }}</button>
  </div>
</template>

<style scoped>
.tab-bar {
  display: flex;
  gap: var(--space-1);
}

.tab-pill {
  padding: 5px 14px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-pill);
  color: var(--tx-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.tab-pill:hover:not(.active) {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}

.tab-pill.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}
</style>
