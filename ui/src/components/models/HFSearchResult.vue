<script setup lang="ts">
import { computed } from 'vue'
import AppBadge from '@/components/shared/AppBadge.vue'
import AppButton from '@/components/shared/AppButton.vue'

const props = defineProps<{
  id: string
  downloads: number
  likes: number
  is_mlx: boolean
  tags: string[]
}>()

const emit = defineEmits<{
  download: []
}>()

function abbreviate(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

const downloadsFormatted = computed(() => abbreviate(props.downloads))
const likesFormatted = computed(() => abbreviate(props.likes))
</script>

<template>
  <div class="hf-result">
    <div class="result-id">
      <span class="model-id">{{ id }}</span>
      <AppBadge v-if="is_mlx" variant="info" size="sm">MLX</AppBadge>
    </div>
    <div class="result-stats">
      <span class="stat">↓ {{ downloadsFormatted }}</span>
      <span class="stat">♥ {{ likesFormatted }}</span>
    </div>
    <AppButton variant="secondary" size="sm" @click="emit('download')">Download</AppButton>
  </div>
</template>

<style scoped>
.hf-result {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  transition: background var(--transition-fast);
}

.hf-result:last-child { border-bottom: none; }
.hf-result:hover { background: rgba(255, 255, 255, .012); }

.result-id {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
}

.model-id {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--tx-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-stats {
  display: flex;
  gap: var(--space-5);
  flex-shrink: 0;
}

.stat {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--tx-muted);
  min-width: 60px;
  text-align: right;
}
</style>
