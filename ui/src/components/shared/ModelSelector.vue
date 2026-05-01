<!--
  ModelSelector — dropdown for selecting an inference model.

  Props:
  - modelValue: currently selected model ID
  - models: array of { id: string; label?: string } options
  - loading: shows spinner and disables interaction
  - placeholder: text shown when no model is selected

  Emits:
  - update:modelValue: new model ID on change

  Usage:
    <ModelSelector v-model="selectedId" :models="models" :loading="switching" />
-->
<script setup lang="ts">
import Spinner from './Spinner.vue'

export interface ModelOption {
  id: string
  label?: string
}

defineProps<{
  modelValue: string | null
  models: ModelOption[]
  loading?: boolean
  placeholder?: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <div class="model-selector">
    <label class="selector-label">Model</label>
    <div class="selector-control">
      <select
        class="selector-select"
        :value="modelValue ?? ''"
        :disabled="loading"
        aria-label="Select model"
        @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-if="!modelValue" value="" disabled>{{ placeholder ?? 'No model loaded' }}</option>
        <option
          v-if="modelValue && !models.find(m => m.id === modelValue)"
          :value="modelValue"
        >{{ modelValue }}</option>
        <option v-for="m in models" :key="m.id" :value="m.id">
          {{ m.label ?? m.id.split('/').pop() ?? m.id }}
        </option>
      </select>
      <Spinner v-if="loading" :size="14" />
    </div>
  </div>
</template>

<style scoped>
.model-selector {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.selector-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.selector-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.selector-select {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 14px;
  padding: 5px 28px 5px 10px;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7280'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  cursor: pointer;
  transition: border-color var(--transition-fast);
  min-width: 200px;
  max-width: 320px;
}

.selector-select:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.selector-select:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
