<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{
  title: string
  defaultOpen?: boolean
}>()

const open = ref(false)
onMounted(() => { open.value = props.defaultOpen ?? false })
</script>

<template>
  <div class="collapsible" :class="{ open }">
    <button class="collapsible-header" @click="open = !open" :aria-expanded="open">
      <span class="collapsible-title">{{ title }}</span>
      <svg class="chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" width="14" height="14" aria-hidden="true">
        <path d="M4 6l4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div v-if="open" class="collapsible-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.collapsible {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
  transition: border-color var(--transition-fast);
}
.collapsible.open { border-color: var(--bd-emphasis); }

.collapsible-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-3) var(--space-5);
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--tx-secondary);
  font-family: inherit;
  text-align: left;
  transition: background var(--transition-fast);
}
.collapsible-header:hover { background: var(--bg-elevated); }

.collapsible-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.chevron {
  color: var(--tx-tertiary);
  transition: transform var(--transition-base);
  flex-shrink: 0;
}
.open .chevron { transform: rotate(180deg); }

.collapsible-body {
  border-top: 1px solid var(--bd-default);
  padding: var(--space-4) var(--space-5);
}
</style>
