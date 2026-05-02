import type { App } from 'vue'
import { inject } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useMachinesStore } from '@/stores/machines'
import { useUpdatesStore } from '@/stores/updates'

export const SYMBOLS = {
  serverStore: Symbol('serverStore'),
  modelsStore: Symbol('modelsStore'),
  machinesStore: Symbol('machinesStore'),
  updatesStore: Symbol('updatesStore'),
}

export function provideStores(app: App) {
  app.provide(SYMBOLS.serverStore, useServerStore())
  app.provide(SYMBOLS.modelsStore, useModelsStore())
  app.provide(SYMBOLS.machinesStore, useMachinesStore())
  app.provide(SYMBOLS.updatesStore, useUpdatesStore())
}

export function useDI() {
  return {
    serverStore: inject(SYMBOLS.serverStore) as ReturnType<typeof useServerStore>,
    modelsStore: inject(SYMBOLS.modelsStore) as ReturnType<typeof useModelsStore>,
    machinesStore: inject(SYMBOLS.machinesStore) as ReturnType<typeof useMachinesStore>,
    updatesStore: inject(SYMBOLS.updatesStore) as ReturnType<typeof useUpdatesStore>,
  }
}
