import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Machine {
  id: string
  name: string
  host: string
  port: number
  type: 'local' | 'remote'
  online: boolean
  memoryGb: number
}

export const useMachinesStore = defineStore('machines', () => {
  const machines = ref<Machine[]>([
    { id: 'local', name: 'This Mac', host: 'localhost', port: 8502, type: 'local', online: true, memoryGb: 0 }
  ])
  const activeMachineId = ref('local')

  const activeMachine = (): Machine => machines.value.find(m => m.id === activeMachineId.value) ?? machines.value[0]

  function addMachine(m: Omit<Machine, 'id' | 'online'>) {
    machines.value.push({ ...m, id: crypto.randomUUID(), online: false })
  }

  function removeMachine(id: string) {
    machines.value = machines.value.filter(m => m.id !== id)
  }

  function setActive(id: string) {
    activeMachineId.value = id
  }

  return { machines, activeMachineId, activeMachine, addMachine, removeMachine, setActive }
})
