<!--
  InstallEngineModal — auto-installs a required engine and shows real-time progress.

  Opens automatically when the user loads a model that requires an engine that is
  not yet installed (e.g. lightning-mlx for MTPLX models). The modal streams pip
  install output from POST /engines/{engineId}/install, then emits `installed`
  when the install succeeds so the parent can retry the model load.

  Props:
  - engineId: engine ID to install (e.g. "lightning-mlx")
  - engineName: human-readable engine name for the header
  - modelId: model being loaded (shown in the header)

  Emits:
  - installed: installation succeeded; parent should retry the model load
  - cancel: user dismissed the modal before/after install
-->
<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { getBase, getMgmtApiKey } from '@/api/client'

const props = defineProps<{
  engineId: string
  engineName: string
  modelId: string
}>()

const emit = defineEmits<{
  installed: []
  cancel: []
}>()

interface LogLine {
  text: string
  type: 'normal' | 'success' | 'error' | 'dim'
}

const lines = ref<LogLine[]>([])
const running = ref(true)
const success = ref(false)
const failed = ref(false)
const logRef = ref<HTMLElement | null>(null)
const abortController = new AbortController()
let retryTimer: ReturnType<typeof setTimeout> | null = null

function addLine(text: string, type?: LogLine['type']) {
  const autoType: LogLine['type'] = type
    ?? (text.includes('✅') ? 'success'
      : text.startsWith('❌') ? 'error'
      : text.startsWith('⚠') ? 'error'
      : text.trim() === '' ? 'dim'
      : 'normal')
  lines.value.push({ text, type: autoType })
  nextTick(() => {
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
  })
}

const modelName = props.modelId.split('/').pop() ?? props.modelId

async function startInstall() {
  addLine(`Setting up ${props.engineName} for ${modelName}`, 'dim')
  addLine('')

  const url = `${getBase()}/engines/${props.engineId}/install`
  const key = getMgmtApiKey()
  const headers: Record<string, string> = {}
  if (key) headers['X-Api-Key'] = key

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      signal: abortController.signal,
    })

    if (!response.ok) {
      const body = await response.text().catch(() => '')
      addLine(`❌ Install request failed (HTTP ${response.status})${body ? ': ' + body : ''}`)
      failed.value = true
      running.value = false
      return
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n')
      buffer = parts.pop() ?? ''
      for (const line of parts) {
        addLine(line)
      }
    }
    if (buffer.trim()) addLine(buffer)

    success.value = lines.value.some(l => l.text.includes('✅ Install complete'))
    failed.value = !success.value
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    addLine(`❌ ${String(e)}`)
    failed.value = true
  } finally {
    running.value = false
  }

  if (success.value) {
    addLine('')
    addLine(`✅ ${props.engineName} installed — loading ${modelName}…`, 'success')
    retryTimer = setTimeout(() => emit('installed'), 1200)
  }
}

function handleCancel() {
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  abortController.abort()
  emit('cancel')
}

function handleEscape(e: KeyboardEvent) {
  if (e.key === 'Escape' && !running.value) {
    e.preventDefault()
    emit('cancel')
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleEscape)
  startInstall()
})

onUnmounted(() => {
  if (retryTimer !== null) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  document.removeEventListener('keydown', handleEscape)
  abortController.abort()
})
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop">
      <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="install-modal-title">
        <!-- Header -->
        <div class="modal-header">
          <div class="header-left">
            <span class="engine-icon">⚡</span>
            <div>
              <div id="install-modal-title" class="modal-title">Installing {{ engineName }}</div>
              <div class="modal-sub">Required for {{ modelName }}</div>
            </div>
          </div>
          <div v-if="running" class="spinner" aria-label="Installing…" />
          <span v-else-if="success" class="status-icon success">✅</span>
          <span v-else-if="failed" class="status-icon error">❌</span>
        </div>

        <!-- Terminal log -->
        <div ref="logRef" class="terminal-log" aria-live="polite" aria-label="Installation output">
          <div
            v-for="(line, i) in lines"
            :key="i"
            class="log-line"
            :class="line.type"
          >{{ line.text || '\u00a0' }}</div>
        </div>

        <!-- Footer -->
        <div class="modal-footer">
          <div class="footer-info">
            <span v-if="running">Installing… this takes 30–60 seconds</span>
            <span v-else-if="success" class="text-success">Install complete — loading model</span>
            <span v-else-if="failed" class="text-error">Installation failed — see output above</span>
          </div>
          <button
            class="btn-cancel"
            :disabled="running"
            @click="handleCancel"
          >{{ running ? 'Installing…' : 'Close' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fade-in 0.12s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.modal-box {
  background: var(--bg-surface);
  border: 1px solid var(--bd-emphasis);
  border-radius: var(--r-xl, 12px);
  box-shadow: 0 24px 72px rgba(0, 0, 0, 0.6);
  width: min(640px, 94vw);
  display: flex;
  flex-direction: column;
  animation: slide-up 0.15s ease;
  overflow: hidden;
}

@keyframes slide-up {
  from { transform: translateY(10px); opacity: 0; }
  to   { transform: translateY(0);    opacity: 1; }
}

/* Header */
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--bd-subtle);
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.engine-icon {
  font-size: 22px;
  line-height: 1;
}

.modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--tx-primary);
}

.modal-sub {
  font-size: 12px;
  color: var(--tx-muted, var(--tx-secondary));
  margin-top: 2px;
}

.status-icon {
  font-size: 20px;
}

/* Spinner */
.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--bd-default);
  border-top-color: var(--si-400, #6b7280);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Terminal */
.terminal-log {
  background: #0d1117;
  font-family: 'SF Mono', 'Menlo', 'Consolas', 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 1.65;
  padding: 14px 16px;
  height: 320px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #30363d transparent;
}

.terminal-log::-webkit-scrollbar { width: 6px; }
.terminal-log::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }

.log-line {
  color: #cdd9e5;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line.success { color: #56d364; }
.log-line.error   { color: #f85149; }
.log-line.dim     { color: #636e7b; }

/* Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--bd-subtle);
  gap: 12px;
}

.footer-info {
  font-size: 13px;
  color: var(--tx-secondary);
}

.text-success { color: var(--cg-400, #4ade80); }
.text-error   { color: var(--cr-400, #f87171); }

.btn-cancel {
  padding: 7px 18px;
  border-radius: var(--r-md);
  font-size: 13px;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-secondary);
  transition: background var(--transition-fast), border-color var(--transition-fast);
  flex-shrink: 0;
}

.btn-cancel:not(:disabled):hover {
  background: var(--bg-canvas);
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}

.btn-cancel:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
