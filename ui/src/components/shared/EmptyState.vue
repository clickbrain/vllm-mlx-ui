<!--
  EmptyState — placeholder shown when a list/view has no data.

  Props:
  - title: main heading text
  - description: supporting copy
  - icon: optional emoji or text icon

  Slots:
  - default: optional action content (e.g. buttons)

  Usage:
    <EmptyState title="No models downloaded" description="Use the Find tab to discover models.">
      <AppButton @click="goToFind">Go to Find</AppButton>
    </EmptyState>
-->
<script setup lang="ts">
defineProps<{
  title: string
  description?: string
  icon?: string
}>()
</script>

<template>
  <div class="empty-state" role="status">
    <span v-if="icon" class="empty-icon" aria-hidden="true">{{ icon }}</span>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-10) var(--space-6);
  text-align: center;
}

.empty-icon {
  font-size: 32px;
  line-height: 1;
  opacity: 0.6;
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-primary);
}

.empty-desc {
  font-size: var(--text-sm);
  color: var(--tx-tertiary);
  line-height: 1.5;
}

.empty-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
}
</style>
