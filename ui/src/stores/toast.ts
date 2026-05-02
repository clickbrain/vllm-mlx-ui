// SPDX-License-Identifier: Apache-2.0
/**
 * Toast store — global notification system.
 *
 * Toasts are short-lived messages shown at the bottom-right of the viewport.
 * Types: 'info' (default), 'success', 'warning', 'error'.
 *
 * Usage:
 *   const toast = useToastStore()
 *   toast.add('Model loaded successfully', 'success')
 *   toast.add('Failed to connect', 'error')
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
  duration: number  // ms; 0 = persistent until dismissed
  _timerId?: ReturnType<typeof setTimeout>
}

let nextId = 0

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])

  function add(message: string, type: Toast['type'] = 'info', duration = 4000) {
    const id = ++nextId
    const toast: Toast = { id, message, type, duration }
    toasts.value.push(toast)
    if (duration > 0) {
      toast._timerId = setTimeout(() => remove(id), duration)
    }
    return id
  }

  function remove(id: number) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) {
      const t = toasts.value[idx]
      if (t._timerId) clearTimeout(t._timerId)
      toasts.value.splice(idx, 1)
    }
  }

  function clear() {
    for (const t of toasts.value) {
      if (t._timerId) clearTimeout(t._timerId)
    }
    toasts.value = []
  }

  function info(message: string, duration = 4000) { return add(message, 'info', duration) }
  function success(message: string, duration = 4000) { return add(message, 'success', duration) }
  function warning(message: string, duration = 5000) { return add(message, 'warning', duration) }
  function error(message: string, duration = 0) { return add(message, 'error', duration) }

  return { toasts, add, remove, clear, info, success, warning, error }
})
