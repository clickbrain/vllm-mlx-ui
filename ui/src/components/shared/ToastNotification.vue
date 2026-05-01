<!--
  ToastNotification — global toast container rendered via <Teleport to="body">.

  Displays a stack of notification toasts at the bottom-right of the viewport.
  Each toast has a type-coloured left border, message text, and a dismiss button.
  Auto-dismisses after a configurable duration (0 = persistent).

  Mounted once in App.vue — do not instantiate manually.
-->
<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const toastStore = useToastStore()

function iconFor(type: string): string {
  return { info: 'ℹ', success: '✓', warning: '⚠', error: '✕' }[type] ?? 'ℹ'
}
</script>

<template>
  <Teleport to="body">
    <div v-if="toastStore.toasts.length" class="toast-stack" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toastStore.toasts"
          :key="toast.id"
          class="toast-item"
          :class="`toast-${toast.type}`"
          role="alert"
        >
          <span class="toast-icon" aria-hidden="true">{{ iconFor(toast.type) }}</span>
          <span class="toast-message">{{ toast.message }}</span>
          <button class="toast-dismiss" aria-label="Dismiss notification" @click="toastStore.remove(toast.id)">✕</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  bottom: var(--space-4);
  right: var(--space-4);
  z-index: 99999;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 420px;
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  border-left: 3px solid var(--g-500);
  box-shadow: 0 4px 16px rgba(0, 0, 0, .3);
  font-size: var(--text-sm);
  color: var(--tx-primary);
  pointer-events: auto;
  min-width: 260px;
}

.toast-info    { border-left-color: var(--si-500); }
.toast-success { border-left-color: var(--ph-500); }
.toast-warning { border-left-color: var(--cu-400); }
.toast-error   { border-left-color: var(--cr-500); }

.toast-icon {
  font-size: var(--text-base);
  flex-shrink: 0;
  line-height: 1;
}

.toast-message {
  flex: 1;
  line-height: 1.4;
}

.toast-dismiss {
  background: none;
  border: none;
  color: var(--tx-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  opacity: 0.6;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}
.toast-dismiss:hover { opacity: 1; }
.toast-dismiss:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--si-500);
  border-radius: var(--r-sm);
}

/* Transitions */
.toast-enter-active { transition: all .2s ease; }
.toast-leave-active { transition: all .15s ease; }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to   { opacity: 0; transform: translateX(20px); }
</style>
