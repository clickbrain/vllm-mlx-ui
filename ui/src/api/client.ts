/**
 * Minimal HTTP client for the vmUI management API.
 *
 * Base URL:
 *   - Dev:  Vite proxy rewrites /api → http://localhost:8502 (strips prefix).
 *   - Prod: Vue is served directly from mgmt_server on port 8502; no prefix.
 *
 * Authentication:
 *   - Reads X-Api-Key from localStorage (key: vmui_mgmt_api_key).
 *   - Sets `authRequired` ref on 401 so App.vue can show the unlock panel.
 *
 * Error handling:
 *   - Non-2xx responses throw `Error("API error <status>: <path>")`.
 *   - 204 No Content (empty body) resolves to `undefined`.
 *
 * No retry / backoff logic — callers are responsible for retrying if needed.
 * No timeout — use AbortSignal via RequestInit.signal if a deadline is required.
 */

import { ref } from 'vue'

// In dev: Vite proxy rewrites /api → http://localhost:8502 and strips the prefix.
// In production: Vue is served directly from mgmt_server at port 8502, so no prefix needed.
let _base: string = import.meta.env.DEV ? '/api' : ''

/** Get the current API base URL (updated when the active machine changes). */
export function getBase(): string { return _base }

/** Switch the API base URL to target a different machine. */
export function setApiBase(base: string): void { _base = base }

const LS_KEY = 'vmui_mgmt_api_key'

/** Reactive flag — set to true when any API call gets a 401. Cleared by AuthUnlockPanel. */
export const authRequired = ref(false)

/** Read the persisted management API key from localStorage. */
export function getMgmtApiKey(): string {
  return localStorage.getItem(LS_KEY) ?? ''
}

/** Persist (or clear) the management API key in localStorage. */
export function setMgmtApiKey(key: string): void {
  if (key) localStorage.setItem(LS_KEY, key)
  else localStorage.removeItem(LS_KEY)
}

/** Build the X-Api-Key header when a key is configured; returns {} otherwise. */
function authHeaders(): Record<string, string> {
  const key = getMgmtApiKey()
  return key ? { 'X-Api-Key': key } : {}
}

/**
 * Core fetch wrapper. Merges auth headers, checks response status, and
 * parses the response body as JSON (or returns undefined for empty bodies).
 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${_base}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options?.headers as Record<string, string> ?? {}) },
  })
  if (res.status === 401) {
    authRequired.value = true
    throw new Error('AUTH_REQUIRED')
  }
  if (!res.ok) {
    // Try to extract FastAPI's `detail` field for a human-readable message.
    let detail = ''
    try {
      const errBody = await res.json()
      detail = typeof errBody?.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail)
    } catch { /* body wasn't JSON */ }
    throw new Error(detail || `API error ${res.status}: ${path}`)
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** Typed HTTP helpers for the management API. */
export const api = {
  /** GET a JSON resource. Throws on non-2xx or 401. */
  get: <T>(path: string) => request<T>(path),

  /** POST a JSON body. Body is omitted if not provided (useful for trigger endpoints). */
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  /** DELETE a resource by path. */
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}


