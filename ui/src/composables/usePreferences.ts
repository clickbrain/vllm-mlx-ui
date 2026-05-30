/**
 * User preference singletons — persisted to localStorage.
 *
 * Module-level refs (not re-created per caller) so all components
 * share the same reactive state.
 */

import { ref, watch } from 'vue'

export type UseCase = 'chat' | 'code' | 'reasoning' | 'vision'
export type QualityPreference = 'fast' | 'balanced' | 'quality'

// ── Storage keys ────────────────────────────────────────────────────────────
const KEY_USE_CASE     = 'vmui_use_case'
const KEY_QUALITY      = 'vmui_quality_pref'
const KEY_MAX_AGE      = 'vmui_max_age_months'
const KEY_AGE_MIGRATED = 'vmui_age_migrated_v1'

// ── Singleton refs ────────────────────────────────────────────────────────────

function readUseCase(): UseCase | null {
  const v = localStorage.getItem(KEY_USE_CASE)
  return (['chat', 'code', 'reasoning', 'vision'] as UseCase[]).includes(v as UseCase)
    ? (v as UseCase)
    : null
}

function readQuality(): QualityPreference {
  const v = localStorage.getItem(KEY_QUALITY)
  return (['fast', 'balanced', 'quality'] as QualityPreference[]).includes(v as QualityPreference)
    ? (v as QualityPreference)
    : 'balanced'
}

function readMaxAge(): number {
  const raw = localStorage.getItem(KEY_MAX_AGE)
  const v = parseInt(raw ?? '', 10)
  if (!Number.isFinite(v) || v < 0) return 0
  // One-time migration: 18 was the old default and silently hid many valid models.
  // Migrate existing users once; after this flag is set, deliberate "18 month"
  // selections are respected on future reloads.
  if (v === 18 && !localStorage.getItem(KEY_AGE_MIGRATED)) {
    localStorage.setItem(KEY_AGE_MIGRATED, '1')
    return 0
  }
  return v
}

export const selectedUseCase  = ref<UseCase | null>(readUseCase())
export const qualityPreference = ref<QualityPreference>(readQuality())
export const maxAgeMonths      = ref<number>(readMaxAge())

// Persist changes immediately
watch(selectedUseCase,  v => {
  if (v == null) localStorage.removeItem(KEY_USE_CASE)
  else           localStorage.setItem(KEY_USE_CASE, v)
})
watch(qualityPreference, v => localStorage.setItem(KEY_QUALITY, v))
watch(maxAgeMonths,      v => localStorage.setItem(KEY_MAX_AGE, String(v)))

/** Composable function for components that need full preference state. */
export function usePreferences() {
  return { selectedUseCase, qualityPreference, maxAgeMonths }
}
