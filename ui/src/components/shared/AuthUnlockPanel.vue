<!--
  AuthUnlockPanel — overlay shown when the dashboard returns a 401.

  Appears when vmUI was installed with an auto-generated API key and the
  browser hasn't stored it yet (e.g. fresh login on the Studio, upgraded
  install, or cleared localStorage). Lets the user paste their key and
  stores it to localStorage so all subsequent requests are authenticated.

  Design: compact centered card, no full-screen takeover. Borders-only depth,
  graphite palette from the design system.
-->
<script setup lang="ts">
import { ref } from 'vue'
import { authRequired, setMgmtApiKey } from '@/api/client'

const inputKey = ref('')
const error = ref('')
const checking = ref(false)

async function unlock() {
  const key = inputKey.value.trim()
  if (!key) { error.value = 'Please paste your API key.'; return }
  checking.value = true
  error.value = ''
  try {
    // Verify the key works before persisting it.
    const res = await fetch('/health', { headers: { 'X-Api-Key': key } })
    if (res.status === 401) {
      error.value = 'That key was not accepted. Double-check you copied the full value.'
      return
    }
    setMgmtApiKey(key)
    authRequired.value = false
    // Reload so all stores re-initialize cleanly.
    window.location.reload()
  } catch {
    error.value = 'Could not reach the dashboard server. Is it running?'
  } finally {
    checking.value = false
  }
}

function skipAuth() {
  // Clear any stored key — if the server has no key set, empty-key requests work fine.
  setMgmtApiKey('')
  authRequired.value = false
}
</script>

<template>
  <Teleport to="body">
    <div v-if="authRequired" class="auth-backdrop" role="dialog" aria-modal="true" aria-label="Authentication required">
      <div class="auth-card">
        <div class="auth-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
        </div>
        <h2 class="auth-title">Authentication Required</h2>
        <p class="auth-desc">
          Your vmUI dashboard is protected with an API key. Paste the key below to unlock it.
        </p>
        <div class="auth-hint">
          <span class="auth-hint-label">Find your key in</span>
          <code class="auth-hint-path">~/.vllm_mlx_ui/config.json</code>
          <span class="auth-hint-label">→ <code>mgmt_api_key</code></span>
        </div>
        <input
          v-model="inputKey"
          class="auth-input"
          type="text"
          placeholder="Paste API key here"
          aria-label="Management API key"
          @keydown.enter="unlock"
        />
        <div v-if="error" class="auth-error" role="alert">{{ error }}</div>
        <div class="auth-actions">
          <button class="auth-btn-primary" :disabled="checking" @click="unlock">
            {{ checking ? 'Checking…' : 'Unlock Dashboard' }}
          </button>
          <button class="auth-btn-ghost" @click="skipAuth">
            Skip (server has no key)
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.auth-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(8, 8, 9, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: var(--space-4);
}

.auth-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
  padding: var(--space-8) var(--space-8) var(--space-6);
  max-width: 440px;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth-icon {
  color: var(--tx-secondary);
  display: flex;
  align-items: center;
}

.auth-title {
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--tx-primary);
  margin: 0;
}

.auth-desc {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  line-height: 1.55;
  margin: 0;
}

.auth-hint {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--tx-tertiary);
  background: var(--bg-inset);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-sm);
  padding: var(--space-2) var(--space-3);
}

.auth-hint code {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--tx-secondary);
}

.auth-hint-label {
  white-space: nowrap;
}

.auth-input {
  width: 100%;
  padding: var(--space-3) var(--space-3);
  background: var(--bg-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color 0.15s;
}

.auth-input:focus-visible {
  border-color: var(--si-500);
  box-shadow: 0 0 0 2px rgba(91, 106, 208, 0.2);
}

.auth-error {
  font-size: var(--text-xs);
  color: var(--cr-500, #EF4444);
  padding: var(--space-2) var(--space-3);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--r-sm);
}

.auth-actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

.auth-btn-primary {
  padding: var(--space-3) var(--space-4);
  background: var(--si-500, #5B6AD0);
  color: #fff;
  border: none;
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
}

.auth-btn-primary:hover:not(:disabled) { opacity: 0.88; }
.auth-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.auth-btn-ghost {
  padding: var(--space-2) var(--space-4);
  background: transparent;
  color: var(--tx-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-md);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.auth-btn-ghost:hover {
  color: var(--tx-secondary);
  border-color: var(--border-default);
}
</style>
