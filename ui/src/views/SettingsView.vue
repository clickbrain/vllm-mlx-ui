<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useMachinesStore } from '@/stores/machines'
import type { Machine } from '@/stores/machines'
import { useServerStore } from '@/stores/server'
import { useUpdatesStore } from '@/stores/updates'
import AppButton from '@/components/shared/AppButton.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import { api } from '@/api/client'

const machinesStore = useMachinesStore()
const serverStore = useServerStore()
const updatesStore = useUpdatesStore()

const showAddForm = ref(false)
const form = reactive({ name: '', host: '', port: 8502, type: 'remote' as 'remote' | 'local' })
const formError = ref('')
const confirmRemove = ref<Machine | null>(null)

const diskUsedGb = ref<number | null>(null)
const editCachePath = ref(false)
const cachePathInput = ref('~/.cache/huggingface/hub')
const savedCachePath = ref('~/.cache/huggingface/hub')

// Startup behavior
const startupBehavior = ref<'auto' | 'ask' | 'none'>('auto')

// Network & Access
const listenAllInterfaces = ref(false)
const inferenceApiKey = ref('')
const hfToken = ref(localStorage.getItem('vmui_hf_token') ?? '')
const offlineMode = ref(false)
const autoModelSwitch = ref(false)

// Advanced Inference Settings
const trustRemoteCode = ref(false)
const gpuMemoryUtil = ref(0.90)
const kvCacheQuantization = ref(false)
const kvCacheQuantizationBits = ref(8)
const usePaged = ref(false)
const ssdCacheDir = ref('')
const ssdCacheMaxGb = ref(0)
const continuousBatching = ref(false)
const enableMtp = ref(false)
const mtpDraftTokens = ref(1)
const prefillStepSize = ref(0)
const enableMetrics = ref(false)
const rateLimit = ref(0)
const rerankModel = ref('')
const warmPrompts = ref('')
const advancedSaved = ref(false)

// Preferences
const openBrowserOnStart = ref(localStorage.getItem('vmui_open_browser') !== 'false')

// Maintenance
const showRestartConfirm = ref(false)
const restarting = ref(false)
const restartCountdown = ref(0)
let restartTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  try {
    const cfg = await api.get<{
      model_cache_dir?: string
      startup_model_behavior?: string
      host?: string
      api_key?: string
      offline?: boolean
      auto_model_switch?: boolean
      trust_remote_code?: boolean
      gpu_memory_utilization?: number
      kv_cache_quantization?: boolean
      kv_cache_quantization_bits?: number
      use_paged_cache?: boolean
      ssd_cache_dir?: string
      ssd_cache_max_gb?: number
      continuous_batching?: boolean
      enable_mtp?: boolean
      mtp_num_draft_tokens?: number
      prefill_step_size?: number
      enable_metrics?: boolean
      rate_limit?: number
      rerank_model?: string
      warm_prompts?: string
    }>('/config')
    const p = cfg.model_cache_dir ?? '~/.cache/huggingface/hub'
    cachePathInput.value = p
    savedCachePath.value = p
    startupBehavior.value = (cfg.startup_model_behavior ?? 'auto') as 'auto' | 'ask' | 'none'
    listenAllInterfaces.value = (cfg.host ?? '127.0.0.1') === '0.0.0.0'
    inferenceApiKey.value = cfg.api_key ?? ''
    offlineMode.value = cfg.offline ?? false
    autoModelSwitch.value = cfg.auto_model_switch ?? false
    // Advanced inference settings
    trustRemoteCode.value = cfg.trust_remote_code ?? false
    gpuMemoryUtil.value = cfg.gpu_memory_utilization ?? 0.90
    kvCacheQuantization.value = cfg.kv_cache_quantization ?? false
    kvCacheQuantizationBits.value = cfg.kv_cache_quantization_bits ?? 8
    usePaged.value = cfg.use_paged_cache ?? false
    ssdCacheDir.value = cfg.ssd_cache_dir ?? ''
    ssdCacheMaxGb.value = cfg.ssd_cache_max_gb ?? 0
    continuousBatching.value = cfg.continuous_batching ?? false
    enableMtp.value = cfg.enable_mtp ?? false
    mtpDraftTokens.value = cfg.mtp_num_draft_tokens ?? 1
    prefillStepSize.value = cfg.prefill_step_size ?? 0
    enableMetrics.value = cfg.enable_metrics ?? false
    rateLimit.value = cfg.rate_limit ?? 0
    rerankModel.value = cfg.rerank_model ?? ''
    warmPrompts.value = cfg.warm_prompts ?? ''
  } catch { /* silent */ }
  try {
    const r = await api.get<{ size_gb: number }>('/models/cache_size')
    diskUsedGb.value = r.size_gb
  } catch { /* silent */ }
  updatesStore.checkUpdates().catch(() => {})
})

async function saveCachePath() {
  try {
    await api.post('/config', { model_cache_dir: cachePathInput.value })
    savedCachePath.value = cachePathInput.value
    editCachePath.value = false
  } catch { /* silent */ }
}

function cancelCachePath() {
  cachePathInput.value = savedCachePath.value
  editCachePath.value = false
}

function submitAdd() {
  if (!form.name.trim()) { formError.value = 'Name is required'; return }
  if (!form.host.trim()) { formError.value = 'Host is required'; return }
  machinesStore.addMachine({ name: form.name, host: form.host, port: form.port, type: form.type, memoryGb: 0 })
  form.name = ''; form.host = ''; form.port = 8502
  showAddForm.value = false
  formError.value = ''
}

function removeConfirm(m: Machine) {
  if (m.type === 'local') return
  confirmRemove.value = m
}

function doRemove() {
  if (!confirmRemove.value) return
  machinesStore.removeMachine(confirmRemove.value.id)
  confirmRemove.value = null
}

async function saveStartupBehavior(val: 'auto' | 'ask' | 'none') {
  startupBehavior.value = val
  try { await api.post('/config', { startup_model_behavior: val }) } catch { /* silent */ }
}

async function saveListenAddress(allInterfaces: boolean) {
  listenAllInterfaces.value = allInterfaces
  try { await api.post('/config', { host: allInterfaces ? '0.0.0.0' : '127.0.0.1' }) } catch { /* silent */ }
}

async function saveApiKey() {
  try { await api.post('/config', { api_key: inferenceApiKey.value }) } catch { /* silent */ }
}

function saveHfToken() {
  localStorage.setItem('vmui_hf_token', hfToken.value.trim())
}

function saveOpenBrowserOnStart(val: boolean) {
  openBrowserOnStart.value = val
  localStorage.setItem('vmui_open_browser', String(val))
}

async function saveOfflineMode(val: boolean) {
  offlineMode.value = val
  try { await api.post('/config', { offline: val }) } catch { /* silent */ }
}

async function saveAutoModelSwitch(val: boolean) {
  autoModelSwitch.value = val
  try { await api.post('/auto_switch_enabled', { enabled: val }) } catch { /* silent */ }
}

async function saveAdvancedSettings() {
  try {
    await api.post('/config', {
      trust_remote_code: trustRemoteCode.value,
      gpu_memory_utilization: gpuMemoryUtil.value,
      kv_cache_quantization: kvCacheQuantization.value,
      kv_cache_quantization_bits: kvCacheQuantizationBits.value,
      use_paged_cache: usePaged.value,
      ssd_cache_dir: ssdCacheDir.value,
      ssd_cache_max_gb: ssdCacheMaxGb.value,
      continuous_batching: continuousBatching.value,
      enable_mtp: enableMtp.value,
      mtp_num_draft_tokens: mtpDraftTokens.value,
      prefill_step_size: prefillStepSize.value,
      enable_metrics: enableMetrics.value,
      rate_limit: rateLimit.value,
      rerank_model: rerankModel.value,
      warm_prompts: warmPrompts.value,
    })
    advancedSaved.value = true
    setTimeout(() => { advancedSaved.value = false }, 2000)
  } catch { /* silent */ }
}

async function doRestart() {
  showRestartConfirm.value = false
  restarting.value = true
  restartCountdown.value = 5
  try { await serverStore.restart() } catch { /* silent */ }
  restartTimer = setInterval(() => {
    restartCountdown.value--
    if (restartCountdown.value <= 0) {
      clearInterval(restartTimer!)
      window.location.href = '/'
    }
  }, 1000)
}
</script>

<template>
  <div class="settings-view">
    <h1 class="page-title">Settings</h1>

    <!-- Software Updates -->
    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Software Updates</div>
          <div class="section-desc">Check and install updates for vllm-mlx-ui and its dependencies.</div>
        </div>
        <AppButton variant="secondary" size="sm" :loading="updatesStore.checking" @click="updatesStore.checkUpdates(true)">
          {{ updatesStore.checking ? 'Checking…' : '↻ Check Now' }}
        </AppButton>
      </div>
      <div v-if="updatesStore.error" class="update-error">{{ updatesStore.error }}</div>
      <div v-if="updatesStore.packages.length" class="update-table">
        <div class="update-header">
          <span>Package</span><span>Installed</span><span>Latest</span><span>Status</span>
        </div>
        <div v-for="pkg in updatesStore.packages" :key="pkg.name" class="update-row">
          <span class="pkg-name">
            <a :href="pkg.url" target="_blank" rel="noopener" class="pkg-link">{{ pkg.name }}</a>
          </span>
          <span class="pkg-mono">{{ pkg.installed }}</span>
          <span class="pkg-mono">{{ pkg.latest }}</span>
          <span>
            <span v-if="pkg.update_available" class="update-chip available">Update available</span>
            <span v-else class="update-chip up-to-date">Up to date</span>
          </span>
        </div>
      </div>
      <div v-else-if="!updatesStore.checking" class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">No update info yet</span>
            <span class="pref-desc">Click "Check Now" to fetch update status.</span>
          </div>
        </div>
      </div>
      <div v-if="updatesStore.anyUpdate || updatesStore.installing" class="update-install-row">
        <div v-if="updatesStore.installMessage" class="install-message">{{ updatesStore.installMessage }}</div>
        <AppButton
          v-else
          variant="primary"
          size="sm"
          :loading="updatesStore.installing"
          @click="updatesStore.installUpdates()"
        >
          {{ updatesStore.installing ? 'Installing…' : '⬆ Install Updates & Restart' }}
        </AppButton>
      </div>
    </section>

    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Fleet</div>
          <div class="section-desc">Manage local and remote machines running vllm-mlx.</div>
        </div>
        <AppButton variant="secondary" size="sm" @click="showAddForm = !showAddForm">+ Add Machine</AppButton>
      </div>

      <div v-if="showAddForm" class="add-form">
        <div class="form-grid">
          <div class="field">
            <label class="field-label">Name</label>
            <input v-model="form.name" class="field-input" placeholder="Mac Studio" />
          </div>
          <div class="field">
            <label class="field-label">Host / IP</label>
            <input v-model="form.host" class="field-input" placeholder="192.168.1.42" />
          </div>
          <div class="field field-sm">
            <label class="field-label">Port</label>
            <input v-model.number="form.port" class="field-input" type="number" placeholder="8502" />
          </div>
        </div>
        <p v-if="formError" class="form-error">{{ formError }}</p>
        <div class="form-actions">
          <AppButton variant="ghost" size="sm" @click="showAddForm = false; formError = ''">Cancel</AppButton>
          <AppButton variant="primary" size="sm" @click="submitAdd">Add</AppButton>
        </div>
      </div>

      <div class="machine-table">
        <div class="table-header">
          <span>Name</span><span>Host</span><span>Port</span><span>Type</span><span>Status</span><span></span>
        </div>
        <div v-for="m in machinesStore.machines" :key="m.id" class="table-row">
          <span class="cell-name">{{ m.name }}</span>
          <span class="cell-mono">{{ m.type === 'local' ? 'localhost' : m.host }}</span>
          <span class="cell-mono">{{ m.port }}</span>
          <span><span class="type-chip" :class="m.type">{{ m.type }}</span></span>
          <span><span class="status-dot" :class="m.online ? 'online' : 'offline'" />{{ m.online ? 'Online' : 'Offline' }}</span>
          <span class="cell-actions">
            <AppButton v-if="m.type !== 'local'" variant="ghost" size="sm" @click="removeConfirm(m)">Remove</AppButton>
          </span>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Preferences</div>
          <div class="section-desc">Startup and interface behaviour.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Auto-start server on launch</span>
            <span class="pref-desc">Automatically start the inference server when vmUI opens.</span>
          </div>
          <label class="toggle">
            <input
              type="checkbox"
              :checked="startupBehavior === 'auto'"
              @change="saveStartupBehavior(($event.target as HTMLInputElement).checked ? 'auto' : 'none')"
            />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Open browser on start</span>
            <span class="pref-desc">Launch the dashboard in the default browser when the server starts.</span>
          </div>
          <label class="toggle">
            <input
              type="checkbox"
              :checked="openBrowserOnStart"
              @change="saveOpenBrowserOnStart(($event.target as HTMLInputElement).checked)"
            />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Storage</div>
          <div class="section-desc">Model cache location and disk usage.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Model cache path</span>
            <span v-if="!editCachePath" class="pref-desc mono">{{ savedCachePath }}</span>
            <input v-else v-model="cachePathInput" class="field-input cache-path-input" type="text" />
          </div>
          <div v-if="!editCachePath" class="pref-actions">
            <AppButton variant="ghost" size="sm" @click="editCachePath = true">Change…</AppButton>
          </div>
          <div v-else class="pref-actions">
            <AppButton variant="ghost" size="sm" @click="cancelCachePath">Cancel</AppButton>
            <AppButton variant="primary" size="sm" @click="saveCachePath">Save</AppButton>
          </div>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Disk used by models</span>
            <span class="pref-desc">Calculated from cached model directories.</span>
          </div>
          <span class="pref-value mono">{{ diskUsedGb !== null ? diskUsedGb.toFixed(1) + ' GB' : '—' }}</span>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Config File</span>
            <span class="pref-desc mono-path">~/.config/vllm-mlx-ui/config.json</span>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-section kilroy-placeholder">
      <div class="section-header">
        <div>
          <div class="section-title">Kilroy Platform</div>
          <div class="section-desc">Swarm management and platform configuration — available when Kilroy is enabled.</div>
        </div>
        <span class="coming-soon">Coming soon</span>
      </div>
    </section>

    <!-- Startup Behavior -->
    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Startup Behavior</div>
          <div class="section-desc">Control what happens to the inference server when vmUI starts.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">On launch, inference server should</span>
            <span class="pref-desc">Applies on the next start of vllm-mlx-ui.</span>
          </div>
          <select
            class="field-input field-select"
            :value="startupBehavior"
            @change="saveStartupBehavior(($event.target as HTMLSelectElement).value as 'auto' | 'ask' | 'none')"
          >
            <option value="auto">Start last model automatically</option>
            <option value="ask">Show a prompt</option>
            <option value="none">Do nothing</option>
          </select>
        </div>
      </div>
    </section>

    <!-- Advanced Inference Settings -->
    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Advanced Inference</div>
          <div class="section-desc">Engine, memory, and API tuning. Changes take effect on the next server restart.</div>
        </div>
      </div>
      <div class="pref-list">

        <!-- Safety -->
        <div class="pref-group-label">Safety</div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Trust Remote Code</span>
            <span class="pref-desc">
              Required for some HuggingFace models (certain Qwen, Phi, and custom architectures).
              <strong class="warn-inline">⚠ Only enable for models you trust.</strong>
              Disabled by default as of vllm-mlx v0.2.9.
            </span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="trustRemoteCode" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>

        <!-- Memory & Cache -->
        <div class="pref-group-label">Memory &amp; Cache</div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">GPU Memory Utilization</span>
            <span class="pref-desc">Fraction of GPU memory reserved for KV cache. Lower if you see OOM errors. Default: 0.90</span>
          </div>
          <input
            v-model.number="gpuMemoryUtil"
            class="field-input field-inline field-narrow"
            type="number" min="0.1" max="1.0" step="0.05"
          />
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">KV Cache Quantization</span>
            <span class="pref-desc">Compress key/value cache to 4 or 8 bits. Reduces memory at a slight quality cost.</span>
          </div>
          <div class="toggle-with-select">
            <label class="toggle">
              <input type="checkbox" v-model="kvCacheQuantization" />
              <span class="toggle-track"><span class="toggle-thumb" /></span>
            </label>
            <select v-if="kvCacheQuantization" class="field-input field-select field-narrow" v-model.number="kvCacheQuantizationBits">
              <option :value="8">8-bit</option>
              <option :value="4">4-bit</option>
            </select>
          </div>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Paged KV Cache</span>
            <span class="pref-desc">Use vLLM-style paged memory blocks. Reduces fragmentation for concurrent requests.</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="usePaged" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">SSD KV Cache Directory</span>
            <span class="pref-desc">
              Spill KV cache blocks to disk when GPU memory is full. Enables long-context workloads beyond RAM limits.
              Leave blank to disable. <em>(Added in v0.2.9)</em>
            </span>
          </div>
          <input
            v-model="ssdCacheDir"
            class="field-input field-inline"
            type="text"
            placeholder="/tmp/vllm-ssd-cache"
          />
        </div>
        <div v-if="ssdCacheDir" class="pref-row pref-row-sub">
          <div class="pref-info">
            <span class="pref-label">SSD Cache Max Size (GB)</span>
            <span class="pref-desc">Maximum disk space to use for KV cache. 0 = unlimited.</span>
          </div>
          <input
            v-model.number="ssdCacheMaxGb"
            class="field-input field-inline field-narrow"
            type="number" min="0" step="10"
          />
        </div>

        <!-- Inference Engine -->
        <div class="pref-group-label">Inference Engine</div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Continuous Batching</span>
            <span class="pref-desc">Enable the batched engine for multi-user serving. Higher throughput, slightly higher latency per request.</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="continuousBatching" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Multi-Token Prediction (MTP)</span>
            <span class="pref-desc">Speculatively draft multiple tokens per step. Increases throughput on capable models.</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="enableMtp" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div v-if="enableMtp" class="pref-row pref-row-sub">
          <div class="pref-info">
            <span class="pref-label">MTP Draft Tokens</span>
            <span class="pref-desc">Number of tokens to speculatively draft per step. Default: 1</span>
          </div>
          <input
            v-model.number="mtpDraftTokens"
            class="field-input field-inline field-narrow"
            type="number" min="1" max="8"
          />
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Prefill Step Size</span>
            <span class="pref-desc">Tokens per chunked prefill step. 0 = use engine default. Tune to trade latency vs throughput on long prompts.</span>
          </div>
          <input
            v-model.number="prefillStepSize"
            class="field-input field-inline field-narrow"
            type="number" min="0" step="64"
            placeholder="0"
          />
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Warm Prompts File</span>
            <span class="pref-desc">
              Path to a file of prompts to pre-warm the KV cache on startup. Reduces cold-start TTFT for agents.
              <em>(Added in v0.2.9)</em>
            </span>
          </div>
          <input
            v-model="warmPrompts"
            class="field-input field-inline"
            type="text"
            placeholder="/path/to/warm-prompts.txt"
          />
        </div>

        <!-- API & Observability -->
        <div class="pref-group-label">API &amp; Observability</div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Rate Limit</span>
            <span class="pref-desc">Max requests per minute per API key. 0 = unlimited.</span>
          </div>
          <input
            v-model.number="rateLimit"
            class="field-input field-inline field-narrow"
            type="number" min="0" step="10"
            placeholder="0"
          />
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Prometheus Metrics</span>
            <span class="pref-desc">Expose <code class="step-code">/metrics</code> endpoint in Prometheus format. Requires server restart.</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="enableMetrics" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Rerank Model</span>
            <span class="pref-desc">HuggingFace model ID to serve on the <code class="step-code">/v1/rerank</code> endpoint (MLX BERT classifier). Leave blank to disable.</span>
          </div>
          <input
            v-model="rerankModel"
            class="field-input field-inline"
            type="text"
            placeholder="mlx-community/…"
          />
        </div>

        <div class="pref-row pref-row-actions">
          <span v-if="advancedSaved" class="saved-badge">✓ Saved — restart server to apply</span>
          <AppButton variant="primary" size="sm" @click="saveAdvancedSettings">Save Advanced Settings</AppButton>
        </div>
      </div>
    </section>

    <!-- Network & Access -->
    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Network &amp; Access</div>
          <div class="section-desc">Control who can reach the inference server and this dashboard.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Listen address</span>
            <span class="pref-desc">
              {{ listenAllInterfaces ? 'All interfaces (0.0.0.0) — reachable from other devices on your network.' : 'This Mac only (127.0.0.1) — not reachable from other devices.' }}
            </span>
          </div>
          <label class="toggle">
            <input type="checkbox" :checked="listenAllInterfaces" @change="saveListenAddress(($event.target as HTMLInputElement).checked)" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Inference Server API Key</span>
            <span class="pref-desc">Bearer token required by clients to connect. Leave blank to disable.</span>
          </div>
          <div class="pref-actions">
            <input
              v-model="inferenceApiKey"
              class="field-input field-inline"
              type="password"
              placeholder="sk-…  (leave blank to disable)"
              @blur="saveApiKey"
            />
          </div>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">HuggingFace Access Token</span>
            <span class="pref-desc">Required for private or gated models. Get yours at huggingface.co/settings/tokens. Stored locally only — never sent to any server.</span>
          </div>
          <div class="pref-actions">
            <input
              v-model="hfToken"
              class="field-input field-inline"
              type="password"
              placeholder="hf_…"
              @blur="saveHfToken"
            />
          </div>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Offline Mode</span>
            <span class="pref-desc">Don't contact HuggingFace for model metadata or downloads.</span>
          </div>
          <label class="toggle">
            <input type="checkbox" :checked="offlineMode" @change="saveOfflineMode(($event.target as HTMLInputElement).checked)" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Auto Model Switch</span>
            <span class="pref-desc">
              When enabled, chat clients that request a different model are automatically switched — the server restarts and they receive an in-stream notification to wait. Uses the <code class="step-code">/v1/chat/completions</code> proxy endpoint (port 8502).
            </span>
          </div>
          <label class="toggle">
            <input type="checkbox" :checked="autoModelSwitch" @change="saveAutoModelSwitch(($event.target as HTMLInputElement).checked)" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
      </div>
      <div class="pref-collapsible-wrap">
        <CollapsibleSection title="Firewall &amp; Remote Access">
          <ol class="firewall-steps">
            <li class="firewall-step">
              <span class="step-num">1</span>
              <span class="step-text">Open <strong>System Settings</strong> → <strong>Privacy &amp; Security</strong> → <strong>Firewall</strong></span>
            </li>
            <li class="firewall-step">
              <span class="step-num">2</span>
              <span class="step-text">Click the <strong>lock icon</strong> and enter your admin password to make changes</span>
            </li>
            <li class="firewall-step">
              <span class="step-num">3</span>
              <span class="step-text">Click <strong>Firewall Options…</strong></span>
            </li>
            <li class="firewall-step">
              <span class="step-num">4</span>
              <span class="step-text">Click <strong>+</strong> and add <span class="step-code">python3</span> (or the vllm-mlx executable) from your Python environment</span>
            </li>
            <li class="firewall-step">
              <span class="step-num">5</span>
              <span class="step-text">Set the entry to <strong>Allow incoming connections</strong> and click OK</span>
            </li>
          </ol>
          <div class="firewall-notes">
            <div class="firewall-note-item">
              <span class="note-bullet">→</span>
              <span>If you enabled <span class="step-code">--host 0.0.0.0</span> and remote clients still can't connect, try temporarily disabling the firewall to confirm it's the cause, then re-enable and adjust the rules.</span>
            </div>
            <div class="firewall-note-item">
              <span class="note-bullet">→</span>
              <span>Port to allow: <span class="step-code">8502</span> (management dashboard) and the inference port configured in Settings → Network → Port. Both must be reachable for remote access.</span>
            </div>
          </div>
        </CollapsibleSection>
      </div>
    </section>

    <!-- Maintenance -->
    <section class="settings-section">
      <div class="section-header">
        <div>
          <div class="section-title">Maintenance</div>
          <div class="section-desc">Restart or manage the dashboard process.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Restart Dashboard</span>
            <span class="pref-desc">Re-reads config and picks up any code changes. The page will reload automatically.</span>
          </div>
          <AppButton variant="secondary" size="sm" @click="showRestartConfirm = true">↺ Restart</AppButton>
        </div>
        <div v-if="restarting" class="pref-row">
          <div class="pref-info">
            <span class="pref-label" style="color: var(--si-300)">Restarting…</span>
            <span class="pref-desc">The page will reload in {{ restartCountdown }} second{{ restartCountdown !== 1 ? 's' : '' }}.</span>
          </div>
        </div>
      </div>
    </section>

    <ConfirmModal
      v-if="confirmRemove"
      title="Remove Machine"
      :message="`Remove &quot;${confirmRemove.name}&quot; from your fleet?`"
      confirm-label="Remove"
      :destructive="true"
      @confirm="doRemove"
      @cancel="confirmRemove = null"
    />
    <ConfirmModal
      v-if="showRestartConfirm"
      title="Restart Dashboard"
      message="The dashboard will restart and reconnect in a few seconds."
      confirm-label="Restart"
      @confirm="doRestart"
      @cancel="showRestartConfirm = false"
    />
  </div>
</template>

<style scoped>
.settings-view { display: flex; flex-direction: column; gap: var(--space-6); max-width: 800px; }
.page-title { font-size: var(--text-lg); font-weight: 700; letter-spacing: -.3px; color: var(--tx-primary); }
.settings-section { background: var(--bg-surface); border: 1px solid var(--bd-default); border-radius: var(--r-lg); overflow: hidden; }
.section-header { display: flex; align-items: flex-start; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-subtle); }
.section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--si-400);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.section-title::before {
  content: '';
  display: block;
  width: 3px;
  height: 11px;
  background: var(--si-500);
  border-radius: 2px;
  flex-shrink: 0;
}
.section-desc { font-size: 12px; color: var(--tx-muted); }
.add-form { padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-default); background: var(--bg-elevated); display: flex; flex-direction: column; gap: var(--space-3); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: var(--space-3); }
.field { display: flex; flex-direction: column; gap: var(--space-1); }
.field-sm { width: 90px; }
.field-label { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); }
.field-input { background: var(--bg-surface); border: 1px solid var(--bd-default); border-radius: var(--r-md); padding: 5px var(--space-3); font-family: var(--font-sans); font-size: var(--text-sm); color: var(--tx-primary); outline: none; transition: border-color var(--transition-fast); }
.field-input:focus { border-color: var(--bd-focus); }
.field-input::placeholder { color: var(--tx-muted); }
.field-select { cursor: pointer; }
.form-error { font-size: 12px; color: var(--cr-500); }
.form-actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
.machine-table { display: flex; flex-direction: column; }
.table-header { display: grid; grid-template-columns: 1.5fr 1.5fr 80px 80px 100px 80px; padding: var(--space-2) var(--space-5); background: var(--bg-elevated); font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.table-row { display: grid; grid-template-columns: 1.5fr 1.5fr 80px 80px 100px 80px; padding: var(--space-3) var(--space-5); align-items: center; border-bottom: 1px solid var(--bd-subtle); font-size: var(--text-sm); color: var(--tx-secondary); transition: background var(--transition-fast); }
.table-row:last-child { border-bottom: none; }
.table-row:hover { background: var(--bg-elevated); }
.cell-name { font-weight: 500; color: var(--tx-primary); }
.cell-mono { font-family: var(--font-mono); font-size: 12px; }
.cell-actions { display: flex; justify-content: flex-end; }
.type-chip { font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; padding: 2px 7px; border-radius: var(--r-pill); border: 1px solid var(--bd-default); color: var(--tx-muted); }
.type-chip.local { color: var(--si-300); border-color: var(--ac-border); background: var(--ac-bg); }
.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.status-dot.online  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.status-dot.offline { background: var(--g-600); }
.pref-list { display: flex; flex-direction: column; }
.pref-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-subtle); }
.pref-row:last-child { border-bottom: none; }
.pref-info { display: flex; flex-direction: column; gap: 2px; }
.pref-label { font-size: var(--text-sm); font-weight: 500; color: var(--tx-primary); }
.pref-desc { font-size: 12px; color: var(--tx-muted); }
.pref-desc.mono { font-family: var(--font-mono); font-size: 11.5px; }
.mono-path { font-family: var(--font-mono); font-size: 11.5px; }
.pref-value { font-size: var(--text-sm); color: var(--tx-secondary); }
.pref-value.mono { font-family: var(--font-mono); font-size: 12px; }
.field-inline { width: 260px; }
.toggle { position: relative; cursor: pointer; display: inline-block; }
.toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.toggle-track { display: block; width: 36px; height: 20px; border-radius: var(--r-pill); background: var(--g-600); border: 1px solid var(--bd-default); transition: background var(--transition-base), border-color var(--transition-base); position: relative; }
.toggle input:checked ~ .toggle-track { background: var(--si-500); border-color: var(--si-600); }
.toggle-thumb { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: white; transition: transform var(--transition-base); }
.toggle input:checked ~ .toggle-track .toggle-thumb { transform: translateX(16px); }
.pref-actions { display: flex; gap: var(--space-2); flex-shrink: 0; }
.cache-path-input { width: 280px; }
.kilroy-placeholder { opacity: .55; }
.coming-soon { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border: 1px solid var(--bd-default); border-radius: var(--r-pill); padding: 3px 10px; flex-shrink: 0; margin-top: 2px; }

/* Updates */
.update-table { display: flex; flex-direction: column; }
.update-header { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr 140px; padding: var(--space-2) var(--space-5); background: var(--bg-elevated); font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.update-row { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr 140px; padding: var(--space-3) var(--space-5); align-items: center; border-bottom: 1px solid var(--bd-subtle); font-size: var(--text-sm); }
.update-row:last-child { border-bottom: none; }
.pkg-name { font-weight: 500; color: var(--tx-primary); }
.pkg-link { color: inherit; text-decoration: none; }
.pkg-link:hover { color: var(--si-300); text-decoration: underline; }
.pkg-mono { font-family: var(--font-mono); font-size: 12px; color: var(--tx-secondary); }
.update-chip { font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; padding: 2px 7px; border-radius: var(--r-pill); }
.update-chip.available { color: #f59e0b; background: rgba(245,158,11,.1); border: 1px solid rgba(245,158,11,.3); }
.update-chip.up-to-date { color: var(--ph-400, #4ade80); background: rgba(74,222,128,.08); border: 1px solid rgba(74,222,128,.2); }
.update-install-row { padding: var(--space-3) var(--space-5); border-top: 1px solid var(--bd-subtle); display: flex; align-items: center; gap: var(--space-3); }
.install-message { font-size: var(--text-sm); color: var(--si-300); }
.update-error { padding: var(--space-3) var(--space-5); font-size: 12px; color: var(--cr-400); }

/* Firewall guide */
.pref-collapsible-wrap {
  padding: 0 var(--space-5) var(--space-5);
  border-top: 1px solid var(--bd-subtle);
  padding-top: var(--space-4);
}

.firewall-steps {
  list-style: none;
  margin: 0;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--bg-canvas, var(--bg-base));
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-md);
}

.firewall-step {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.step-num {
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--si-300);
  min-width: 18px;
  line-height: 1.6;
  flex-shrink: 0;
}

.step-text {
  font-size: 13px;
  color: var(--tx-secondary);
  line-height: 1.55;
}

.step-code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--tx-primary);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-sm);
  padding: 1px 5px;
}

.firewall-notes {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.firewall-note-item {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  font-size: 12px;
  color: var(--tx-muted);
  line-height: 1.55;
}

.note-bullet {
  color: var(--si-300);
  font-size: 12px;
  line-height: 1.55;
  flex-shrink: 0;
}

/* Advanced inference settings */
.pref-group-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  padding: var(--space-2) var(--space-5) var(--space-1);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--bd-subtle);
  border-top: 1px solid var(--bd-subtle);
}
.pref-group-label:first-child {
  border-top: none;
}
.pref-row-sub {
  background: var(--bg-elevated);
  padding-left: calc(var(--space-5) + 16px);
}
.field-narrow { width: 100px; }
.toggle-with-select { display: flex; align-items: center; gap: var(--space-3); }
.warn-inline { color: var(--cr-400, #f87171); font-weight: 600; font-size: 11.5px; }
.pref-row-actions {
  justify-content: flex-end;
  gap: var(--space-3);
  padding-top: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: none;
}
.saved-badge {
  font-size: 12px;
  color: var(--ph-400, #4ade80);
  font-weight: 500;
}
</style>
