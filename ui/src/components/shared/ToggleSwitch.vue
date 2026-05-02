<!--
  ToggleSwitch — accessible on/off toggle.

  Props:
  - modelValue: boolean bound value
  - label: visible label text
  - description: optional helper text shown below

  Emits:
  - update:modelValue: toggled state

  Usage:
    <ToggleSwitch v-model="autoStart" label="Auto-start" description="Start server on launch" />
-->
<script setup lang="ts">
defineProps<{
  modelValue: boolean
  label: string
  description?: string
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <label class="toggle-switch">
    <div class="toggle-switch-body">
      <div class="toggle-switch-text">
        <span class="toggle-label">{{ label }}</span>
        <span v-if="description" class="toggle-desc">{{ description }}</span>
      </div>
      <div class="toggle-switch-control">
        <input
          type="checkbox"
          :checked="modelValue"
          class="toggle-input"
          @change="$emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
        />
        <span class="toggle-track">
          <span class="toggle-thumb" />
        </span>
      </div>
    </div>
  </label>
</template>

<style scoped>
.toggle-switch {
  display: block;
  cursor: pointer;
  user-select: none;
}

.toggle-switch-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.toggle-switch-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.toggle-label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--tx-primary);
}

.toggle-desc {
  font-size: 14px;
  color: var(--tx-muted);
  line-height: 1.4;
}

.toggle-switch-control {
  flex-shrink: 0;
}

.toggle-input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-track {
  display: block;
  width: 36px;
  height: 20px;
  border-radius: var(--r-pill);
  background: var(--g-600);
  border: 1px solid var(--bd-default);
  transition: background var(--transition-base), border-color var(--transition-base);
  position: relative;
}

.toggle-input:checked ~ .toggle-track {
  background: var(--si-500);
  border-color: var(--si-600);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  transition: transform var(--transition-base);
}

.toggle-input:checked ~ .toggle-track .toggle-thumb {
  transform: translateX(16px);
}

.toggle-input:focus-visible ~ .toggle-track {
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .22);
}

.toggle-switch:has(.toggle-input:disabled) {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
