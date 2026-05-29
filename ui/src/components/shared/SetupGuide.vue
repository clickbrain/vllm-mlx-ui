<!--
  SetupGuide — guided first-run onboarding for new vmUI installs.

  Shown when no engine is installed (or vllm-mlx is not installed).
  Walks the user through:
    Step 1: Welcome + hardware detection
    Step 2: Install vllm-mlx (auto) + discover other engines
    Step 3: Download a model (hardware-fitted recommendations)
    Step 4: Configure the server (optional, skippable)
    Step 5: Start the server

  Design: accordion-style steps. Active step is expanded; completed steps
  show a ✓ check and are collapsed. Every step teaches the concept before
  asking the user to act.
-->
<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useServerStore } from '@/stores/server'
import { api, getBase, getMgmtApiKey } from '@/api/client'

const router = useRouter()
const serverStore = useServerStore()

// ── Hardware ──────────────────────────────────────────────────────────────────
interface HardwareInfo { chip: string; ram_gb: number }
const hardware = ref<HardwareInfo | null>(null)

async function fetchHardware() {
  try {
    // /hardware is public — no auth required
    const base = import.meta.env.DEV ? '/api' : ''
    const res = await fetch(`${base}/hardware`)
    if (res.ok) hardware.value = await res.json()
  } catch { /* non-critical */ }
}

// ── RAM-tier model recommendations ───────────────────────────────────────────
interface ModelRec {
  id: string
  name: string
  ramGb: number
  quant: string
  speedHint: string
  useCases: string[]
  desc: string
}

const modelRecs = computed<ModelRec[]>(() => {
  const gb = hardware.value?.ram_gb ?? 16
  const chip = hardware.value?.chip ?? ''
  const isM4Plus = /M[4-9]|M[1-9][0-9]/.test(chip)
  const speedMultiplier = isM4Plus ? 1.2 : 1.0

  const allRecs: ModelRec[] = [
    {
      id: 'mlx-community/Qwen3-1.7B-8bit',
      name: 'Qwen3 1.7B · 8-bit',
      ramGb: 3,
      quant: '8-bit',
      speedHint: `~${Math.round(200 * speedMultiplier)} tok/s`,
      useCases: ['Chat', 'Q&A', 'Quick tasks'],
      desc: 'The smallest capable model. Instant responses, minimal RAM.',
    },
    {
      id: 'mlx-community/Qwen3-4B-8bit',
      name: 'Qwen3 4B · 8-bit',
      ramGb: 5,
      quant: '8-bit',
      speedHint: `~${Math.round(150 * speedMultiplier)} tok/s`,
      useCases: ['Chat', 'Coding', 'Summarization'],
      desc: 'Fast and capable. Great everyday assistant.',
    },
    {
      id: 'mlx-community/Qwen3-8B-8bit',
      name: 'Qwen3 8B · 8-bit',
      ramGb: 10,
      quant: '8-bit',
      speedHint: `~${Math.round(110 * speedMultiplier)} tok/s`,
      useCases: ['Chat', 'Coding', 'Reasoning'],
      desc: 'Strong reasoning and coding at high speed.',
    },
    {
      id: 'mlx-community/Qwen3-14B-8bit',
      name: 'Qwen3 14B · 8-bit',
      ramGb: 16,
      quant: '8-bit',
      speedHint: `~${Math.round(75 * speedMultiplier)} tok/s`,
      useCases: ['Chat', 'Coding', 'Reasoning', 'Q&A'],
      desc: 'Excellent everyday assistant. Near-full quality.',
    },
    {
      id: 'mlx-community/Qwen3-30B-A3B-4bit',
      name: 'Qwen3 30B MoE · 4-bit',
      ramGb: 24,
      quant: '4-bit',
      speedHint: `~${Math.round(90 * speedMultiplier)} tok/s`,
      useCases: ['Coding', 'Reasoning', 'Long context'],
      desc: 'Mixture-of-experts — fast like a small model, smart like a large one.',
    },
    {
      id: 'mlx-community/Qwen3-32B-4bit',
      name: 'Qwen3 32B · 4-bit',
      ramGb: 22,
      quant: '4-bit',
      speedHint: `~${Math.round(60 * speedMultiplier)} tok/s`,
      useCases: ['Chat', 'Coding', 'Reasoning'],
      desc: 'More capable than 14B with a modest RAM tradeoff.',
    },
    {
      id: 'mlx-community/Llama-3.3-70B-Instruct-4bit',
      name: 'Llama 3.3 70B · 4-bit',
      ramGb: 43,
      quant: '4-bit',
      speedHint: `~${Math.round(35 * speedMultiplier)} tok/s`,
      useCases: ['Research', 'Writing', 'Complex reasoning'],
      desc: 'Near-frontier quality. The largest open model most Macs can run.',
    },
    {
      id: 'mlx-community/Qwen3-235B-A22B-4bit',
      name: 'Qwen3 235B MoE · 4-bit',
      ramGb: 140,
      quant: '4-bit',
      speedHint: `~${Math.round(45 * speedMultiplier)} tok/s`,
      useCases: ['Research', 'Writing', 'Expert tasks'],
      desc: 'Frontier-grade open model. Only for the highest-RAM machines.',
    },
  ]

  // Show 3 recommendations that fit in their RAM (with 4 GB headroom for OS)
  const maxRam = gb - 4
  const fits = allRecs.filter(m => m.ramGb <= maxRam)
  // Pick variety: small / medium / large
  if (fits.length >= 3) {
    const sorted = [...fits].sort((a, b) => a.ramGb - b.ramGb)
    const small = sorted[0]
    const large = sorted[sorted.length - 1]
    // Pick a "medium" between them
    const mid = sorted[Math.floor((sorted.length - 1) / 2)]
    const seen = new Set([small.id, mid.id, large.id])
    return [small.id === mid.id ? sorted[1] ?? mid : small, mid, large].filter(
      (m, i, arr) => arr.findIndex(x => x.id === m.id) === i
    ).slice(0, 3)
  }
  return fits.slice(-3)
})

// ── Step state ────────────────────────────────────────────────────────────────
type StepId = 'welcome' | 'engine' | 'model' | 'config' | 'start'
const currentStep = ref<StepId>('welcome')
const completedSteps = ref(new Set<StepId>())

function isCompleted(id: StepId) { return completedSteps.value.has(id) }
function isActive(id: StepId) { return currentStep.value === id }
function goTo(id: StepId) { currentStep.value = id }

function completeStep(id: StepId, next: StepId) {
  completedSteps.value.add(id)
  currentStep.value = next
  nextTick(() => {
    const el = document.getElementById(`step-${next}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

// ── Step 2: Engine install ────────────────────────────────────────────────────
interface EngineInfo {
  id: string
  name: string
  description: string
  installed: boolean
  install_method: string
}

const allEngines = ref<EngineInfo[]>([])
const vllmInstalling = ref(false)
const vllmInstallLog = ref('')
const vllmInstalled = ref(false)
const vllmInstallError = ref('')
const installingOtherId = ref<string | null>(null)
const otherInstallLogs = ref<Record<string, string>>({})

const otherEngines = computed(() =>
  allEngines.value.filter(e => e.id !== 'vllm-mlx' && e.id !== 'rapid-mlx')
)

async function loadEngines() {
  try {
    const r = await api.get<{ engines: EngineInfo[] }>('/engines')
    allEngines.value = r.engines
    const vllm = r.engines.find(e => e.id === 'vllm-mlx')
    if (vllm?.installed) vllmInstalled.value = true
  } catch { /* non-critical */ }
}

async function installVllmMlx() {
  vllmInstalling.value = true
  vllmInstallLog.value = 'Starting installation…\n'
  vllmInstallError.value = ''
  try {
    const base = import.meta.env.DEV ? '/api' : ''
    const headers: Record<string, string> = getMgmtApiKey() ? { 'X-Api-Key': getMgmtApiKey() } : {}
    const resp = await fetch(`${base}/engines/vllm-mlx/install`, { method: 'POST', headers })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      vllmInstallError.value = err.detail ?? `Install failed (HTTP ${resp.status})`
      return
    }
    if (!resp.body) throw new Error('No response body')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      if (value) vllmInstallLog.value += decoder.decode(value)
    }
    vllmInstalled.value = true
    await loadEngines()
  } catch (e: any) {
    vllmInstallError.value = e?.message ?? 'Install failed'
  } finally {
    vllmInstalling.value = false
  }
}

async function installOtherEngine(id: string) {
  installingOtherId.value = id
  otherInstallLogs.value[id] = 'Starting installation…\n'
  try {
    const base = import.meta.env.DEV ? '/api' : ''
    const headers: Record<string, string> = getMgmtApiKey() ? { 'X-Api-Key': getMgmtApiKey() } : {}
    const resp = await fetch(`${base}/engines/${id}/install`, { method: 'POST', headers })
    if (!resp.ok) return
    if (!resp.body) return
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      if (value) otherInstallLogs.value[id] = (otherInstallLogs.value[id] ?? '') + decoder.decode(value)
    }
    await loadEngines()
  } catch (e: any) {
    otherInstallLogs.value[id] = (otherInstallLogs.value[id] ?? '') + `\nError: ${e?.message}`
  } finally {
    installingOtherId.value = null
  }
}

// ── Step 3: Model download ────────────────────────────────────────────────────
const downloadingModel = ref<string | null>(null)
const downloadProgress = ref<Record<string, number>>({})
const downloadDone = ref<Set<string>>(new Set())
const selectedModel = ref('')

async function downloadModel(modelId: string) {
  downloadingModel.value = modelId
  downloadProgress.value[modelId] = 0
  try {
    await api.post('/models/download', { model_id: modelId })
    // Poll download progress
    const poll = setInterval(async () => {
      try {
        const queue = await api.get<any[]>('/models/download/queue')
        const entry = queue.find((q: any) => q.model_id === modelId)
        if (entry) {
          downloadProgress.value[modelId] = entry.progress ?? 0
          if (entry.status === 'done') {
            clearInterval(poll)
            downloadDone.value.add(modelId)
            downloadingModel.value = null
            selectedModel.value = modelId
            // Save to config
            await api.post('/config', { model: modelId })
          } else if (entry.status === 'error') {
            clearInterval(poll)
            downloadingModel.value = null
          }
        } else {
          // Not in queue — assume done
          clearInterval(poll)
          downloadDone.value.add(modelId)
          downloadingModel.value = null
          selectedModel.value = modelId
          await api.post('/config', { model: modelId })
        }
      } catch { clearInterval(poll) }
    }, 1000)
  } catch {
    downloadingModel.value = null
  }
}

function useExistingModel() {
  // Skip to config step, model already set in store
  selectedModel.value = serverStore.modelId ?? ''
  completeStep('model', 'config')
}

// ── Step 4: Config ────────────────────────────────────────────────────────────
const configPort = ref(8000)
const configContextWindow = ref(32768)
const configHost = ref('127.0.0.1')
const configThinking = ref(true)
const configLoading = ref(false)

async function loadConfig() {
  try {
    const cfg = await api.get<Record<string, any>>('/config')
    configPort.value = cfg.port ?? 8000
    configContextWindow.value = cfg.max_seq_len ?? 32768
    configHost.value = cfg.host ?? '127.0.0.1'
    configThinking.value = cfg.enable_thinking !== false
  } catch { /* use defaults */ }
}

async function saveConfig() {
  configLoading.value = true
  try {
    await api.post('/config', {
      port: configPort.value,
      max_seq_len: configContextWindow.value,
      host: configHost.value,
      enable_thinking: configThinking.value,
    })
    completeStep('config', 'start')
  } catch { /* non-critical */ }
  finally { configLoading.value = false }
}

function skipConfig() {
  completeStep('config', 'start')
}

// ── Step 5: Start ─────────────────────────────────────────────────────────────
const starting = ref(false)
const startError = ref('')

async function startServer() {
  starting.value = true
  startError.value = ''
  try {
    await serverStore.startServer()
    // Mark setup done so it won't show again
    localStorage.setItem('vmui_setup_complete', '1')
    emit('complete')
  } catch (e: any) {
    startError.value = e?.message ?? 'Failed to start server'
  } finally {
    starting.value = false
  }
}

// ── RAM bar helper ────────────────────────────────────────────────────────────
function ramBarWidth(ramGb: number): string {
  const total = hardware.value?.ram_gb ?? 16
  return `${Math.min(100, (ramGb / total) * 100).toFixed(1)}%`
}

const emit = defineEmits<{ complete: [] }>()

onMounted(async () => {
  await fetchHardware()
  await loadEngines()
  await loadConfig()
})
</script>

<template>
  <div class="sg-wrap">
    <!-- Hardware context bar (always visible) -->
    <div v-if="hardware" class="sg-hw-bar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>
      <span>{{ hardware.chip }}</span>
      <span class="sg-hw-sep">·</span>
      <span>{{ hardware.ram_gb }} GB unified memory</span>
    </div>

    <div class="sg-steps">

      <!-- ── Step 1: Welcome ──────────────────────────────────────────────── -->
      <div :id="`step-welcome`" class="sg-step" :class="{ 'is-active': isActive('welcome'), 'is-done': isCompleted('welcome') }">
        <div class="sg-step-header" @click="!isCompleted('welcome') || goTo('welcome')">
          <div class="sg-step-num">
            <span v-if="isCompleted('welcome')" class="sg-check">✓</span>
            <span v-else>1</span>
          </div>
          <div class="sg-step-title-row">
            <span class="sg-step-title">Welcome to vmUI</span>
            <span v-if="isCompleted('welcome')" class="sg-step-summary">Ready to configure</span>
          </div>
        </div>

        <div v-if="isActive('welcome')" class="sg-step-body">
          <p class="sg-body-text">
            vmUI is a local AI inference dashboard. You run AI models
            directly on your Mac — no API keys, no cloud, no data leaving
            your machine.
          </p>
          <p class="sg-body-text">
            This guide will walk you through installing the inference engine,
            downloading a model that fits your hardware, and starting your
            first AI server — all in about 5 minutes.
          </p>

          <div v-if="hardware" class="sg-hw-card">
            <div class="sg-hw-line">
              <span class="sg-hw-label">Your chip</span>
              <span class="sg-hw-value">{{ hardware.chip }}</span>
            </div>
            <div class="sg-hw-line">
              <span class="sg-hw-label">Unified memory</span>
              <span class="sg-hw-value">{{ hardware.ram_gb }} GB</span>
            </div>
            <div class="sg-hw-note">
              <template v-if="hardware.ram_gb >= 96">
                Excellent. You can run the largest open models at full quality — or multiple models simultaneously.
              </template>
              <template v-else-if="hardware.ram_gb >= 36">
                Great. You can run large, capable models including 70B-class models at 4-bit quantization.
              </template>
              <template v-else-if="hardware.ram_gb >= 16">
                Good. You can run solid 14B–30B models at high quality.
              </template>
              <template v-else>
                You can run capable small models (up to ~7B) at full quality.
              </template>
            </div>
          </div>

          <button class="sg-btn-primary" @click="completeStep('welcome', 'engine')">
            Let's go →
          </button>
        </div>
      </div>

      <!-- ── Step 2: Inference Engine ─────────────────────────────────────── -->
      <div :id="`step-engine`" class="sg-step" :class="{ 'is-active': isActive('engine'), 'is-done': isCompleted('engine') }">
        <div class="sg-step-header" @click="isCompleted('engine') && goTo('engine')">
          <div class="sg-step-num">
            <span v-if="isCompleted('engine')" class="sg-check">✓</span>
            <span v-else>2</span>
          </div>
          <div class="sg-step-title-row">
            <span class="sg-step-title">Inference Engine</span>
            <span v-if="isCompleted('engine')" class="sg-step-summary">vllm-mlx installed</span>
          </div>
        </div>

        <div v-if="isActive('engine')" class="sg-step-body">
          <div class="sg-concept-box">
            <div class="sg-concept-label">What is an inference engine?</div>
            <p class="sg-concept-text">
              An inference engine is the runtime that loads an AI model into your
              Mac's memory and turns it into a live HTTP API. It handles streaming
              responses, context windows, and all the OpenAI-compatible endpoints
              that apps like Cursor, Claude Desktop, or your own code connect to.
            </p>
          </div>

          <p class="sg-body-text" style="margin-top: var(--space-4)">
            For Apple Silicon, the built-in engine is <strong>vllm-mlx</strong> — built on
            Apple's MLX framework, optimised for the unified memory architecture of
            your {{ hardware?.chip ?? 'Mac' }}. It supports paged KV cache, continuous
            batching, tool calls, vision, and audio.
          </p>

          <!-- Install vllm-mlx -->
          <div class="sg-engine-primary">
            <div class="sg-engine-row">
              <div class="sg-engine-info">
                <span class="sg-engine-name">vllm-mlx</span>
                <span v-if="vllmInstalled" class="sg-badge sg-badge-ok">✓ installed</span>
                <span v-else class="sg-badge sg-badge-pending">not installed</span>
              </div>
              <button
                v-if="!vllmInstalled && !vllmInstalling"
                class="sg-btn-primary"
                @click="installVllmMlx"
              >
                Install vllm-mlx
              </button>
              <span v-if="vllmInstalling" class="sg-installing-spinner">Installing…</span>
            </div>

            <div v-if="vllmInstallLog" class="sg-log">
              <pre>{{ vllmInstallLog }}</pre>
            </div>
            <div v-if="vllmInstallError" class="sg-error">{{ vllmInstallError }}</div>
          </div>

          <!-- Other engines (shown after vllm installed) -->
          <div v-if="vllmInstalled && otherEngines.length" class="sg-other-engines">
            <div class="sg-other-engines-title">Other Engines (Optional)</div>
            <p class="sg-other-engines-desc">
              vmUI also supports other inference runtimes. Useful if you want
              specific models or workflows only they support.
            </p>

            <div v-for="eng in otherEngines" :key="eng.id" class="sg-other-engine-card">
              <div class="sg-other-engine-row">
                <div class="sg-other-engine-info">
                  <span class="sg-engine-name">{{ eng.name }}</span>
                  <span v-if="eng.installed" class="sg-badge sg-badge-ok">✓ detected</span>
                  <span v-else class="sg-badge sg-badge-muted">not installed</span>
                </div>
                <button
                  v-if="!eng.installed && installingOtherId !== eng.id"
                  class="sg-btn-ghost-sm"
                  @click="installOtherEngine(eng.id)"
                >
                  Install
                </button>
                <span v-if="installingOtherId === eng.id" class="sg-installing-spinner" style="font-size:var(--text-xs)">Installing…</span>
              </div>
              <div class="sg-other-engine-desc">{{ eng.description.split('.')[0] }}.</div>
              <div v-if="otherInstallLogs[eng.id]" class="sg-log sg-log-sm">
                <pre>{{ otherInstallLogs[eng.id] }}</pre>
              </div>
            </div>
          </div>

          <button
            v-if="vllmInstalled"
            class="sg-btn-primary"
            style="margin-top: var(--space-4)"
            @click="completeStep('engine', 'model')"
          >
            Continue →
          </button>
        </div>
      </div>

      <!-- ── Step 3: Model ─────────────────────────────────────────────────── -->
      <div :id="`step-model`" class="sg-step" :class="{ 'is-active': isActive('model'), 'is-done': isCompleted('model') }">
        <div class="sg-step-header" @click="isCompleted('model') && goTo('model')">
          <div class="sg-step-num">
            <span v-if="isCompleted('model')" class="sg-check">✓</span>
            <span v-else>3</span>
          </div>
          <div class="sg-step-title-row">
            <span class="sg-step-title">AI Model</span>
            <span v-if="isCompleted('model')" class="sg-step-summary">{{ selectedModel.split('/').pop() }}</span>
          </div>
        </div>

        <div v-if="isActive('model')" class="sg-step-body">
          <div class="sg-concept-box">
            <div class="sg-concept-label">What is a model?</div>
            <p class="sg-concept-text">
              A model is the AI brain — a file of billions of numerical weights
              that determines how the AI thinks, reasons, and responds. Models
              come in different sizes and precisions.
            </p>
            <div class="sg-concept-grid">
              <div class="sg-concept-term">
                <span class="sg-concept-term-name">Parameters</span>
                The model's total knowledge capacity. Larger models generally
                give better, more nuanced answers — but require more RAM to run.
              </div>
              <div class="sg-concept-term">
                <span class="sg-concept-term-name">Quantization</span>
                How precisely the weights are stored. 8-bit is near-full quality.
                4-bit uses half the memory with ~5–10% accuracy loss.
                Q4 at 70B is often better than Q8 at 14B.
              </div>
            </div>
          </div>

          <div class="sg-model-header">
            <span>Models that fit your {{ hardware?.ram_gb ?? '?' }} GB Mac</span>
          </div>

          <div class="sg-model-cards">
            <div
              v-for="m in modelRecs"
              :key="m.id"
              class="sg-model-card"
              :class="{ 'is-downloading': downloadingModel === m.id, 'is-done': downloadDone.has(m.id) }"
            >
              <div class="sg-model-card-header">
                <div class="sg-model-name">{{ m.name }}</div>
                <div class="sg-model-speed">{{ m.speedHint }}</div>
              </div>
              <div class="sg-model-desc">{{ m.desc }}</div>

              <!-- RAM bar -->
              <div class="sg-ram-bar-wrap">
                <div class="sg-ram-bar">
                  <div class="sg-ram-bar-fill" :style="{ width: ramBarWidth(m.ramGb) }" />
                </div>
                <span class="sg-ram-label">{{ m.ramGb }} GB / {{ hardware?.ram_gb ?? '?' }} GB</span>
              </div>

              <div class="sg-model-tags">
                <span v-for="tag in m.useCases" :key="tag" class="sg-tag">{{ tag }}</span>
              </div>

              <div class="sg-model-actions">
                <template v-if="downloadDone.has(m.id)">
                  <span class="sg-badge sg-badge-ok">✓ Downloaded</span>
                  <button class="sg-btn-primary" @click="completeStep('model', 'config')">
                    Use this model →
                  </button>
                </template>
                <template v-else-if="downloadingModel === m.id">
                  <div class="sg-download-progress-wrap">
                    <div class="sg-download-progress-bar">
                      <div class="sg-download-progress-fill" :style="{ width: `${downloadProgress[m.id] ?? 0}%` }" />
                    </div>
                    <span class="sg-download-pct">{{ Math.round(downloadProgress[m.id] ?? 0) }}%</span>
                  </div>
                </template>
                <template v-else>
                  <button
                    class="sg-btn-primary"
                    :disabled="downloadingModel !== null"
                    @click="downloadModel(m.id)"
                  >
                    ↓ Download {{ m.ramGb }} GB
                  </button>
                </template>
              </div>
            </div>
          </div>

          <div class="sg-model-alt">
            <RouterLink to="/models" class="sg-link">Browse all models →</RouterLink>
            <span class="sg-sep">·</span>
            <button
              v-if="serverStore.modelId"
              class="sg-link-btn"
              @click="useExistingModel"
            >
              I already have a model configured
            </button>
          </div>
        </div>
      </div>

      <!-- ── Step 4: Config ─────────────────────────────────────────────────── -->
      <div :id="`step-config`" class="sg-step" :class="{ 'is-active': isActive('config'), 'is-done': isCompleted('config') }">
        <div class="sg-step-header" @click="isCompleted('config') && goTo('config')">
          <div class="sg-step-num">
            <span v-if="isCompleted('config')" class="sg-check">✓</span>
            <span v-else>4</span>
          </div>
          <div class="sg-step-title-row">
            <span class="sg-step-title">Server Configuration</span>
            <span v-if="isCompleted('config')" class="sg-step-summary">Port {{ configPort }} · {{ configContextWindow.toLocaleString() }} ctx</span>
          </div>
        </div>

        <div v-if="isActive('config')" class="sg-step-body">
          <div class="sg-concept-box">
            <div class="sg-concept-label">What is the inference server?</div>
            <p class="sg-concept-text">
              The inference server is an HTTP API on your Mac that apps connect
              to — it speaks the OpenAI API format, so Cursor, Claude Desktop,
              or any Python/JS script that works with OpenAI can use it locally.
            </p>
          </div>

          <div class="sg-config-fields">
            <div class="sg-config-field">
              <label class="sg-config-label">
                Inference Port
                <span class="sg-config-hint">Apps connect at http://127.0.0.1:{{ configPort }}/v1</span>
              </label>
              <input v-model.number="configPort" type="number" class="sg-input" min="1024" max="65535" />
            </div>

            <div class="sg-config-field">
              <label class="sg-config-label">
                Context Window
                <span class="sg-config-hint">How much conversation history the model reads at once. Larger = more RAM used.</span>
              </label>
              <select v-model.number="configContextWindow" class="sg-input">
                <option :value="8192">8,192 tokens (~6,000 words)</option>
                <option :value="16384">16,384 tokens (~12,000 words)</option>
                <option :value="32768">32,768 tokens (~24,000 words) — default</option>
                <option :value="65536">65,536 tokens (~48,000 words)</option>
                <option :value="131072">131,072 tokens (~96,000 words)</option>
              </select>
            </div>

            <div class="sg-config-field">
              <label class="sg-config-label">
                Bind Address
                <span class="sg-config-hint">127.0.0.1 = local only (secure). 0.0.0.0 = accessible on your network.</span>
              </label>
              <select v-model="configHost" class="sg-input">
                <option value="127.0.0.1">127.0.0.1 — local only (recommended)</option>
                <option value="0.0.0.0">0.0.0.0 — share on network</option>
              </select>
            </div>

            <div class="sg-config-field">
              <label class="sg-config-label">
                Thinking Mode
                <span class="sg-config-hint">Qwen3 models can show reasoning steps. Off = faster, more direct responses.</span>
              </label>
              <select v-model="configThinking" class="sg-input">
                <option :value="true">On — show reasoning steps</option>
                <option :value="false">Off — direct responses</option>
              </select>
            </div>
          </div>

          <div class="sg-config-actions">
            <button class="sg-btn-primary" :disabled="configLoading" @click="saveConfig">
              {{ configLoading ? 'Saving…' : 'Save & Continue →' }}
            </button>
            <button class="sg-btn-ghost" @click="skipConfig">Use defaults</button>
          </div>
        </div>
      </div>

      <!-- ── Step 5: Start ──────────────────────────────────────────────────── -->
      <div :id="`step-start`" class="sg-step" :class="{ 'is-active': isActive('start'), 'is-done': isCompleted('start') }">
        <div class="sg-step-header">
          <div class="sg-step-num">
            <span v-if="isCompleted('start')" class="sg-check">✓</span>
            <span v-else>5</span>
          </div>
          <div class="sg-step-title-row">
            <span class="sg-step-title">Start Serving</span>
          </div>
        </div>

        <div v-if="isActive('start')" class="sg-step-body">
          <div class="sg-summary-card">
            <div class="sg-summary-row">
              <span class="sg-summary-label">Engine</span>
              <span class="sg-summary-value">vllm-mlx</span>
            </div>
            <div class="sg-summary-row">
              <span class="sg-summary-label">Model</span>
              <span class="sg-summary-value">{{ (selectedModel || serverStore.modelId || '').split('/').pop() }}</span>
            </div>
            <div class="sg-summary-row">
              <span class="sg-summary-label">Endpoint</span>
              <span class="sg-summary-value sg-mono">http://{{ configHost }}:{{ configPort }}/v1</span>
            </div>
          </div>

          <div class="sg-what-next">
            <div class="sg-what-next-title">What you can do once it's running</div>
            <div class="sg-feature-grid">
              <div class="sg-feature-item">
                <span class="sg-feature-icon">💬</span>
                <div>
                  <div class="sg-feature-name">Chat</div>
                  <div class="sg-feature-desc">Chat with your model right here in the browser</div>
                </div>
              </div>
              <div class="sg-feature-item">
                <span class="sg-feature-icon">📊</span>
                <div>
                  <div class="sg-feature-name">Benchmark</div>
                  <div class="sg-feature-desc">Measure real tokens/s and compare models</div>
                </div>
              </div>
              <div class="sg-feature-item">
                <span class="sg-feature-icon">🔍</span>
                <div>
                  <div class="sg-feature-name">Find Models</div>
                  <div class="sg-feature-desc">Browse and download from 12,000+ HuggingFace models</div>
                </div>
              </div>
              <div class="sg-feature-item">
                <span class="sg-feature-icon">🌐</span>
                <div>
                  <div class="sg-feature-name">Connect Apps</div>
                  <div class="sg-feature-desc">Point any OpenAI client at your local endpoint</div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="startError" class="sg-error">{{ startError }}</div>

          <button class="sg-btn-start" :disabled="starting" @click="startServer">
            <span v-if="starting">Starting…</span>
            <span v-else>▶ Start Inference Server</span>
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.sg-wrap {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-2) 0 var(--space-10);
}

/* Hardware context bar */
.sg-hw-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  font-size: var(--text-xs);
  color: var(--tx-secondary);
  margin-bottom: var(--space-6);
}

.sg-hw-sep { color: var(--tx-muted); }

/* Steps container */
.sg-steps {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* Individual step */
.sg-step {
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-lg);
  overflow: hidden;
  transition: border-color 0.15s;
}

.sg-step.is-active {
  border-color: var(--border-default);
}

.sg-step.is-done {
  border-color: var(--border-subtle);
  opacity: 0.85;
}

.sg-step-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  cursor: pointer;
  user-select: none;
}

.sg-step.is-active .sg-step-header { cursor: default; }

.sg-step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--tx-secondary);
  flex-shrink: 0;
}

.sg-step.is-active .sg-step-num {
  border-color: var(--si-500, #5B6AD0);
  color: var(--si-500, #5B6AD0);
  background: rgba(91, 106, 208, 0.08);
}

.sg-check {
  color: var(--ph-500, #22C55E);
}

.sg-step-title-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex: 1;
}

.sg-step-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--tx-primary);
}

.sg-step-summary {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
}

/* Step body */
.sg-step-body {
  padding: 0 var(--space-5) var(--space-5);
  padding-left: calc(var(--space-5) + 28px + var(--space-3));
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sg-body-text {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Concept explanation box */
.sg-concept-box {
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sg-concept-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--tx-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sg-concept-text {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  line-height: 1.6;
  margin: 0;
}

.sg-concept-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.sg-concept-term {
  font-size: var(--text-xs);
  color: var(--tx-secondary);
  line-height: 1.55;
}

.sg-concept-term-name {
  display: block;
  font-weight: 600;
  color: var(--tx-primary);
  margin-bottom: 2px;
}

/* Hardware card in welcome */
.sg-hw-card {
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sg-hw-line {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-sm);
}

.sg-hw-label { color: var(--tx-tertiary); }
.sg-hw-value { color: var(--tx-primary); font-weight: 500; }

.sg-hw-note {
  font-size: var(--text-xs);
  color: var(--tx-secondary);
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-2);
  margin-top: var(--space-1);
  line-height: 1.5;
}

/* Engine install area */
.sg-engine-primary {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sg-engine-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.sg-engine-info { display: flex; align-items: center; gap: var(--space-2); }
.sg-engine-name { font-size: var(--text-sm); font-weight: 600; color: var(--tx-primary); }

.sg-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px var(--space-2);
  border-radius: var(--r-pill);
}

.sg-badge-ok { background: rgba(34, 197, 94, 0.12); color: var(--ph-500, #22C55E); }
.sg-badge-pending { background: var(--bg-inset); color: var(--tx-tertiary); border: 1px solid var(--border-subtle); }
.sg-badge-muted { background: var(--bg-inset); color: var(--tx-muted); border: 1px solid var(--border-subtle); }

.sg-log {
  background: var(--bg-canvas);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm);
  padding: var(--space-3);
  max-height: 200px;
  overflow-y: auto;
}

.sg-log pre {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--tx-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.sg-log-sm { max-height: 120px; margin-top: var(--space-2); }

.sg-error {
  font-size: var(--text-xs);
  color: var(--cr-500, #EF4444);
  padding: var(--space-2) var(--space-3);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--r-sm);
}

.sg-installing-spinner {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  font-style: italic;
}

/* Other engines */
.sg-other-engines {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.sg-other-engines-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--tx-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sg-other-engines-desc {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  line-height: 1.5;
}

.sg-other-engine-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sg-other-engine-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sg-other-engine-info { display: flex; align-items: center; gap: var(--space-2); }

.sg-other-engine-desc {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  line-height: 1.5;
}

/* Model cards */
.sg-model-header {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  font-weight: 500;
  padding-top: var(--space-2);
}

.sg-model-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sg-model-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sg-model-card.is-done {
  border-color: rgba(34, 197, 94, 0.3);
}

.sg-model-card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.sg-model-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-primary);
}

.sg-model-speed {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
}

.sg-model-desc {
  font-size: var(--text-xs);
  color: var(--tx-secondary);
  line-height: 1.5;
}

/* RAM bar */
.sg-ram-bar-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sg-ram-bar {
  flex: 1;
  height: 5px;
  background: var(--bg-inset);
  border-radius: var(--r-pill);
  overflow: hidden;
}

.sg-ram-bar-fill {
  height: 100%;
  background: var(--si-500, #5B6AD0);
  border-radius: var(--r-pill);
  transition: width 0.3s;
}

.sg-ram-label {
  font-size: 11px;
  color: var(--tx-muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* Tags */
.sg-model-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.sg-tag {
  font-size: 10px;
  padding: 2px var(--space-2);
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-pill);
  color: var(--tx-tertiary);
}

/* Download progress */
.sg-download-progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
}

.sg-download-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-inset);
  border-radius: var(--r-pill);
  overflow: hidden;
}

.sg-download-progress-fill {
  height: 100%;
  background: var(--si-500, #5B6AD0);
  border-radius: var(--r-pill);
  transition: width 0.5s;
}

.sg-download-pct {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  font-variant-numeric: tabular-nums;
  min-width: 34px;
  text-align: right;
}

.sg-model-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sg-model-alt {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  padding-top: var(--space-2);
}

.sg-sep { color: var(--border-default); }

.sg-link {
  color: var(--si-500, #5B6AD0);
  text-decoration: none;
}

.sg-link:hover { text-decoration: underline; }

.sg-link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  cursor: pointer;
  text-decoration: underline;
}

.sg-link-btn:hover { color: var(--tx-secondary); }

/* Config fields */
.sg-config-fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.sg-config-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.sg-config-label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--tx-primary);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sg-config-hint {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  font-weight: 400;
}

.sg-input {
  padding: var(--space-2) var(--space-3);
  background: var(--bg-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color 0.15s;
  max-width: 360px;
}

.sg-input:focus-visible {
  border-color: var(--si-500, #5B6AD0);
  box-shadow: 0 0 0 2px rgba(91, 106, 208, 0.2);
}

.sg-config-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

/* Summary card */
.sg-summary-card {
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sg-summary-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-4);
}

.sg-summary-label {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  min-width: 80px;
}

.sg-summary-value {
  font-size: var(--text-sm);
  color: var(--tx-primary);
  font-weight: 500;
}

.sg-mono { font-family: var(--font-mono); font-size: var(--text-xs); }

/* Feature grid */
.sg-what-next {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sg-what-next-title {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sg-feature-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.sg-feature-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
}

.sg-feature-icon { font-size: 18px; flex-shrink: 0; line-height: 1.4; }

.sg-feature-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--tx-primary);
  margin-bottom: 2px;
}

.sg-feature-desc {
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  line-height: 1.5;
}

/* Buttons */
.sg-btn-primary {
  padding: var(--space-2) var(--space-5);
  background: var(--si-500, #5B6AD0);
  color: #fff;
  border: none;
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}

.sg-btn-primary:hover:not(:disabled) { opacity: 0.88; }
.sg-btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }

.sg-btn-ghost {
  padding: var(--space-2) var(--space-4);
  background: transparent;
  color: var(--tx-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.sg-btn-ghost:hover { border-color: var(--border-emphasis); color: var(--tx-primary); }

.sg-btn-ghost-sm {
  padding: var(--space-1) var(--space-3);
  background: transparent;
  color: var(--tx-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: color 0.15s;
}

.sg-btn-ghost-sm:hover { color: var(--tx-primary); border-color: var(--border-default); }

.sg-btn-start {
  padding: var(--space-3) var(--space-8);
  background: var(--ph-500, #22C55E);
  color: #fff;
  border: none;
  border-radius: var(--r-md);
  font-size: var(--text-base);
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
  margin-top: var(--space-2);
}

.sg-btn-start:hover:not(:disabled) { opacity: 0.88; }
.sg-btn-start:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
