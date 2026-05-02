import type { App } from 'vue'
import type { InjectionKey } from 'vue'
import { inject } from 'vue'
import type { Pinia } from 'pinia'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useMachinesStore } from '@/stores/machines'
import { useUpdatesStore } from '@/stores/updates'

export const SYMBOLS: Record<string, InjectionKey<unknown>> = {
  serverStore: Symbol('serverStore') as InjectionKey<ReturnType<typeof useServerStore>>,
  modelsStore: Symbol('modelsStore') as InjectionKey<ReturnType<typeof useModelsStore>>,
  machinesStore: Symbol('machinesStore') as InjectionKey<ReturnType<typeof useMachinesStore>>,
  updatesStore: Symbol('updatesStore') as InjectionKey<ReturnType<typeof useUpdatesStore>>,
}

export function provideStores(app: App) {
  app.provide(SYMBOLS.serverStore, useServerStore())
  app.provide(SYMBOLS.modelsStore, useModelsStore())
  app.provide(SYMBOLS.machinesStore, useMachinesStore())
  app.provide(SYMBOLS.updatesStore, useUpdatesStore())
}

export function useDI() {
  return {
    serverStore: inject(SYMBOLS.serverStore),
    modelsStore: inject(SYMBOLS.modelsStore),
    machinesStore: inject(SYMBOLS.machinesStore),
    updatesStore: inject(SYMBOLS.updatesStore),
  }
}
