<!--
  SettingsView — global configuration for the vmUI management server.

  Sections:
  - Remote Server: host/port/API key for connecting to a remote vmUI instance
  - Authentication: management API key for securing the dashboard itself
  - Network: bind host and port for the management server
  - Startup: auto-start inference server on dashboard launch

  Changes are saved via POST /api/settings and take effect immediately or on
  next server restart depending on the setting type.
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useMachinesStore } from '@/stores/machines'
import type { Machine } from '@/stores/machines'
import { useServerStore } from '@/stores/server'
import { useUpdatesStore } from '@/stores/updates'
import AppButton from '@/components/shared/AppButton.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import CollapsibleSection from '@/components/shared/CollapsibleSection.vue'
import { api, getBase, getMgmtApiKey } from '@/api/client'

const machinesStore = useMachinesStore()
const serverStore = useServerStore()
const updatesStore = useUpdatesStore()

const showAddForm = ref(false)
const form = reactive({ name: '', host: '', port: 8502, type: 'remote' as 'remote' | 'local' })
const formError = ref('')
const confirmRemove = ref<Machine | null>(null)
const settingsError = ref('')

// ── Inference engine management ────────────────────────────────────────────
interface EngineInfo {
  id: string
  name: string
  description: string
  installed: boolean
  install_method: 'bundled' | 'pip' | 'external'
  version?: string
  latest_version?: string
  release_url?: string
  is_builtin?: boolean
  health_path?: string
  requirements_errors?: string[]
  requirements_warnings?: string[]
}
const engines = ref<EngineInfo[]>([])
const enginesLoading = ref(false)
const enginesError = ref('')
const selectedEngine = ref(serverStore.engineId)
const installingEngine = ref<string | null>(null)
const uninstallingEngine = ref<string | null>(null)
const engineInstallLog = ref<Record<string, string>>({})
const reloadingEngines = ref(false)

async function loadEngines() {
  enginesLoading.value = true
  enginesError.value = ''
  try {
    const result = await api.get<{ engines: EngineInfo[] } | EngineInfo[]>('/engines')
    // Handle both {engines: [...]} and plain array responses
    engines.value = Array.isArray(result) ? result : (result as any).engines ?? []
  } catch (e: any) {
    enginesError.value = `Failed to load engines: ${e?.message ?? 'unknown error'}`
  } finally {
    enginesLoading.value = false
  }
}

async function reloadEngines() {
  reloadingEngines.value = true
  enginesError.value = ''
  try {
    const result = await api.post<{ ok: boolean; engines: EngineInfo[] }>('/engines/reload', {})
    engines.value = result.engines ?? []
  } catch (e: any) {
    enginesError.value = `Reload failed: ${e?.message ?? 'unknown error'}`
  } finally {
    reloadingEngines.value = false
  }
}

async function selectEngine(id: string) {
  selectedEngine.value = id
  try {
    await api.post('/config', { engine_id: id })
  } catch (e: any) {
    settingsError.value = `Failed to save engine: ${e?.message ?? 'unknown error'}`
  }
}

async function saveEngineAndRestart() {
  if (!selectedEngine.value) return
  try {
    await api.post('/config', { engine_id: selectedEngine.value })
    await serverStore.restart()
  } catch (e: any) {
    settingsError.value = `Failed to save engine: ${e?.message ?? 'unknown error'}`
  }
}

async function installEngine(id: string) {
  installingEngine.value = id
  engineInstallLog.value[id] = 'Starting install...\n'
  try {
    const resp = await fetch(`${getBase()}/engines/${id}/install`, {
      method: 'POST',
      headers: getMgmtApiKey() ? { 'X-Api-Key': getMgmtApiKey() } : {},
    })
    if (resp.status === 400) {
      const err = await resp.json().catch(() => ({}))
      enginesError.value = err.detail || 'This engine cannot be installed automatically. See description for instructions.'
      return
    }
    if (!resp.body) throw new Error('No response body')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let done = false
    while (!done) {
      const { value, done: d } = await reader.read()
      done = d
      if (value) {
        const chunk = decoder.decode(value)
        engineInstallLog.value[id] = (engineInstallLog.value[id] ?? '') + chunk
      }
    }
    await loadEngines()
  } catch (e: any) {
    enginesError.value = `Install failed: ${e?.message ?? 'unknown error'}`
  } finally {
    installingEngine.value = null
  }
}

async function uninstallEngine(id: string, name: string) {
  if (!window.confirm(`Uninstall "${name}"? This will remove the engine package and all its files.`)) return
  uninstallingEngine.value = id
  engineInstallLog.value[id] = ''
  try {
    const resp = await fetch(`${getBase()}/engines/${id}/uninstall`, {
      method: 'POST',
      headers: getMgmtApiKey() ? { 'X-Api-Key': getMgmtApiKey() } : {},
    })
    if (resp.status === 400) {
      const err = await resp.json().catch(() => ({}))
      enginesError.value = err.detail || 'This engine cannot be uninstalled automatically.'
      return
    }
    if (!resp.body) throw new Error('No response body')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let done = false
    while (!done) {
      const { value, done: d } = await reader.read()
      done = d
      if (value) {
        const chunk = decoder.decode(value)
        engineInstallLog.value[id] = (engineInstallLog.value[id] ?? '') + chunk
      }
    }
    await loadEngines()
  } catch (e: any) {
    enginesError.value = `Uninstall failed: ${e?.message ?? 'unknown error'}`
  } finally {
    uninstallingEngine.value = null
  }
}

// Keep selectedEngine in sync if the store updates after a poll
watch(() => serverStore.engineId, (id) => { selectedEngine.value = id })

// Fleet discovery
interface DiscoveredMachine { ip: string; hostname: string; port: number; version: string; model_id: string }
const discoverLoading = ref(false)
const discoverResults = ref<DiscoveredMachine[] | null>(null)
const discoverError = ref('')

async function scanFleet() {
  discoverLoading.value = true
  discoverResults.value = null
  discoverError.value = ''
  try {
    const results = await api.get<DiscoveredMachine[]>('/fleet/discover')
    discoverResults.value = results ?? []
  } catch (e: any) {
    discoverError.value = e?.message ?? 'Scan failed'
  } finally {
    discoverLoading.value = false
  }
}

function addDiscovered(d: DiscoveredMachine) {
  const label = d.hostname && d.hostname !== d.ip ? d.hostname.split('.')[0] : d.ip
  machinesStore.addMachine({ name: label, host: d.ip, port: d.port, type: 'remote', memoryGb: 0 })
  // Remove from discovered list so button turns into confirmation
  if (discoverResults.value) {
    discoverResults.value = discoverResults.value.filter(r => r.ip !== d.ip)
  }
}

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
const mgmtApiKeyMasked = ref('')
const mgmtApiKeyInput = ref('')
const mgmtApiKeySaved = ref(false)
const mgmtApiKeyError = ref('')

// Advanced Inference Settings
const trustRemoteCode = ref(false)
const gpuMemoryUtil = ref(0.90)
// Display GPU utilization as an integer percentage (10–100); store as decimal (0.1–1.0)
const gpuMemoryUtilPct = computed({
  get: () => Math.round(gpuMemoryUtil.value * 100),
  set: (v: number) => { gpuMemoryUtil.value = Math.max(10, Math.min(100, Math.round(v))) / 100 },
})
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

const ssdBrowsing = ref(false)
async function browseSsdDir() {
  ssdBrowsing.value = true
  try {
    const result = await api.get<{ path: string }>('/browse-directory')
    if (result?.path) ssdCacheDir.value = result.path
  } catch { /* user cancelled or unsupported */ }
  finally { ssdBrowsing.value = false }
}
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
  } catch (e: any) {
    settingsError.value = `Failed to load settings: ${e?.message ?? 'unknown error'}`
  }
  try {
    const r = await api.get<{ size_gb: number }>('/models/cache_size')
    diskUsedGb.value = r.size_gb
  } catch { /* cache size is non-critical */ }
  try {
    const r = await api.get<{ key_set: boolean; masked: string }>('/config/mgmt-key')
    mgmtApiKeyMasked.value = r.masked
  } catch { /* mgmt key display is non-critical */ }
  updatesStore.checkUpdates().catch(() => { /* non-critical */ })
  loadEngines().catch(() => { /* non-critical */ })
})

async function saveCachePath() {
  try {
    await api.post('/config', { model_cache_dir: cachePathInput.value })
    savedCachePath.value = cachePathInput.value
    editCachePath.value = false
  } catch (e: any) {
    settingsError.value = `Failed to save cache path: ${e?.message ?? 'unknown error'}`
  }
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
  try { await api.post('/config', { startup_model_behavior: val }) } catch (e: any) {
    settingsError.value = `Failed to save startup behavior: ${e?.message ?? 'unknown error'}`
  }
}

async function saveListenAddress(allInterfaces: boolean) {
  listenAllInterfaces.value = allInterfaces
  try { await api.post('/config', { host: allInterfaces ? '0.0.0.0' : '127.0.0.1' }) } catch (e: any) {
    settingsError.value = `Failed to save listen address: ${e?.message ?? 'unknown error'}`
  }
}

async function saveApiKey() {
  try { await api.post('/config', { api_key: inferenceApiKey.value }) } catch (e: any) {
    settingsError.value = `Failed to save API key: ${e?.message ?? 'unknown error'}`
  }
}

async function saveMgmtApiKey() {
  mgmtApiKeyError.value = ''
  try {
    await api.post('/config/mgmt-key', { key: mgmtApiKeyInput.value })
    const r = await api.get<{ key_set: boolean; masked: string }>('/config/mgmt-key')
    mgmtApiKeyMasked.value = r.masked
    mgmtApiKeyInput.value = ''
    mgmtApiKeySaved.value = true
    setTimeout(() => { mgmtApiKeySaved.value = false }, 2500)
  } catch (e: any) {
    mgmtApiKeyError.value = `Failed to save management API key: ${e?.message ?? 'unknown error'}`
  }
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
  try { await api.post('/config', { offline: val }) } catch (e: any) {
    settingsError.value = `Failed to save offline mode: ${e?.message ?? 'unknown error'}`
  }
}

async function saveAutoModelSwitch(val: boolean) {
  autoModelSwitch.value = val
  try { await api.post('/auto_switch_enabled', { enabled: val }) } catch (e: any) {
    settingsError.value = `Failed to save auto model switch: ${e?.message ?? 'unknown error'}`
  }
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
  } catch (e: any) {
    settingsError.value = `Failed to save advanced settings: ${e?.message ?? 'unknown error'}`
  }
}

async function doRestart() {
  showRestartConfirm.value = false
  restarting.value = true
  restartCountdown.value = 5
  try { await serverStore.restart() } catch (e: any) {
    settingsError.value = `Failed to restart: ${e?.message ?? 'unknown error'}`
  }
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

    <div v-if="settingsError" class="settings-error-banner">
      ⚠ {{ settingsError }}
      <button class="error-dismiss" @click="settingsError = ''">✕</button>
    </div>

    <!-- Software Updates -->
    <section class="settings-section" aria-labelledby="updates-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="updates-heading">Software Updates</div>
          <div class="section-desc">Check and install updates for vllm-mlx-ui and its dependencies.</div>
        </div>
        <AppButton variant="secondary" size="sm" :loading="updatesStore.checking" aria-label="Check for updates now" @click="updatesStore.checkUpdates(true)">
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
        <div v-if="updatesStore.installPhase" class="install-phase">
          <span class="phase-spinner" v-if="updatesStore.installing">⏳</span>
          {{ updatesStore.installPhase }}
        </div>
        <AppButton
          v-if="!updatesStore.installPhase"
          variant="primary"
          size="sm"
          :loading="updatesStore.installing"
          @click="updatesStore.installUpdates()"
        >
          {{ updatesStore.installing ? 'Installing…' : '⬆ Install Updates & Restart' }}
        </AppButton>
      </div>
    </section>

    <!-- Inference Engine -->
    <section class="settings-section" aria-labelledby="engine-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="engine-heading">Inference Engine</div>
          <div class="section-desc">Choose which engine runs your models. Changing takes effect on next server start.</div>
        </div>
        <AppButton
          variant="secondary"
          size="sm"
          :loading="reloadingEngines"
          aria-label="Reload engine plugins"
          title="Re-scan for custom engine plugins"
          @click="reloadEngines"
        >↺ Reload Plugins</AppButton>
      </div>
      <div v-if="enginesError" class="settings-error-banner">
        ⚠ {{ enginesError }}
        <button class="error-dismiss" @click="enginesError = ''">✕</button>
      </div>
      <div v-if="enginesLoading" class="pref-list">
        <div class="pref-row"><span class="pref-label">Loading engines…</span></div>
      </div>
      <div v-else class="engine-cards">
        <div
          v-for="eng in engines"
          :key="eng.id"
          class="engine-card"
          :class="{ active: selectedEngine === eng.id, unavailable: !eng.installed && eng.install_method === 'bundled' }"
          @click="eng.installed || eng.install_method !== 'bundled' ? selectEngine(eng.id) : undefined"
        >
          <div class="engine-card-header">
            <span class="engine-card-name">{{ eng.name }}</span>
            <span v-if="eng.is_builtin === false" class="engine-custom-badge" title="Loaded from a local plugin manifest">Custom</span>
            <span class="engine-installed-badge" :class="eng.installed ? 'installed' : 'not-installed'">
              {{ eng.installed ? '✓ Installed' : 'Not installed' }}
            </span>
          </div>
          <div class="engine-card-desc">{{ eng.description }}</div>
          <div v-if="eng.requirements_errors && eng.requirements_errors.length" class="engine-req-errors">
            <div class="engine-req-error-title">⚠ System Requirements Not Met</div>
            <ul class="engine-req-error-list">
              <li v-for="err in eng.requirements_errors" :key="err">{{ err }}</li>
            </ul>
          </div>
          <div v-if="eng.requirements_warnings && eng.requirements_warnings.length" class="engine-req-warnings">
            <div class="engine-req-warning-title">⚡ Low Available Memory</div>
            <ul class="engine-req-warning-list">
              <li v-for="warn in eng.requirements_warnings" :key="warn">{{ warn }}</li>
            </ul>
          </div>
          <div class="engine-card-footer">
            <span class="engine-method-chip">{{ eng.install_method }}</span>
            <span v-if="eng.version" class="engine-version dim">v{{ eng.version }}</span>
            <AppButton
              v-if="eng.installed && eng.id === selectedEngine"
              variant="primary"
              size="sm"
              @click.stop="saveEngineAndRestart()"
            >{{ eng.id !== serverStore.engineId ? 'Save & Restart' : 'Restart' }}</AppButton>
            <AppButton
              v-if="!eng.installed && eng.install_method !== 'bundled' && !(eng.requirements_errors && eng.requirements_errors.length)"
              variant="primary"
              size="sm"
              :loading="installingEngine === eng.id"
              @click.stop="installEngine(eng.id)"
            >Install</AppButton>
            <AppButton
              v-if="eng.installed && eng.install_method !== 'bundled'"
              variant="danger"
              size="sm"
              :loading="uninstallingEngine === eng.id"
              @click.stop="uninstallEngine(eng.id, eng.name)"
            >Uninstall</AppButton>
          </div>
          <div v-if="engineInstallLog[eng.id]" class="engine-install-log">
            <pre>{{ engineInstallLog[eng.id] }}</pre>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-section" aria-labelledby="fleet-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="fleet-heading">Fleet</div>
          <div class="section-desc">Manage local and remote machines running vllm-mlx.</div>
        </div>
        <div class="fleet-header-actions">
          <AppButton variant="ghost" size="sm" :disabled="discoverLoading" @click="scanFleet">
            <span v-if="discoverLoading" class="phase-spinner">⟳</span>
            {{ discoverLoading ? 'Scanning…' : 'Scan Network' }}
          </AppButton>
          <AppButton variant="secondary" size="sm" @click="showAddForm = !showAddForm">+ Add Machine</AppButton>
        </div>
      </div>

      <!-- Fleet discovery results -->
      <div v-if="discoverError" class="discover-error">{{ discoverError }}</div>
      <div v-if="discoverResults !== null" class="discover-results">
        <div v-if="discoverResults.length === 0" class="discover-empty">
          No vllm-mlx-ui servers found on local network.
        </div>
        <div v-else class="discover-list">
          <div class="discover-header">
            <span>IP</span><span>Hostname</span><span>Model</span><span>Version</span><span></span>
          </div>
          <div v-for="d in discoverResults" :key="d.ip" class="discover-row">
            <span class="cell-mono">{{ d.ip }}</span>
            <span class="cell-mono">{{ d.hostname !== d.ip ? d.hostname : '—' }}</span>
            <span class="discover-model">{{ d.model_id || '—' }}</span>
            <span class="cell-mono">{{ d.version || '—' }}</span>
            <span class="cell-actions">
              <AppButton variant="primary" size="sm" @click="addDiscovered(d)">Add</AppButton>
            </span>
          </div>
        </div>
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

    <section class="settings-section" aria-labelledby="prefs-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="prefs-heading">Preferences</div>
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

    <section class="settings-section" aria-labelledby="storage-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="storage-heading">Storage</div>
          <div class="section-desc">Unified models directory and disk usage. All MLX and GGUF engines share one directory.</div>
        </div>
      </div>
      <div class="pref-list">
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Models Directory</span>
            <span v-if="!editCachePath" class="pref-desc mono">{{ savedCachePath }}</span>
            <span v-if="!editCachePath" class="pref-desc">
              Shared by all MLX and GGUF engines. MLX models download here via HuggingFace Hub
              structure (<code>models--org--name/</code>). GGUF files can coexist as flat files
              in the same directory. Ollama uses its own <code>~/.ollama/models/</code> store.
            </span>
            <input v-else v-model="cachePathInput" class="field-input cache-path-input" type="text" placeholder="~/.cache/huggingface/hub (default)" />
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
    <section class="settings-section" aria-labelledby="startup-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="startup-heading">Startup Behavior</div>
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
    <section class="settings-section" aria-labelledby="advanced-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="advanced-heading">Advanced Inference</div>
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
              Some HuggingFace models (certain Qwen, Phi, and custom architectures) ship custom Python
              tokenizer or model code that must execute locally. Enabling this allows that code to run.
              <strong class="warn-inline">⚠ Only enable for models you explicitly trust</strong> — malicious
              model code can access your file system and network. Applies to all loaded models; there is no
              per-model toggle.
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
            <span class="pref-desc">
              Percentage of unified memory the inference server may use for the KV cache.
              90% is a safe default on most Macs. Lower this (e.g. to 75%) if you see out-of-memory errors,
              or if you want to reserve memory for other apps. Does not affect the model weights themselves.
            </span>
          </div>
          <div class="field-with-unit">
            <input
              v-model.number="gpuMemoryUtilPct"
              class="field-input field-inline field-narrow"
              type="number" min="10" max="100" step="5"
            />
            <span class="field-unit">%</span>
          </div>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">KV Cache Quantization</span>
            <span class="pref-desc">
              Compress the key/value attention cache to 4 or 8 bits instead of 16-bit floats.
              Typically saves 30–50% KV cache memory with a small quality cost at very long contexts.
              Active only in Paged KV Cache mode.
            </span>
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
            <span class="pref-desc">
              Allocates the KV cache in fixed-size pages instead of one large contiguous block.
              Eliminates memory fragmentation when running multiple concurrent requests, and enables
              prefix sharing across conversations. Required for KV Cache Quantization and SSD spill.
              Enabled automatically in Continuous Batching mode.
            </span>
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
              Spill KV cache pages to disk when GPU memory is full. Lets you run very long contexts
              (e.g. 128k+ tokens) that would otherwise run out of RAM. Uses NVMe SSD for fast access.
              Leave blank to disable disk spill. Requires Paged KV Cache to be enabled.
            </span>
          </div>
          <div class="field-with-browse">
            <input
              v-model="ssdCacheDir"
              class="field-input field-inline"
              type="text"
              placeholder="/tmp/vllm-ssd-cache"
            />
            <AppButton variant="ghost" size="sm" :loading="ssdBrowsing" @click="browseSsdDir">
              Browse…
            </AppButton>
          </div>
        </div>
        <div v-if="ssdCacheDir" class="pref-row pref-row-sub">
          <div class="pref-info">
            <span class="pref-label">SSD Cache Max Size (GB)</span>
            <span class="pref-desc">Maximum disk space to use for KV cache spill. 0 = unlimited.</span>
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
            <span class="pref-desc">
              Enables the batched inference engine, which can serve <strong>multiple apps or users simultaneously</strong>.
              Requests are grouped into dynamic batches for higher overall throughput. Individual
              request latency may be slightly higher. Recommended when sharing the server across multiple
              applications or team members.
            </span>
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
            <span class="pref-desc">
              Exposes a <code class="step-code">/metrics</code> endpoint in
              <a class="settings-link" href="https://prometheus.io/docs/concepts/data_model/" target="_blank">Prometheus format</a>
              — a standard way for monitoring tools to scrape performance data (request rates, latencies,
              token counts, memory use). Use with Prometheus + Grafana to build custom dashboards or alerts.
              Requires server restart.
            </span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="enableMetrics" />
            <span class="toggle-track"><span class="toggle-thumb" /></span>
          </label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Rerank Model</span>
            <span class="pref-desc">
              <a class="settings-link" href="https://www.sbert.net/examples/applications/retrieve_rerank/README.html" target="_blank">Reranking</a>
              scores a list of documents by relevance to a query — a second-pass step used in RAG pipelines
              to improve retrieval quality. Set to a HuggingFace model ID (e.g. an MLX BERT classifier)
              to serve on the <code class="step-code">/v1/rerank</code> endpoint. Leave blank to disable.
            </span>
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
    <section class="settings-section" aria-labelledby="network-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="network-heading">Network &amp; Access</div>
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
            <span class="pref-label">Management API Key</span>
            <span class="pref-desc">
              Secret key protecting this dashboard's management API (port 8502).
              <span v-if="mgmtApiKeyMasked" class="pref-badge-key">Active: {{ mgmtApiKeyMasked }}</span>
              <span v-else class="pref-badge-key pref-badge-warn">⚠ No key set — dashboard is open to your network</span>
            </span>
          </div>
          <div class="pref-actions pref-actions-row">
            <input
              v-model="mgmtApiKeyInput"
              class="field-input field-inline"
              type="password"
              placeholder="New key… (leave blank to clear)"
              @keydown.enter="saveMgmtApiKey"
            />
            <button class="btn-sm" @click="saveMgmtApiKey">
              {{ mgmtApiKeySaved ? '✓ Saved' : 'Save' }}
            </button>
          </div>
          <div v-if="mgmtApiKeyError" class="pref-error">{{ mgmtApiKeyError }}</div>
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
    <section class="settings-section" aria-labelledby="maintenance-heading">
      <div class="section-header">
        <div>
          <div class="section-title" id="maintenance-heading">Maintenance</div>
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
.settings-error-banner {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08); border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md); font-size: var(--text-sm); color: var(--cr-300);
}
.settings-section { background: var(--bg-surface); border: 1px solid var(--bd-default); border-radius: var(--r-lg); overflow: hidden; }
.section-header { display: flex; align-items: flex-start; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-subtle); }
.section-title {
  font-size: 12px;
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
.section-desc { font-size: 14px; color: var(--tx-muted); }
.add-form { padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-default); background: var(--bg-elevated); display: flex; flex-direction: column; gap: var(--space-3); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: var(--space-3); }
.field { display: flex; flex-direction: column; gap: var(--space-1); }
.field-sm { width: 90px; }
.field-label { font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); }
.field-input { background: var(--bg-surface); border: 1px solid var(--bd-default); border-radius: var(--r-md); padding: 5px var(--space-3); font-family: var(--font-sans); font-size: var(--text-sm); color: var(--tx-primary); outline: none; transition: border-color var(--transition-fast); }
.field-input:focus { border-color: var(--bd-focus); }
.field-input::placeholder { color: var(--tx-muted); }
.field-select { cursor: pointer; }
.form-error { font-size: 14px; color: var(--cr-500); }
.form-actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
.machine-table { display: flex; flex-direction: column; }
.fleet-header-actions { display: flex; gap: var(--space-2); align-items: center; }
.discover-error { padding: var(--space-3) var(--space-5); font-size: 14px; color: var(--cr-400); }
.discover-empty { padding: var(--space-3) var(--space-5); font-size: var(--text-sm); color: var(--tx-muted); }
.discover-results { border: 1px solid var(--bd-default); border-radius: var(--r-md); margin-bottom: var(--space-4); overflow: hidden; }
.discover-list { display: flex; flex-direction: column; }
.discover-header { display: grid; grid-template-columns: 130px 1.5fr 2fr 90px 70px; padding: var(--space-2) var(--space-5); background: var(--bg-elevated); font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.discover-row { display: grid; grid-template-columns: 130px 1.5fr 2fr 90px 70px; padding: var(--space-3) var(--space-5); align-items: center; border-bottom: 1px solid var(--bd-subtle); font-size: var(--text-sm); color: var(--tx-secondary); }
.discover-row:last-child { border-bottom: none; }
.discover-model { font-size: 13px; color: var(--tx-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-header { display: grid; grid-template-columns: 1.5fr 1.5fr 80px 80px 100px 80px; padding: var(--space-2) var(--space-5); background: var(--bg-elevated); font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.table-row { display: grid; grid-template-columns: 1.5fr 1.5fr 80px 80px 100px 80px; padding: var(--space-3) var(--space-5); align-items: center; border-bottom: 1px solid var(--bd-subtle); font-size: var(--text-sm); color: var(--tx-secondary); transition: background var(--transition-fast); }
.table-row:last-child { border-bottom: none; }
.table-row:hover { background: var(--bg-elevated); }
.cell-name { font-weight: 500; color: var(--tx-primary); }
.cell-mono { font-family: var(--font-mono); font-size: 14px; }
.cell-actions { display: flex; justify-content: flex-end; }
.type-chip { font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; padding: 2px 7px; border-radius: var(--r-pill); border: 1px solid var(--bd-default); color: var(--tx-muted); }
.type-chip.local { color: var(--si-300); border-color: var(--ac-border); background: var(--ac-bg); }
.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.status-dot.online  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.status-dot.offline { background: var(--g-600); }

/* Engine cards */
.engine-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--space-4); padding: var(--space-4) var(--space-5); }
.engine-card {
  border: 1.5px solid var(--bd-default); border-radius: var(--r-lg); padding: var(--space-4);
  cursor: pointer; transition: border-color .15s, background .15s;
  background: var(--bg-elevated);
}
.engine-card:hover { border-color: var(--bd-hover); }
.engine-card.active { border-color: var(--ac-400); background: var(--ac-bg); }
.engine-card.unavailable { opacity: 0.55; cursor: default; }
.engine-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-2); }
.engine-card-name { font-weight: 600; font-size: var(--text-sm); color: var(--tx-primary); }
.engine-installed-badge { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: var(--r-pill); }
.engine-installed-badge.installed { color: #4ade80; background: rgba(74,222,128,.1); border: 1px solid rgba(74,222,128,.25); }
.engine-installed-badge.not-installed { color: var(--tx-muted); background: var(--bg-inset); border: 1px solid var(--bd-subtle); }
.engine-custom-badge { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: var(--r-pill); color: var(--tx-secondary); background: var(--bg-inset); border: 1px solid var(--bd-subtle); margin-right: 4px; }
.engine-card-desc { font-size: 13px; color: var(--tx-muted); line-height: 1.4; margin-bottom: var(--space-3); white-space: pre-line; }
.engine-card-footer { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.engine-method-chip { font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--tx-muted); padding: 1px 6px; border-radius: var(--r-pill); background: var(--bg-inset); border: 1px solid var(--bd-subtle); }
.engine-version { font-size: 12px; font-family: var(--font-mono); }
.engine-external-hint { font-size: 12px; font-style: italic; }
.engine-install-log { margin-top: var(--space-3); }
.engine-install-log pre { font-size: 11px; font-family: var(--font-mono); color: var(--tx-muted); background: var(--bg-inset); border-radius: var(--r-sm); padding: var(--space-3); max-height: 160px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
.engine-req-errors {
  margin: var(--space-2) 0 var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: rgba(239, 68, 68, .07);
  border: 1px solid rgba(239, 68, 68, .3);
  border-radius: var(--r-md);
}
.engine-req-error-title { font-size: 12px; font-weight: 700; color: var(--cr-400, #f87171); margin-bottom: var(--space-1); }
.engine-req-error-list { margin: 0; padding-left: var(--space-4); }
.engine-req-error-list li { font-size: 12px; color: var(--cr-300, #fca5a5); line-height: 1.5; }
.engine-req-warnings {
  margin: var(--space-2) 0 var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: rgba(245, 158, 11, .07);
  border: 1px solid rgba(245, 158, 11, .3);
  border-radius: var(--r-md);
}
.engine-req-warning-title { font-size: 12px; font-weight: 700; color: #f59e0b; margin-bottom: var(--space-1); }
.engine-req-warning-list { margin: 0; padding-left: var(--space-4); }
.engine-req-warning-list li { font-size: 12px; color: #fcd34d; line-height: 1.5; }
.pref-list { display: flex; flex-direction: column; }
.pref-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--bd-subtle); }
.pref-row:last-child { border-bottom: none; }
.pref-info { display: flex; flex-direction: column; gap: 2px; }
.pref-label { font-size: var(--text-sm); font-weight: 500; color: var(--tx-primary); }
.pref-desc { font-size: 14px; color: var(--tx-muted); }
.pref-desc.mono { font-family: var(--font-mono); font-size: 13.5px; }
.mono-path { font-family: var(--font-mono); font-size: 13.5px; }
.pref-value { font-size: var(--text-sm); color: var(--tx-secondary); }
.pref-value.mono { font-family: var(--font-mono); font-size: 14px; }
.field-inline { width: 260px; }
.toggle { position: relative; cursor: pointer; display: inline-block; }
.toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.toggle-track { display: block; width: 36px; height: 20px; border-radius: var(--r-pill); background: var(--g-600); border: 1px solid var(--bd-default); transition: background var(--transition-base), border-color var(--transition-base); position: relative; }
.toggle input:checked ~ .toggle-track { background: var(--si-500); border-color: var(--si-600); }
.toggle-thumb { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: white; transition: transform var(--transition-base); }
.toggle input:checked ~ .toggle-track .toggle-thumb { transform: translateX(16px); }
.pref-actions { display: flex; gap: var(--space-2); flex-shrink: 0; }
.pref-actions-row { flex-direction: row; align-items: center; }
.pref-badge-key { font-family: var(--font-mono); font-size: 11px; color: var(--tx-secondary); background: var(--bg-elevated); border: 1px solid var(--bd-default); border-radius: var(--r-pill); padding: 1px 6px; margin-left: 4px; white-space: nowrap; }
.pref-badge-warn { color: #f59e0b; background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.3); }
.pref-error { font-size: 12px; color: var(--si-300, #f87171); margin-top: var(--space-1); padding: 0 var(--space-3); }
.btn-sm { font-size: 12px; padding: 4px 10px; border-radius: var(--r-base); border: 1px solid var(--bd-default); background: var(--bg-elevated); color: var(--tx-primary); cursor: pointer; white-space: nowrap; }
.btn-sm:hover { background: var(--bg-inset); }
.cache-path-input { width: 280px; }
.kilroy-placeholder { opacity: .55; }
.coming-soon { font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border: 1px solid var(--bd-default); border-radius: var(--r-pill); padding: 3px 10px; flex-shrink: 0; margin-top: 2px; }

/* Updates */
.update-table { display: flex; flex-direction: column; }
.update-header { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr 140px; padding: var(--space-2) var(--space-5); background: var(--bg-elevated); font-size: 12px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.update-row { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr auto; padding: var(--space-3) var(--space-5); align-items: center; border-bottom: 1px solid var(--bd-subtle); font-size: var(--text-sm); }
.update-row:last-child { border-bottom: none; }
.pkg-name { font-weight: 500; color: var(--tx-primary); }
.pkg-link { color: inherit; text-decoration: none; }
.pkg-link:hover { color: var(--si-300); text-decoration: underline; }
.pkg-mono { font-family: var(--font-mono); font-size: 14px; color: var(--tx-secondary); }
.update-chip { font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; padding: 2px 7px; border-radius: var(--r-pill); white-space: nowrap; }
.update-chip.available { color: #f59e0b; background: rgba(245,158,11,.1); border: 1px solid rgba(245,158,11,.3); }
.update-chip.up-to-date { color: var(--ph-400, #4ade80); background: rgba(74,222,128,.08); border: 1px solid rgba(74,222,128,.2); }
.update-install-row { padding: var(--space-3) var(--space-5); border-top: 1px solid var(--bd-subtle); display: flex; align-items: center; gap: var(--space-3); }
.install-message { font-size: var(--text-sm); color: var(--si-300); }
.install-phase { font-size: var(--text-sm); color: var(--tx-secondary); display: flex; align-items: center; gap: var(--space-2); }
.phase-spinner { animation: spin 1.2s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
.update-error { padding: var(--space-3) var(--space-5); font-size: 14px; color: var(--cr-400); }

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
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--si-300);
  min-width: 18px;
  line-height: 1.6;
  flex-shrink: 0;
}

.step-text {
  font-size: 15px;
  color: var(--tx-secondary);
  line-height: 1.55;
}

.step-code {
  font-family: var(--font-mono);
  font-size: 13.5px;
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
  font-size: 14px;
  color: var(--tx-muted);
  line-height: 1.55;
}

.note-bullet {
  color: var(--si-300);
  font-size: 14px;
  line-height: 1.55;
  flex-shrink: 0;
}

/* Advanced inference settings */
.pref-group-label {
  font-size: 12px;
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
.warn-inline { color: var(--cr-400, #f87171); font-weight: 600; font-size: 13.5px; }

/* GPU % input + SSD browse button layouts */
.field-with-unit {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.field-unit {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  font-weight: 500;
}
.field-with-browse {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.field-with-browse .field-inline { flex: 1; width: auto; min-width: 160px; }

/* Inline links in setting descriptions */
.settings-link {
  color: var(--si-400);
  text-decoration: underline;
  text-decoration-color: rgba(91,106,208,.4);
  text-underline-offset: 2px;
}
.settings-link:hover { text-decoration-color: var(--si-400); }
.pref-row-actions {
  justify-content: flex-end;
  gap: var(--space-3);
  padding-top: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: none;
}
.saved-badge {
  font-size: 14px;
  color: var(--ph-400, #4ade80);
  font-weight: 500;
}
</style>
