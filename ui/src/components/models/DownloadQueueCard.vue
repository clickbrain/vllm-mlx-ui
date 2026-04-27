<!--
  DownloadQueueCard — floating card showing active model downloads.

  Reads downloadQueue from modelsStore and renders a progress bar per item.
  Only mounts when there is at least one download in progress (v-if guard).
  No props — driven entirely by store state.
-->
<script setup lang="ts">
import { useModelsStore } from '@/stores/models'

const modelsStore = useModelsStore()
</script>

<template>
  <div v-if="modelsStore.downloadQueue.length > 0" class="queue-card">
    <div class="queue-header">
      <span class="queue-title">Downloading</span>
      <span class="queue-count">{{ modelsStore.downloadQueue.length }}</span>
    </div>
    <div class="queue-list">
      <div
        v-for="item in modelsStore.downloadQueue"
        :key="item.id"
        class="queue-row"
      >
        <div class="row-top">
          <span class="item-id">{{ item.id }}</span>
          <span class="item-pct">{{ Math.round(item.progress) }}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${item.progress}%` }" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.queue-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.queue-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
}

.queue-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  flex: 1;
}

.queue-count {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-muted);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  padding: 1px 7px;
}

.queue-row {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.queue-row:last-child { border-bottom: none; }

.row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.item-id {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--tx-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 80%;
}

.item-pct {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-muted);
  flex-shrink: 0;
}

.progress-track {
  width: 100%;
  height: 4px;
  background: var(--bg-elevated);
  border-radius: var(--r-pill);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--si-500);
  border-radius: var(--r-pill);
  transition: width .3s ease;
}
</style>
