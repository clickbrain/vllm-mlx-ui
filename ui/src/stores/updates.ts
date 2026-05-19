// SPDX-License-Identifier: Apache-2.0
/**
 * Updates store — checks for vmUI and vllm-mlx package updates.
 *
 * checkUpdates() hits GET /updates (or /updates?force=true) which returns a
 * list of pip-inspected packages with installed vs latest versions.
 *
 * installUpdates() triggers POST /updates/install. The backend runs brew upgrade
 * and restarts itself; this store polls /updates/install-status for progress,
 * then polls /health every 2s, reloading the page once the server is back up.
 *
 * anyUpdate is the reactive flag used by AppTopbar to show the update dot.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

interface PackageInfo {
  name: string
  installed: string
  latest: string
  update_available: boolean
  url: string
}

const PHASE_LABELS: Record<string, string> = {
  idle: '',
  upgrading: 'Running brew upgrade… this may take a minute.',
  restarting: 'Upgrade complete — server restarting…',
  done: 'Done! Reloading…',
}

export const useUpdatesStore = defineStore('updates', () => {
  const packages = ref<PackageInfo[]>([])
  const anyUpdate = ref(false)
  const installMethod = ref('')
  const checking = ref(false)
  const installing = ref(false)
  const installMessage = ref('')
  const installPhase = ref('')   // human-readable current phase
  const error = ref('')

  async function checkUpdates(force = false) {
    checking.value = true
    error.value = ''
    try {
      const data = await api.get<{ packages: PackageInfo[]; any_update: boolean; install_method: string }>(`/updates${force ? '?force=true' : ''}`)
      packages.value = data.packages ?? []
      anyUpdate.value = data.any_update ?? false
      installMethod.value = data.install_method ?? ''
    } catch (e: any) {
      error.value = e.message ?? 'Failed to check updates'
    } finally {
      checking.value = false
    }
  }

  async function installUpdates() {
    installing.value = true
    installMessage.value = ''
    installPhase.value = 'Starting upgrade…'
    error.value = ''

    try {
      await api.post<{ message?: string }>('/updates/install', {})
    } catch (e: any) {
      error.value = e.message ?? 'Failed to start upgrade'
      installing.value = false
      installPhase.value = ''
      return
    }

    // Poll /updates/install-status every 2s for phase updates.
    // After the server kills itself (restarting phase), poll /health every 2s.
    // Timeout after 3 minutes total.
    const startedAt = Date.now()
    const TIMEOUT_MS = 3 * 60 * 1000
    let sawRestarting = false

    const statusPoll = setInterval(async () => {
      if (Date.now() - startedAt > TIMEOUT_MS) {
        clearInterval(statusPoll)
        installing.value = false
        installPhase.value = ''
        error.value = 'Upgrade timed out. Please check the server logs.'
        return
      }
      try {
        const s = await api.get<{ status: string }>('/updates/install-status')
        const phase = s.status ?? 'upgrading'
        installPhase.value = PHASE_LABELS[phase] ?? phase
        if (phase === 'restarting' || phase.startsWith('error:')) {
          clearInterval(statusPoll)
          if (phase.startsWith('error:')) {
            error.value = phase.replace('error:', '') || 'Upgrade failed'
            installing.value = false
            installPhase.value = ''
            return
          }
          sawRestarting = true
          // Server is about to kill itself — switch to health polling
          _pollUntilBack()
        }
      } catch {
        // Server went down — it's restarting
        if (!sawRestarting) {
          sawRestarting = true
          clearInterval(statusPoll)
          installPhase.value = 'Server restarting…'
          _pollUntilBack()
        }
      }
    }, 2000)

    function _pollUntilBack() {
      const healthPoll = setInterval(async () => {
        if (Date.now() - startedAt > TIMEOUT_MS) {
          clearInterval(healthPoll)
          installing.value = false
          installPhase.value = ''
          error.value = 'Server did not come back after upgrade. Please restart manually.'
          return
        }
        try {
          await api.get('/health')
          clearInterval(healthPoll)
          installPhase.value = 'Done! Reloading…'
          // Hard-navigate to / so the browser fetches fresh HTML (not cached).
          // window.location.reload() can return a stale index.html whose asset
          // hash no longer matches the new build, causing a blank page.
          setTimeout(() => { window.location.href = '/' }, 1200)
        } catch { /* still restarting */ }
      }, 2000)
    }
  }

  /**
   * Merge update data delivered via the /poll endpoint.
   * Avoids a separate /updates network call when the cache is already warm.
   */
  function mergeFromPoll(pollUpdates: PackageInfo[]) {
    if (!pollUpdates.length && !packages.value.length) return
    packages.value = pollUpdates
    anyUpdate.value = pollUpdates.some(p => p.update_available)
  }

  return { packages, anyUpdate, installMethod, checking, installing, installMessage, installPhase, error, checkUpdates, installUpdates, mergeFromPoll }
})
