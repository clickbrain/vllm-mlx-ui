<!--
  ErrorBanner — dismissable error message banner.

  Props:
  - message: error text to display
  - dismissible: show dismiss button (default: true)

  Emits:
  - dismiss: user clicked the dismiss button

  Usage:
    <ErrorBanner :message="errorMsg" @dismiss="errorMsg = null" />
-->
<script setup lang="ts">
defineProps<{
  message: string
  dismissible?: boolean
}>()

defineEmits<{
  dismiss: []
}>()
</script>

<template>
  <div class="error-banner" role="alert">
    <span class="error-icon" aria-hidden="true">⚠</span>
    <span class="error-message">{{ message }}</span>
    <button
      v-if="dismissible"
      class="error-dismiss"
      aria-label="Dismiss error"
      @click="$emit('dismiss')"
    >✕</button>
  </div>
</template>

<style scoped>
.error-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--cr-300);
}

.error-icon {
  flex-shrink: 0;
  font-size: var(--text-base);
}

.error-message {
  flex: 1;
  line-height: 1.4;
}

.error-dismiss {
  background: none;
  border: none;
  color: var(--cr-300);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  opacity: 0.7;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}
.error-dismiss:hover { opacity: 1; }
.error-dismiss:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--si-500);
  border-radius: var(--r-sm);
}
</style>
