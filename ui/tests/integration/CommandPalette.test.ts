import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommandPaletteStore } from '@/stores/commandPalette'

describe('CommandPaletteStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('opens with toggle', () => {
    const store = useCommandPaletteStore()
    expect(store.isOpen).toBe(false)
    store.toggle()
    expect(store.isOpen).toBe(true)
  })

  it('closes on close()', () => {
    const store = useCommandPaletteStore()
    store.open()
    expect(store.isOpen).toBe(true)
    store.close()
    expect(store.isOpen).toBe(false)
  })

  it('filters commands based on query', () => {
    const store = useCommandPaletteStore()
    store.open()
    store.query = 'serve'
    expect(store.filteredCommands.length).toBeGreaterThan(0)
    expect(store.filteredCommands[0].label.toLowerCase()).toContain('serve')
  })

  it('resets query on close', () => {
    const store = useCommandPaletteStore()
    store.open()
    store.query = 'test'
    store.close()
    expect(store.query).toBe('')
  })
})
