<script setup lang="ts">
import { useCommandPaletteStore } from '@/stores/commandPalette'
import type { Command } from '@/stores/commandPalette'

const palette = useCommandPaletteStore()

function handleKeydown(e: KeyboardEvent) {
  palette.onKeydown(e)
}

function selectCommand(cmd: Command) {
  palette.execute(cmd)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="palette.isOpen" class="palette-overlay" @click.self="palette.close()">
        <div class="palette-card" @keydown="handleKeydown">
          <div class="palette-search">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd" />
            </svg>
            <input
              ref="searchInput"
              v-model="palette.query"
              type="text"
              placeholder="Type a command or search..."
              class="palette-input"
              autofocus
            />
            <kbd class="palette-kbd">ESC</kbd>
          </div>
          <ul class="palette-list" role="listbox">
            <li
              v-for="(cmd, idx) in palette.filteredCommands"
              :key="cmd.id"
              class="palette-item"
              :class="{ active: idx === palette.selectedIndex }"
              role="option"
              :aria-selected="idx === palette.selectedIndex"
              @click="selectCommand(cmd)"
              @mouseenter="palette.selectedIndex = idx"
            >
              <span class="palette-icon">{{ cmd.icon }}</span>
              <span class="palette-label">{{ cmd.label }}</span>
              <span v-if="cmd.shortcut" class="palette-shortcut">{{ cmd.shortcut }}</span>
            </li>
          </ul>
          <div v-if="!palette.filteredCommands.length" class="palette-empty">
            No commands found
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.palette-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 20vh;
  z-index: 9999;
}

.palette-card {
  background: var(--bg1);
  border: 1px solid var(--bd);
  border-radius: 12px;
  width: 90%;
  max-width: 560px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.palette-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--bd);
  color: var(--tx-muted);
}

.palette-input {
  flex: 1;
  background: none;
  border: none;
  color: var(--tx1);
  font-size: 15px;
  font-family: inherit;
  outline: none;
}

.palette-input::placeholder {
  color: var(--tx3);
}

.palette-kbd {
  font-size: 11px;
  padding: 2px 6px;
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: 4px;
  color: var(--tx3);
  font-family: var(--font-mono);
}

.palette-list {
  list-style: none;
  padding: 6px;
  margin: 0;
  max-height: 320px;
  overflow-y: auto;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--tx2);
  font-size: 14px;
  transition: background 0.1s;
}

.palette-item:hover,
.palette-item.active {
  background: var(--bg-elevated);
  color: var(--tx1);
}

.palette-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

.palette-label {
  flex: 1;
}

.palette-shortcut {
  font-size: 12px;
  color: var(--tx3);
  font-family: var(--font-mono);
}

.palette-empty {
  padding: 24px;
  text-align: center;
  color: var(--tx3);
  font-size: 14px;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.15s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
