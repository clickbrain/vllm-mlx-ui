<script setup lang="ts">
import { useTourStore } from '@/stores/tour'

const tour = useTourStore()

const steps = [
  { target: '[data-tour="serve"]', title: 'Server Control', text: 'Start and stop your vLLM-MLX server from here.' },
  { target: '[data-tour="models"]', title: 'Model Management', text: 'Load, unload, and manage your MLX models.' },
  { target: '[data-tour="chat"]', title: 'Chat Interface', text: 'Test your models with the built-in chat interface.' },
  { target: '[data-tour="settings"]', title: 'Settings', text: 'Configure server, API keys, and preferences.' }
]
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="tour.isActive && steps[tour.currentStep]" class="tour-overlay" @click.self="tour.skip()">
        <div class="tour-card">
          <h3>{{ steps[tour.currentStep].title }}</h3>
          <p>{{ steps[tour.currentStep].text }}</p>
          <div class="tour-footer">
            <span class="tour-step">{{ tour.currentStep + 1 }} / {{ tour.totalSteps }}</span>
            <div class="tour-actions">
              <button class="btn-text" @click="tour.skip()">Skip</button>
              <button class="btn-primary" @click="tour.next()">
                {{ tour.currentStep < tour.totalSteps - 1 ? 'Next' : 'Finish' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.tour-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.tour-card {
  background: var(--bg1);
  border: 1px solid var(--bd);
  border-radius: 12px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.tour-card h3 {
  color: var(--tx1);
  margin: 0 0 8px;
  font-size: 18px;
}

.tour-card p {
  color: var(--tx2);
  margin: 0 0 24px;
  font-size: 14px;
  line-height: 1.5;
}

.tour-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tour-step {
  color: var(--tx3);
  font-size: 13px;
}

.tour-actions {
  display: flex;
  gap: 8px;
}

.btn-text {
  background: none;
  border: none;
  color: var(--tx2);
  cursor: pointer;
  padding: 8px 16px;
  font-size: 14px;
}

.btn-primary {
  background: var(--accent, #646cff);
  border: none;
  color: white;
  padding: 8px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
