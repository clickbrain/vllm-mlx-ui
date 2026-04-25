<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useMachinesStore } from '@/stores/machines'
import type { Machine } from '@/stores/machines'
import AppButton from '@/components/shared/AppButton.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'

const machinesStore = useMachinesStore()

const showAddForm = ref(false)
const form = reactive({ name: '', host: '', port: 8502, type: 'remote' as 'remote' | 'local' })
const formError = ref('')
const confirmRemove = ref<Machine | null>(null)

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
</script>

<template>
  <div class="settings-view">
    <h1 class="page-title">Settings</h1>

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
          <label class="toggle"><input type="checkbox" /><span class="toggle-track"><span class="toggle-thumb" /></span></label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Open browser on start</span>
            <span class="pref-desc">Launch the dashboard in the default browser when the server starts.</span>
          </div>
          <label class="toggle"><input type="checkbox" checked /><span class="toggle-track"><span class="toggle-thumb" /></span></label>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">API key</span>
            <span class="pref-desc">Optional bearer token required by clients to connect.</span>
          </div>
          <input class="field-input field-inline" type="password" placeholder="sk-…  (leave blank to disable)" />
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
            <span class="pref-desc mono">~/.cache/huggingface/hub</span>
          </div>
          <AppButton variant="ghost" size="sm">Change…</AppButton>
        </div>
        <div class="pref-row">
          <div class="pref-info">
            <span class="pref-label">Disk used by models</span>
            <span class="pref-desc">Calculated from cached model directories.</span>
          </div>
          <span class="pref-value mono">—</span>
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

    <ConfirmModal
      v-if="confirmRemove"
      title="Remove Machine"
      :message="`Remove &quot;${confirmRemove.name}&quot; from your fleet?`"
      confirm-label="Remove"
      :destructive="true"
      @confirm="doRemove"
      @cancel="confirmRemove = null"
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
.pref-value { font-size: var(--text-sm); color: var(--tx-secondary); }
.pref-value.mono { font-family: var(--font-mono); font-size: 12px; }
.field-inline { width: 260px; }
.toggle { position: relative; cursor: pointer; display: inline-block; }
.toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.toggle-track { display: block; width: 36px; height: 20px; border-radius: var(--r-pill); background: var(--g-600); border: 1px solid var(--bd-default); transition: background var(--transition-base), border-color var(--transition-base); position: relative; }
.toggle input:checked ~ .toggle-track { background: var(--si-500); border-color: var(--si-600); }
.toggle-thumb { position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: 50%; background: white; transition: transform var(--transition-base); }
.toggle input:checked ~ .toggle-track .toggle-thumb { transform: translateX(16px); }
.kilroy-placeholder { opacity: .55; }
.coming-soon { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); border: 1px solid var(--bd-default); border-radius: var(--r-pill); padding: 3px 10px; flex-shrink: 0; margin-top: 2px; }
</style>
