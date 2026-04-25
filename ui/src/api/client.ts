const BASE = '/api'

const LS_KEY = 'vmui_mgmt_api_key'

export function getMgmtApiKey(): string {
  return localStorage.getItem(LS_KEY) ?? ''
}

export function setMgmtApiKey(key: string): void {
  if (key) localStorage.setItem(LS_KEY, key)
  else localStorage.removeItem(LS_KEY)
}

function authHeaders(): Record<string, string> {
  const key = getMgmtApiKey()
  return key ? { 'X-Api-Key': key } : {}
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options?.headers as Record<string, string> ?? {}) },
  })
  if (res.status === 401) throw new Error('AUTH_REQUIRED')
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
