<!--
  ConfirmModal — accessible confirmation dialog rendered via <Teleport to="body">.

  Props:
  - title: dialog header text
  - message: body copy asking the user to confirm
  - confirmLabel: label for the confirm button (default: 'Confirm')
  - destructive: applies red styling to the confirm button for dangerous actions

  Emits:
  - confirm: user clicked the confirm button
  - cancel: user clicked Cancel or the backdrop

  Usage: pair with a v-if flag; listen for @confirm/@cancel to act and dismiss.
-->
<script setup lang="ts">

defineEmits<{
  confirm: []
  cancel: []
}>()
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @click.self="$emit('cancel')">
      <div class="modal-box" role="dialog" aria-modal="true">
        <div class="modal-header">
          <span class="modal-title">{{ title }}</span>
        </div>
        <div class="modal-body">
          <p class="modal-message">{{ message }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="$emit('cancel')">Cancel</button>
          <button class="btn-confirm" :class="{ destructive }" @click="$emit('confirm')">
            {{ confirmLabel ?? 'Confirm' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, .60);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fade-in .1s ease;
}

@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

.modal-box {
  background: var(--bg-surface);
  border: 1px solid var(--bd-emphasis);
  border-radius: var(--r-xl, 12px);
  box-shadow: 0 20px 60px rgba(0,0,0,.5);
  min-width: 320px;
  max-width: 480px;
  width: 90vw;
  animation: slide-up .15s ease;
}

@keyframes slide-up { from { transform: translateY(8px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

.modal-header {
  padding: var(--space-5) var(--space-5) var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
}

.modal-title {
  font-size: var(--text-base, 15px);
  font-weight: 600;
  color: var(--tx-primary);
}

.modal-body {
  padding: var(--space-4) var(--space-5);
}

.modal-message {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  line-height: 1.5;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-5);
}

.btn-cancel,
.btn-confirm {
  padding: 7px 18px;
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.btn-cancel {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-secondary);
}
.btn-cancel:hover {
  background: var(--bg-canvas);
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}

.btn-confirm {
  background: var(--si-600, #4c56b8);
  border: 1px solid var(--si-500);
  color: #fff;
}
.btn-confirm:hover {
  background: var(--si-500);
}
.btn-confirm.destructive {
  background: rgba(239, 68, 68, .15);
  border-color: rgba(239, 68, 68, .40);
  color: var(--cr-300, #f87171);
}
.btn-confirm.destructive:hover {
  background: rgba(239, 68, 68, .25);
}
</style>
