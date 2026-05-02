# Phase 5.1: Refactor Global State to Dependency Injection

## Goal
Replace direct Pinia store imports with a Dependency Injection (DI) container to:
- Decouple components from specific store implementations
- Enable easier testing with mocked dependencies
- Prepare for potential migration to other state management solutions

## Current State
Components directly import stores:
```typescript
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
// Used in setup() or <script setup>
const serverStore = useServerStore()
```

## Proposed Architecture

### 1. Create DI Container
`ui/src/di/container.ts`:
```typescript
import type { App } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useMachinesStore } from '@/stores/machines'

interface Dependencies {
  serverStore: ReturnType<typeof useServerStore>
  modelsStore: ReturnType<typeof useModelsStore>
  machinesStore: ReturnType<typeof useMachinesStore>
  // Add more as needed
}

const SYMBOLS = {
  serverStore: Symbol('serverStore'),
  modelsStore: Symbol('modelsStore'),
  machinesStore: Symbol('machinesStore'),
}

export function provideDependencies(app: App) {
  app.provide(SYMBOLS.serverStore, useServerStore())
  app.provide(SYMBOLS.modelsStore, useModelsStore())
  app.provide(SYMBOLS.machinesStore, useMachinesStore())
}

export function injectDependencies(): Dependencies {
  const app = getCurrentInstance()?.appContext.app
  if (!app) throw new Error('No app context')

  return {
    serverStore: app.config.globalProperties.$serverStore,
    modelsStore: app.config.globalProperties.$modelsStore,
    machinesStore: app.config.globalProperties.$machinesStore,
  }
}
```

### 2. Plugin Alternative (Simpler)
`ui/src/plugins/stores.ts`:
```typescript
import { Plugin } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'

export const storePlugin: Plugin = {
  install(app) {
    app.config.globalProperties.$serverStore = useServerStore()
    app.config.globalProperties.$modelsStore = useModelsStore()
  }
}
```

### 3. Migration Path
1. Create plugin/container
2. Register in `main.ts`
3. Gradually migrate components (one store at a time)
4. Keep old imports working during transition
5. Update tests to use DI

## Benefits
- Components become more testable
- Clear dependency graph
- Easier to swap implementations
- Better TypeScript inference

## Risks
- Breaking change for existing components
- Need to maintain backward compatibility during migration
- Additional abstraction layer

## Timeline Estimate
- Week 1: Create DI infrastructure, migrate 2-3 stores
- Week 2: Complete migration, update all tests, remove old pattern

## Decision Needed
Choose one approach:
A) **Pinia + Provide/Inject** (Recommended) - Lightweight, uses Vue's built-in DI
B) **InversifyJS** - Full DI container, heavier but more features
C) **tsyringe** - Decorator-based DI, requires experimental decorators
D) **Manual container** - Custom implementation, full control

**Recommendation:** Option A - stays within Vue ecosystem, minimal new dependencies.
