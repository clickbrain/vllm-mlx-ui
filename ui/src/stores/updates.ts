// SPDX-License-Identifier: Apache-2.0
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

export const useUpdatesStore = defineStore('updates', () => {
  const packages = ref<PackageInfo[]>([])
  const anyUpdate = ref(false)
  const installMethod = ref('')
  const checking = ref(false)
  const installing = ref(false)
  const installMessage = ref('')
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
    error.value = ''
    try {
      const data = await api.post<{ message?: string }>('/updates/install', {})
      installMessage.value = data.message ?? 'Upgrade started...'
    } catch (e: any) {
      error.value = e.message ?? 'Failed to start upgrade'
      installing.value = false
    }
    // Note: installing stays true — app will restart, page will reload
  }

  return { packages, anyUpdate, installMethod, checking, installing, installMessage, error, checkUpdates, installUpdates }
})
