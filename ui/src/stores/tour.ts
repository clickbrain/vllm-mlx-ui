import { defineStore } from 'pinia'
import { ref } from 'vue'

const TOUR_KEY = 'vllm-mlx-ui-tour-completed'

export const useTourStore = defineStore('tour', () => {
  const isActive = ref(false)
  const currentStep = ref(0)
  const totalSteps = 4

  function start() {
    isActive.value = true
    currentStep.value = 0
  }

  function next() {
    if (currentStep.value < totalSteps - 1) {
      currentStep.value++
    } else {
      finish()
    }
  }

  function skip() {
    finish()
  }

  function finish() {
    isActive.value = false
    localStorage.setItem(TOUR_KEY, 'true')
  }

  function checkFirstRun() {
    const completed = localStorage.getItem(TOUR_KEY)
    if (!completed) {
      start()
    }
  }

  return { isActive, currentStep, totalSteps, start, next, skip, finish, checkFirstRun }
})
