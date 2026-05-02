import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTourStore } from '@/stores/tour'

describe('TourStore', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('shows tour on first run', () => {
    const store = useTourStore()
    store.checkFirstRun()
    expect(store.isActive).toBe(true)
  })

  it('hides tour after completion', () => {
    const store = useTourStore()
    store.start()
    store.finish()
    expect(store.isActive).toBe(false)
    expect(localStorage.getItem('vllm-mlx-ui-tour-completed')).toBe('true')
  })

  it('navigates through steps', () => {
    const store = useTourStore()
    store.start()
    expect(store.currentStep).toBe(0)
    store.next()
    expect(store.currentStep).toBe(1)
  })

  it('finishes tour at last step', () => {
    const store = useTourStore()
    store.start()
    store.currentStep = 3
    store.next()
    expect(store.isActive).toBe(false)
  })
})
