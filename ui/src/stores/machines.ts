import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface Machine {
  id: string
  name: string
  host: string
  port: number
  type: 'local' | 'remote'
  online: boolean
  memoryGb: number
}

const LS_KEY = 'vmui_machines'
const LS_ACTIVE_KEY = 'vmui_active_machine'

function loadMachines(): Machine[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Machine[]
      if (!parsed.find(m => m.id === 'local')) {
        parsed.unshift({ id: 'local', name: 'This Mac', host: 'localhost', port: 8502, type: 'local', online: true, memoryGb: 0 })
      }
      return parsed
    }
  } catch {}
  return [{ id: 'local', name: 'This Mac', host: 'localhost', port: 8502, type: 'local', online: true, memoryGb: 0 }]
}

export const useMachinesStore = defineStore('machines', () => {
  const machines = ref<Machine[]>(loadMachines())
  const activeMachineId = ref(localStorage.getItem(LS_ACTIVE_KEY) ?? 'local')

  watch(machines, (v) => localStorage.setItem(LS_KEY, JSON.stringify(v)), { deep: true })
  watch(activeMachineId, (v) => localStorage.setItem(LS_ACTIVE_KEY, v))

  const activeMachine = (): Machine => machines.value.find(m => m.id === activeMachineId.value) ?? machines.value[0]

  function addMachine(m: Omit<Machine, 'id' | 'online'>) {
    machines.value.push({ ...m, id: crypto.randomUUID(), online: false })
  }

  function removeMachine(id: string) {
    machines.value = machines.value.filter(m => m.id !== id)
    if (activeMachineId.value === id) activeMachineId.value = 'local'
  }

  function setActive(id: string) {
    activeMachineId.value = id
  }

  return { machines, activeMachineId, activeMachine, addMachine, removeMachine, setActive }
})
