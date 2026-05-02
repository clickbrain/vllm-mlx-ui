import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useServerStore } from './server'
import { useModelsStore } from './models'

export interface Command {
  id: string
  label: string
  icon?: string
  shortcut?: string
  action: () => void | Promise<void>
  category: 'nav' | 'server' | 'models' | 'general'
}

export const useCommandPaletteStore = defineStore('commandPalette', () => {
  const router = useRouter()
  const serverStore = useServerStore()
  const modelsStore = useModelsStore()

  const isOpen = ref(false)
  const query = ref('')
  const selectedIndex = ref(0)

  const commands = computed<Command[]>(() => [
    // Navigation
    {
      id: 'nav-serve',
      label: 'Go to Serve',
      icon: '⚡',
      shortcut: '1',
      category: 'nav',
      action: () => router.push('/serve')
    },
    {
      id: 'nav-models',
      label: 'Go to Models',
      icon: '📦',
      shortcut: '2',
      category: 'nav',
      action: () => router.push('/models')
    },
    {
      id: 'nav-benchmarks',
      label: 'Go to Benchmarks',
      icon: '📊',
      shortcut: '3',
      category: 'nav',
      action: () => router.push('/benchmarks')
    },
    {
      id: 'nav-chat',
      label: 'Go to Chat',
      icon: '💬',
      shortcut: '4',
      category: 'nav',
      action: () => router.push('/chat')
    },
    {
      id: 'nav-settings',
      label: 'Go to Settings',
      icon: '⚙️',
      shortcut: '5',
      category: 'nav',
      action: () => router.push('/settings')
    },
    // Server actions
    {
      id: 'server-start',
      label: serverStore.isRunning ? 'Restart Server' : 'Start Server',
      icon: '▶️',
      category: 'server',
      action: () => serverStore.toggleServer()
    },
    {
      id: 'server-stop',
      label: 'Stop Server',
      icon: '⏹️',
      category: 'server',
      action: () => serverStore.stopServer(),
      shortcut: 'Mod+Shift+S'
    },
    // Models
    {
      id: 'models-refresh',
      label: 'Refresh Models',
      icon: '🔄',
      category: 'models',
      action: () => modelsStore.fetchModels()
    },
    // General
    {
      id: 'general-theme',
      label: 'Toggle Theme',
      icon: '🌓',
      category: 'general',
      action: () => {
        const html = document.documentElement
        html.classList.toggle('dark')
        localStorage.setItem('theme', html.classList.contains('dark') ? 'dark' : 'light')
      }
    }
  ])

  const filteredCommands = computed(() => {
    if (!query.value) return commands.value
    const q = query.value.toLowerCase()
    return commands.value.filter(c =>
      c.label.toLowerCase().includes(q) ||
      c.category.toLowerCase().includes(q)
    )
  })

  function open() {
    isOpen.value = true
    query.value = ''
    selectedIndex.value = 0
  }

  function close() {
    isOpen.value = false
    query.value = ''
  }

  function toggle() {
    isOpen.value ? close() : open()
  }

  function execute(command: Command) {
    close()
    command.action()
  }

  function onKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      toggle()
      return
    }
    if (!isOpen.value) return
    if (e.key === 'Escape') { close(); e.preventDefault() }
    if (e.key === 'ArrowDown') { selectedIndex.value = Math.min(selectedIndex.value + 1, filteredCommands.value.length - 1); e.preventDefault() }
    if (e.key === 'ArrowUp') { selectedIndex.value = Math.max(selectedIndex.value - 1, 0); e.preventDefault() }
    if (e.key === 'Enter') { execute(filteredCommands.value[selectedIndex.value]); e.preventDefault() }
  }

  return { isOpen, query, selectedIndex, commands, filteredCommands, open, close, toggle, execute, onKeydown }
})
