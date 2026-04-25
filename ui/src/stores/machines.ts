import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { api } from '@/api/client'

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

  async function pingMachine(machine: Machine): Promise<boolean> {
    try {
      const res = await fetch(`http://${machine.host}:${machine.port}/health`, {
        signal: AbortSignal.timeout(3000),
      })
      return res.ok
    } catch {
      return false
    }
  }

  async function refreshOnlineStatus() {
    for (const machine of machines.value) {
      if (machine.type === 'local') {
        machine.online = true
      } else {
        machine.online = await pingMachine(machine)
      }
    }
  }

  async function scanNetwork(): Promise<Machine[]> {
    const results = await api.get<{ ip: string; port: number; name: string }[]>('/network/scan')
    if (!results) return []
    const discovered: Machine[] = []
    for (const r of results) {
      const alreadyKnown = machines.value.some(
        m => m.host === r.ip && m.port === r.port
      )
      if (!alreadyKnown) {
        discovered.push({
          id: crypto.randomUUID(),
          name: r.name || r.ip,
          host: r.ip,
          port: r.port,
          type: 'remote',
          online: true,
          memoryGb: 0,
        })
      }
    }
    return discovered
  }

  return { machines, activeMachineId, activeMachine, addMachine, removeMachine, setActive, pingMachine, refreshOnlineStatus, scanNetwork }
})
