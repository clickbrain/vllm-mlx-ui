<script setup lang="ts">
// SPDX-License-Identifier: Apache-2.0
/**
 * ChatView — interactive test chat for the local inference server.
 *
 * Features:
 *  - Streaming & non-streaming modes with AbortController stop button
 *  - Auto-resizing textarea (grows up to 200 px, collapses on send)
 *  - Message hover actions: copy, regenerate (last assistant), edit (user)
 *  - Scroll-to-bottom button; auto-scroll only when already at bottom
 *  - Collapsible system prompt persisted to localStorage
 *  - Token usage display after each response
 *  - Saved chats panel with New Chat (auto-saves current), Save, delete, load
 *  - Per-model inference parameters persisted to localStorage
 *  - Starter prompts in empty state
 *  - Multimodal image/video attachment for MLLM models (auto-detected)
 */
import { ref, computed, watch, nextTick, onMounted, onUnmounted, onActivated, defineOptions } from 'vue'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import { useChatStore } from '@/stores/chat'
import AppButton from '@/components/shared/AppButton.vue'
import MarkdownMessage from '@/components/chat/MarkdownMessage.vue'
import { getBase, api } from '@/api/client'

defineOptions({ name: 'ChatView' })

const serverStore = useServerStore()
const modelsStore = useModelsStore()
const chatStore = useChatStore()

// ── Types ────────────────────────────────────────────────────────────────────

interface EngineInfo {
  id: string
  name: string
  installed: boolean
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  streaming?: boolean
  stopped?: boolean
  /** Base64 data-URLs of images attached to a user message (multimodal only) */
  images?: string[]
}

interface SavedChat {
  id: string
  title: string
  savedAt: number      // created_at (ms)
  messages: Message[]  // may be empty for server-only chats (lazy-loaded)
  model?: string
  engine?: string
  serverSaved?: boolean
}

interface ChatParams {
  temperature: number
  topP: number
  topK: number
  minP: number
  maxTokens: number
  repetitionPenalty: number
  seed: number
  stream: boolean
}

interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

// ── Storage keys ─────────────────────────────────────────────────────────────
const LS_CHATS_KEY    = 'vmui_saved_chats'
const LS_PARAMS_PFX   = 'vmui_chat_params_'
const LS_SYSTEM_KEY   = 'vmui_system_prompt'
const LS_DRAFT_ID_KEY = 'vmui_draft_id'   // stable server-side draft conversation ID

// ── Saved chats ──────────────────────────────────────────────────────────────
function loadSavedChats(): SavedChat[] {
  try { return JSON.parse(localStorage.getItem(LS_CHATS_KEY) ?? '[]') }
  catch { return [] }
}
function persistSavedChats(chats: SavedChat[]) {
  localStorage.setItem(LS_CHATS_KEY, JSON.stringify(chats))
}

// ── Per-model params ─────────────────────────────────────────────────────────
function paramsKey(model: string | null) {
  return LS_PARAMS_PFX + (model ?? '__default__').replace(/\//g, '_')
}
function loadParams(model: string | null): ChatParams {
  try {
    const raw = localStorage.getItem(paramsKey(model))
    if (raw) return JSON.parse(raw) as ChatParams
  } catch {}
  return { temperature: 0.7, topP: 0.9, topK: 0, minP: 0.0, maxTokens: 8192, repetitionPenalty: 1.0, seed: 0, stream: true }
}
function saveParams(model: string | null, params: ChatParams) {
  localStorage.setItem(paramsKey(model), JSON.stringify(params))
}

// ── State ─────────────────────────────────────────────────────────────────────
const messages     = computed(() => chatStore.messages)
const input        = ref('')
const sending      = ref(false)
const error        = ref('')
const autoStarting = ref(false)
const savedChats   = ref<SavedChat[]>(loadSavedChats())
const showParams   = ref(false)
const showAdvanced = ref(false)
const loadingOptimal = ref(false)
const optimalApplied = ref(false)
const taskMode     = ref<'chat'|'code'|'creative'|'analysis'|'precise'>(
  (localStorage.getItem('vmui_task_mode') as 'chat'|'code'|'creative'|'analysis'|'precise') ?? 'chat'
)
const tokenUsage   = ref<TokenUsage | null>(null)

const systemPrompt     = ref(localStorage.getItem(LS_SYSTEM_KEY) ?? '')
const showSystemPrompt = ref(false)

const modelId = computed(() => serverStore.modelId)
const p       = ref<ChatParams>(loadParams(modelId.value))

// ── Engine selector ───────────────────────────────────────────────────────────
const engines          = ref<EngineInfo[]>([])
const selectedEngine   = ref(serverStore.engineId)
const switchingEngine  = ref(false)
const enginesLoadError = ref('')

async function loadEngines() {
  try {
    const result = await api.get<{ engines: EngineInfo[] } | EngineInfo[]>('/engines')
    const all: EngineInfo[] = Array.isArray(result) ? result : (result as any).engines ?? []
    engines.value = all.filter(e => e.installed)
  } catch (e: any) {
    enginesLoadError.value = `${e?.message ?? 'unknown error'}`
  }
}

async function switchEngine(id: string) {
  if (id === serverStore.engineId || switchingEngine.value || modelsStore.serverRestartingFor) return
  selectedEngine.value = id
  switchingEngine.value = true
  try {
    await api.post('/config', { engine_id: id })
    await serverStore.restart()
    // Phase 1: wait for server to go offline (max 10 s)
    let downElapsed = 0
    await new Promise<void>(resolve => {
      const downPoll = setInterval(async () => {
        downElapsed += 1
        await serverStore.fetchStatus()
        if (!serverStore.isRunning || downElapsed >= 10) { clearInterval(downPoll); resolve() }
      }, 1000)
    })
    // Phase 2: wait for server to come back with target engine (max 90 s)
    let upElapsed = 0
    await new Promise<void>(resolve => {
      const upPoll = setInterval(async () => {
        upElapsed += 2
        await serverStore.fetchStatus()
        await serverStore.fetchConfig()
        if ((serverStore.engineId === id && serverStore.isRunning) || upElapsed >= 90) {
          clearInterval(upPoll)
          await serverStore.fetchMetrics()
          await modelsStore.fetchModels()
          resolve()
        }
      }, 2000)
    })
  } catch (e: any) {
    enginesLoadError.value = `Engine switch failed: ${e?.message ?? 'unknown error'}`
    selectedEngine.value = serverStore.engineId  // revert on failure
  } finally {
    switchingEngine.value = false
  }
}

// Keep selectedEngine in sync if something else changes the engine externally
watch(() => serverStore.engineId, (id) => {
  if (!switchingEngine.value) selectedEngine.value = id
})

// Active chat title for the header (set when loading a saved chat)
const activeTitle = ref<string | null>(null)

// AbortController for in-flight streaming requests
let abortCtrl: AbortController | null = null

// ── Multimodal attachment ─────────────────────────────────────────────────────
// Only shown when the loaded model is MLLM (serverStore.isMultimodal).
// Each entry is a base64 data-URL of the dropped/selected file.
const attachedImages = ref<string[]>([])
const imageInputEl = ref<HTMLInputElement | null>(null)

/** Read a File as a base64 data-URL. */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function onImageFiles(files: FileList | null) {
  if (!files) return
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) continue
    const url = await fileToDataUrl(file)
    attachedImages.value.push(url)
  }
}

function onImageInputChange(e: Event) {
  onImageFiles((e.target as HTMLInputElement).files)
}

function removeImage(idx: number) {
  attachedImages.value.splice(idx, 1)
}

/** Handle drag-and-drop images onto the input area (only when multimodal). */
async function onInputDrop(e: DragEvent) {
  if (!serverStore.isMultimodal) return
  e.preventDefault()
  await onImageFiles(e.dataTransfer?.files ?? null)
}

// DOM refs
const messagesEl = ref<HTMLElement | null>(null)
const inputEl    = ref<HTMLTextAreaElement | null>(null)

// Scroll-to-bottom visibility
const isAtBottom = ref(true)

// Copied message index for transient feedback
const copiedIdx = ref<number | null>(null)

// ── Watchers ──────────────────────────────────────────────────────────────────
watch(modelId, (newModel) => { p.value = loadParams(newModel) })
watch(p, (val) => saveParams(modelId.value, val), { deep: true })
watch(systemPrompt, (val) => localStorage.setItem(LS_SYSTEM_KEY, val))

// ── Textarea auto-resize ──────────────────────────────────────────────────────
function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}
function resetInputHeight() {
  if (inputEl.value) inputEl.value.style.height = 'auto'
}

// ── Scroll tracking ───────────────────────────────────────────────────────────
function onMessagesScroll() {
  const el = messagesEl.value
  if (!el) return
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

/**
 * Scroll the message list to the bottom.
 * @param force - if false, only scrolls when already at bottom (non-interrupting)
 */
async function scrollToBottom(force = false) {
  await nextTick()
  const el = messagesEl.value
  if (!el) return
  if (force || isAtBottom.value) {
    el.scrollTop = el.scrollHeight
    isAtBottom.value = true
  }
}

// ── Optimal settings ──────────────────────────────────────────────────────────
async function applyOptimalSettings() {
  if (!modelId.value) return
  loadingOptimal.value = true
  try {
    const params = new URLSearchParams({
      model_id:  modelId.value,
      task_mode: taskMode.value,
      engine_id: serverStore.engineId || '',
    })
    const resp = await fetch(`${getBase()}/models/presets?${params}`)
    if (!resp.ok) throw new Error(`${resp.status}`)
    const data = await resp.json() as {
      recommended?: Record<string, number>
      model_family?: string
      ram_gb?: number
    }
    const rec = data.recommended
    if (rec) {
      // API returns snake_case; map to camelCase ChatParams
      if (rec.temperature        !== undefined) p.value.temperature       = rec.temperature
      if (rec.top_p              !== undefined) p.value.topP              = rec.top_p
      if (rec.top_k              !== undefined) p.value.topK              = rec.top_k
      if (rec.min_p              !== undefined) p.value.minP              = rec.min_p
      if (rec.max_tokens         !== undefined) p.value.maxTokens         = rec.max_tokens
      if (rec.repetition_penalty !== undefined) p.value.repetitionPenalty = rec.repetition_penalty
      // Open params panel so user can see what was applied
      showParams.value = true
      optimalApplied.value = true
      setTimeout(() => { optimalApplied.value = false }, 1800)
      const family = data.model_family ? ` (${data.model_family})` : ''
      const ram    = data.ram_gb       ? `, ${data.ram_gb} GB RAM` : ''
      error.value  = ''
      // Brief info banner — clears after 4 s
      const msg = `Optimal applied for ${taskMode.value} mode${family}${ram}: temp=${rec.temperature?.toFixed(2)} max_tokens=${rec.max_tokens}`
      error.value = msg
      setTimeout(() => { if (error.value === msg) error.value = '' }, 4000)
    }
  } catch (e) {
    error.value = `Could not fetch optimal settings: ${e}`
  } finally {
    loadingOptimal.value = false
  }
}

function setTaskMode(mode: typeof taskMode.value) {
  taskMode.value = mode
  localStorage.setItem('vmui_task_mode', mode)
}

// ── Build API body ────────────────────────────────────────────────────────────
function buildBody(): Record<string, unknown> {
  const systemMsgs = systemPrompt.value.trim()
    ? [{ role: 'system', content: systemPrompt.value.trim() }]
    : []

  // Build messages; user messages with attached images use the OpenAI
  // multipart content array format instead of a plain string.
  const msgList = chatStore.messages
    .filter(m => !m.streaming)
    .map(m => {
      if (m.role === 'user' && m.images?.length) {
        // Vision format: array of image_url + text content parts
        const parts: unknown[] = m.images.map(url => ({
          type: 'image_url',
          image_url: { url },
        }))
        if (m.content) parts.push({ type: 'text', text: m.content })
        return { role: m.role, content: parts }
      }
      return { role: m.role, content: m.content }
    })

  const body: Record<string, unknown> = {
    model:       modelId.value ?? 'default',
    messages: [...systemMsgs, ...msgList],
    stream:              p.value.stream,
    temperature:         p.value.temperature,
    max_tokens:          p.value.maxTokens,
    top_p:               p.value.topP,
  }
  if (p.value.topK > 0)             body.top_k             = p.value.topK
  if (p.value.minP > 0)             body.min_p             = p.value.minP
  if (p.value.repetitionPenalty !== 1.0) body.repetition_penalty = p.value.repetitionPenalty
  if (p.value.seed > 0)             body.seed              = p.value.seed
  return body
}

// ── Non-streaming send ────────────────────────────────────────────────────────
async function sendNonStreaming(body: Record<string, unknown>) {
  abortCtrl = new AbortController()
  const resp = await fetch(`${getBase()}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: abortCtrl.signal,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = await resp.json() as {
    choices: Array<{ message: { content: string; reasoning_content?: string } }>
    usage?: TokenUsage
  }
  const msg = data?.choices?.[0]?.message
  chatStore.addMessage({
    role:      'assistant',
    content:   msg?.content ?? '(no response)',
    reasoning: msg?.reasoning_content || undefined,
  })
  if (data.usage) tokenUsage.value = data.usage
}

// ── Streaming send ────────────────────────────────────────────────────────────
async function sendStreaming(body: Record<string, unknown>) {
  abortCtrl = new AbortController()
  const resp = await fetch(`${getBase()}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: abortCtrl.signal,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  if (!resp.body) throw new Error('Response body is null — streaming not supported')

  chatStore.addMessage({ role: 'assistant', content: '', streaming: true })
  let completionTokens = 0

  const reader  = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    const lines = buf.split('\n')
    buf = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') break
      try {
        const chunk = JSON.parse(payload) as {
          choices: Array<{ delta?: { content?: string; reasoning_content?: string }; finish_reason?: string }>
          usage?: TokenUsage
        }
        const delta = chunk.choices?.[0]?.delta
        if (delta?.reasoning_content) chatStore.updateLastReasoning(delta.reasoning_content)
        if (delta?.content) {
          chatStore.updateLastMessage(delta.content)
          completionTokens++  // approximate chunk count (used only if server omits usage)
          await scrollToBottom()
        }
        if (chunk.usage) tokenUsage.value = chunk.usage
      } catch {}
    }
  }

  chatStore.finalizeLastMessage()
  // If server didn't provide usage, show approximate completion token count
  if (!tokenUsage.value && completionTokens > 0) {
    tokenUsage.value = { prompt_tokens: 0, completion_tokens: completionTokens, total_tokens: completionTokens }
  }
}

// ── Core send logic ───────────────────────────────────────────────────────────
async function sendRequest() {
  if (sending.value) return
  sending.value = true
  error.value   = ''
  tokenUsage.value = null
  await scrollToBottom(true)

  const body = buildBody()
  try {
    if (p.value.stream) {
      await sendStreaming(body)
    } else {
      await sendNonStreaming(body)
    }
    // Save active session as server-side draft after every completed response
    saveDraft()
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      // User stopped — partial message already in store; finalize it as stopped
      chatStore.finalizeLastMessage(true)
      await scrollToBottom()
      sending.value = false
      abortCtrl = null
      // Still save draft so stopped responses are not lost
      saveDraft()
      return
    }
    const msg = String(e)
    if (msg.includes('502') || msg.includes('Load failed') || msg.includes('Failed to fetch')) {
      error.value = 'The inference server is not responding. Make sure it is started on the Serve page.'
    } else {
      error.value = `Request failed: ${msg}`
    }
    // Remove any partial streaming placeholder
    if (chatStore.messages.at(-1)?.streaming) chatStore.popLastMessage()
  } finally {
    sending.value = false
    abortCtrl = null
    await scrollToBottom()
  }
}

// ── Public send (from input) ──────────────────────────────────────────────────
async function send() {
  const text = input.value.trim()
  const images = [...attachedImages.value]
  if (!text && !images.length) return
  if (sending.value || autoStarting.value) return
  if (!serverStore.isRunning) {
    const configModel = serverStore.config?.model ?? serverStore.modelId
    if (!configModel && !modelsStore.models.length) {
      error.value = 'No model loaded. Download and select a model on the Models page first.'
      return
    }
    // Auto-start the inference server then send
    autoStarting.value = true
    error.value = ''
    try {
      await serverStore.startServer()
      // Poll for healthy status up to 90 s
      const TIMEOUT = 90_000
      const POLL_MS = 1_500
      const start = Date.now()
      await new Promise<void>((resolve, reject) => {
        const iv = setInterval(async () => {
          await serverStore.fetchStatus()
          if (serverStore.isRunning && serverStore.status?.healthy) {
            clearInterval(iv)
            resolve()
          } else if (Date.now() - start > TIMEOUT) {
            clearInterval(iv)
            reject(new Error('Server did not become ready in time'))
          }
        }, POLL_MS)
      })
    } catch (e) {
      error.value = `Could not start server: ${e instanceof Error ? e.message : String(e)}`
      autoStarting.value = false
      return
    } finally {
      autoStarting.value = false
    }
  }
  chatStore.addMessage({ role: 'user', content: text, images: images.length ? images : undefined })
  input.value = ''
  attachedImages.value = []
  if (imageInputEl.value) imageInputEl.value.value = ''
  resetInputHeight()
  activeTitle.value = null
  await sendRequest()
}

// ── Stop streaming ────────────────────────────────────────────────────────────
function stopStreaming() {
  abortCtrl?.abort()
}

// ── Regenerate last assistant response ───────────────────────────────────────
async function regenerate() {
  if (sending.value) return
  // Remove last assistant message (keep the user message it responded to)
  if (chatStore.messages.at(-1)?.role === 'assistant') {
    chatStore.popLastMessage()
  }
  await sendRequest()
}

// ── Edit a user message (remove it + everything after, put text in input) ────
function editMessage(index: number) {
  const msg = chatStore.messages[index]
  if (!msg || msg.role !== 'user') return
  input.value = msg.content
  chatStore.removeMessagesFrom(index)
  activeTitle.value = null
  tokenUsage.value  = null
  nextTick(() => {
    inputEl.value?.focus()
    autoResize()
  })
}

// ── Copy a message to clipboard ───────────────────────────────────────────────
async function copyMessage(idx: number, content: string) {
  try {
    await navigator.clipboard.writeText(content)
    copiedIdx.value = idx
    setTimeout(() => { if (copiedIdx.value === idx) copiedIdx.value = null }, 1500)
  } catch { /* clipboard unavailable */ }
}

// ── Keyboard ──────────────────────────────────────────────────────────────────
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    // Allow sending with only an image attached (no text required for vision)
    if (input.value.trim() || attachedImages.value.length) send()
  }
}

// ── Chat management ───────────────────────────────────────────────────────────

// ── Server-side chat sync ────────────────────────────────────────────────────

/** Get or create a stable ID for the current draft (active) session. */
function getDraftId(): string {
  let id = localStorage.getItem(LS_DRAFT_ID_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(LS_DRAFT_ID_KEY, id)
  }
  return id
}

/** Save a conversation to the server. Silently ignores network errors. */
async function serverSaveChat(
  id: string, title: string, messages: Message[], isDraft: boolean, createdAt?: number
) {
  try {
    const body = {
      id,
      title,
      model: modelId.value ?? '',
      engine: serverStore.engineId ?? '',
      is_draft: isDraft,
      created_at: createdAt,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
        reasoning: m.reasoning ?? null,
      })),
    }
    await api.post('/chats', body)
  } catch {
    // Server may be offline — localStorage already has the data
  }
}

/** Delete a conversation from the server. Silently ignores network errors. */
async function serverDeleteChat(id: string) {
  try { await api.delete(`/chats/${id}`) } catch {}
}

/** Fetch all server conversations and merge into savedChats, deduplicating by ID. */
async function loadServerChats() {
  try {
    const data = await api.get('/chats') as { conversations: Array<{
      id: string; title: string; model?: string; engine?: string;
      is_draft: number; created_at: number; updated_at: number; message_count: number
    }> }
    const serverChats: SavedChat[] = (data.conversations ?? [])
      .filter(c => !c.is_draft)  // exclude draft — handled separately
      .map(c => ({
        id: c.id,
        title: c.title,
        savedAt: c.created_at,
        messages: [],            // lazy-loaded on click
        model: c.model,
        engine: c.engine,
        serverSaved: true,
      }))
    // Merge: server is authoritative; keep any localStorage-only chats not on server
    const serverIds = new Set(serverChats.map(c => c.id))
    const localOnly = savedChats.value.filter(c => !serverIds.has(c.id))
    savedChats.value = [...serverChats, ...localOnly]
      .sort((a, b) => b.savedAt - a.savedAt)
    persistSavedChats(savedChats.value)
  } catch {
    // Server offline — use localStorage only
  }
}

/** Save current active messages as the server draft (called after each completion). */
async function saveDraft() {
  const msgs = chatStore.messages.filter(m => !m.streaming)
  if (!msgs.length) return
  const draftId = getDraftId()
  const firstUser = msgs.find(m => m.role === 'user')?.content ?? ''
  const title = firstUser.length > 60 ? firstUser.slice(0, 57) + '…' : firstUser || 'Draft'
  await serverSaveChat(draftId, title, msgs, true)
}

function clear() {
  chatStore.clearMessages()
  tokenUsage.value  = null
  activeTitle.value = null
  error.value = ''
}

/** Save current chat to the saved panel. Returns the generated title. */
async function saveChat(): Promise<string> {
  if (!chatStore.messages.length) return ''
  const firstUser = chatStore.messages.find(m => m.role === 'user')?.content ?? 'Chat'
  const title = firstUser.length > 60 ? firstUser.slice(0, 60) + '…' : firstUser
  // Check if there is already a saved entry with the same title (avoid duplicates from auto-save)
  const chat: SavedChat = {
    id:          crypto.randomUUID(),
    title,
    savedAt:     Date.now(),
    messages:    chatStore.messages.filter(m => !m.streaming).map(m => ({ ...m })),
    model:       modelId.value ?? undefined,
    engine:      serverStore.engineId ?? undefined,
    serverSaved: true,
  }
  savedChats.value.unshift(chat)
  persistSavedChats(savedChats.value)
  await serverSaveChat(chat.id, chat.title, chat.messages, false, chat.savedAt)
  return title
}

/** Start a new chat, auto-saving current if it has messages. */
async function newChat() {
  if (chatStore.messages.length) await saveChat()
  // Delete the old draft from server and issue a new draft ID
  try { await serverDeleteChat(getDraftId()) } catch {}
  localStorage.removeItem(LS_DRAFT_ID_KEY)
  clear()
}

async function loadChat(chat: SavedChat) {
  let messages = chat.messages
  // Lazy-load from server if we only have the summary (no messages cached locally)
  if (!messages.length && chat.serverSaved) {
    try {
      const full = await api.get(`/chats/${chat.id}`) as { messages: Message[] }
      messages = full.messages ?? []
      // Cache locally so repeat clicks don't need a network round-trip
      chat.messages = messages
      persistSavedChats(savedChats.value)
    } catch {
      error.value = 'Could not load chat from server.'
      return
    }
  }
  chatStore.setMessages(messages)
  activeTitle.value = chat.title
  tokenUsage.value  = null
  error.value = ''
  nextTick(() => scrollToBottom(true))
}

async function deleteChat(id: string) {
  savedChats.value = savedChats.value.filter(c => c.id !== id)
  persistSavedChats(savedChats.value)
  await serverDeleteChat(id)
}

// ── Starter prompts ───────────────────────────────────────────────────────────
const STARTER_PROMPTS = [
  'Explain how transformers work in plain English',
  'Write a Python function to find all prime numbers up to N',
  'What are the main differences between REST and GraphQL?',
  'Summarize the key ideas in the paper "Attention Is All You Need"',
]

function useStarterPrompt(prompt: string) {
  input.value = prompt
  nextTick(() => {
    inputEl.value?.focus()
    autoResize()
  })
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  nextTick(() => scrollToBottom(true))
  loadEngines()

  // Load saved chats from server and merge with localStorage
  await loadServerChats()

  // Offer to restore the server-side draft if localStorage active session is empty
  if (!chatStore.messages.length) {
    const draftId = localStorage.getItem(LS_DRAFT_ID_KEY)
    if (draftId) {
      try {
        const draft = await api.get(`/chats/${draftId}`) as { messages: Message[]; title: string }
        if (draft.messages?.length) {
          chatStore.setMessages(draft.messages)
          activeTitle.value = null  // treat as continuation, not a named save
        }
      } catch {
        // Draft not on server yet (e.g. fresh install) — that's fine
      }
    }
  }
})

// When user returns to the Chat tab, scroll to bottom so the latest message is visible
onActivated(() => {
  nextTick(() => scrollToBottom(false))
})

onUnmounted(() => {
  abortCtrl?.abort()
})
</script>

<template>
  <div class="chat-view">
    <!-- ── Main chat area ──────────────────────────────────────────────── -->
    <div class="chat-main">
      <!-- Header -->
      <div class="chat-header">
        <div class="header-left">
          <h1 class="page-title">{{ activeTitle ?? 'Chat' }}</h1>
        </div>
        <div class="header-actions">
          <!-- Engine picker — only shown when multiple engines are installed -->
          <div v-if="engines.length > 1" class="model-picker-wrap">
            <div class="model-picker-label">Engine</div>
            <div class="model-picker-control">
              <select
                class="model-select"
                :value="selectedEngine"
                :disabled="switchingEngine || !!modelsStore.serverRestartingFor || serverStore.loading"
                :title="enginesLoadError || 'Switch inference engine (requires server restart)'"
                @change="(e) => switchEngine((e.target as HTMLSelectElement).value)"
              >
                <option v-for="eng in engines" :key="eng.id" :value="eng.id">
                  {{ eng.name }}
                </option>
              </select>
            </div>
          </div>

          <!-- Model picker -->
          <div v-if="modelsStore.models.length" class="model-picker-wrap">
            <div class="model-picker-label">Model</div>
            <div class="model-picker-control">
              <select
                class="model-select"
                :value="modelId ?? ''"
                :disabled="switchingEngine || !!modelsStore.serverRestartingFor || serverStore.loading"
                @change="(e) => modelsStore.loadModel((e.target as HTMLSelectElement).value)"
              >
                <option value="" disabled>Switch model…</option>
                <option v-for="m in modelsStore.models" :key="m.id" :value="m.id">
                  {{ m.id.split('/').pop() }}
                </option>
              </select>
            </div>
          </div>

          <!-- System prompt toggle -->
          <button
            class="icon-btn"
            :class="{ active: showSystemPrompt || systemPrompt.trim() }"
            title="System prompt"
            @click="showSystemPrompt = !showSystemPrompt"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm1 11H9v-2h2v2zm0-4H9V7h2v2z"/></svg>
          </button>

          <AppButton v-if="messages.length" variant="ghost" size="sm" @click="saveChat" title="Save conversation">
            Save
          </AppButton>
          <AppButton v-if="messages.length" variant="ghost" size="sm" @click="clear" title="Clear without saving">
            Clear
          </AppButton>
        </div>
      </div>

      <!-- Chat body -->
      <div class="chat-body">
        <!-- System prompt (collapsible) -->
        <div v-if="showSystemPrompt" class="system-prompt-bar">
          <div class="system-prompt-label">
            <svg viewBox="0 0 20 20" fill="currentColor" width="11" height="11"><path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm1 11H9v-2h2v2zm0-4H9V7h2v2z"/></svg>
            System Prompt
          </div>
          <textarea
            v-model="systemPrompt"
            class="system-prompt-input"
            placeholder="You are a helpful assistant…"
            rows="3"
          />
        </div>

        <!-- Messages -->
        <div class="messages" ref="messagesEl" @scroll="onMessagesScroll" role="log" aria-label="Chat messages" aria-live="polite">
          <!-- Empty state -->
          <div v-if="!messages.length" class="empty-state">
            <div v-if="!modelId" class="server-warning">
              ⚠ No model loaded — start the server on the Serve page first.
            </div>
            <div v-else>
              <p class="empty-title">Ready to chat</p>
              <p class="empty-sub">Send a message or try one of these:</p>
              <div class="starter-prompts">
                <button
                  v-for="prompt in STARTER_PROMPTS"
                  :key="prompt"
                  class="starter-btn"
                  @click="useStarterPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </div>
          </div>

          <!-- Message list -->
          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="message"
            :class="msg.role"
            :role="msg.role === 'assistant' ? 'article' : undefined"
            :aria-label="msg.role === 'assistant' ? 'Assistant message' : 'Your message'"
          >
            <div class="msg-content" :class="msg.role">
              <!-- Attached images (user messages with multimodal content) -->
              <div v-if="msg.images?.length" class="msg-images">
                <img
                  v-for="(img, imgIdx) in msg.images"
                  :key="imgIdx"
                  :src="img"
                  class="msg-image-thumb"
                  alt="Attached image"
                />
              </div>
              <div class="message-bubble" :class="{ streaming: msg.streaming, stopped: msg.stopped }">
                <MarkdownMessage
                  v-if="msg.role === 'assistant'"
                  :content="msg.content"
                  :reasoning="msg.reasoning"
                  :streaming="!!msg.streaming"
                />
                <span v-else>{{ msg.content }}</span>
                <span v-if="msg.stopped" class="stopped-badge">stopped</span>
              </div>

              <!-- Hover actions -->
              <div class="msg-actions" :class="msg.role">
                <!-- Copy -->
                <button
                  class="action-btn"
                  :title="copiedIdx === i ? 'Copied!' : 'Copy'"
                  @click="copyMessage(i, msg.content)"
                >
                  <svg v-if="copiedIdx !== i" viewBox="0 0 20 20" fill="currentColor" width="12" height="12">
                    <path d="M8 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z"/>
                    <path d="M6 3a2 2 0 00-2 2v11a2 2 0 002 2h8a2 2 0 002-2V5a2 2 0 00-2-2 3 3 0 01-3 3H9a3 3 0 01-3-3z"/>
                  </svg>
                  <svg v-else viewBox="0 0 20 20" fill="currentColor" width="12" height="12">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                  </svg>
                  {{ copiedIdx === i ? 'Copied' : 'Copy' }}
                </button>

                <!-- Regenerate (last assistant only, not streaming) -->
                <button
                  v-if="msg.role === 'assistant' && i === messages.length - 1 && !sending"
                  class="action-btn"
                  title="Regenerate response"
                  @click="regenerate"
                >
                  <svg viewBox="0 0 20 20" fill="currentColor" width="12" height="12">
                    <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/>
                  </svg>
                  Retry
                </button>

                <!-- Edit (user messages only, not streaming) -->
                <button
                  v-if="msg.role === 'user' && !sending"
                  class="action-btn"
                  title="Edit and resend"
                  @click="editMessage(i)"
                >
                  <svg viewBox="0 0 20 20" fill="currentColor" width="12" height="12">
                    <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
                  </svg>
                  Edit
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Scroll to bottom button -->
        <button
          v-if="!isAtBottom && messages.length"
          class="scroll-to-bottom"
          title="Scroll to bottom"
          @click="scrollToBottom(true)"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
            <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>

        <!-- Error banner -->
        <div v-if="error" class="chat-error">
          {{ error }}
          <button class="error-dismiss" @click="error = ''">✕</button>
        </div>

        <!-- Parameters panel -->
        <div class="chat-params">
          <div class="params-toolbar">
            <button class="params-toggle" @click="showParams = !showParams">
              <svg viewBox="0 0 20 20" fill="currentColor" width="12" height="12"><path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"/></svg>
              Parameters
              <svg class="params-chevron" :class="{ open: showParams }" viewBox="0 0 20 20" fill="currentColor" width="12" height="12"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
            </button>

            <label class="stream-toggle" title="Stream tokens as they are generated">
              <input type="checkbox" v-model="p.stream" class="stream-check" />
              <span class="stream-label">Stream</span>
            </label>

            <!-- Task mode selector -->
            <div class="task-mode-group">
              <button
                v-for="m in (['chat','code','creative','analysis','precise'] as const)"
                :key="m"
                class="task-mode-btn"
                :class="{ active: taskMode === m }"
                :title="({
                  chat:     'Chat — Balanced, conversational (temp 0.7). Click Optimal to apply.',
                  code:     'Code — Accurate code generation, low randomness (temp 0.2). Click Optimal to apply.',
                  creative: 'Creative — High diversity for writing and brainstorming (temp 1.0). Click Optimal to apply.',
                  analysis: 'Analysis — Careful, structured reasoning (temp 0.4). Click Optimal to apply.',
                  precise:  'Precise — Factual, minimal responses (temp 0.1). Click Optimal to apply.',
                } as Record<string,string>)[m]"
                @click="setTaskMode(m)"
              >{{ m }}</button>
            </div>

            <button
              class="optimal-btn"
              :class="{ applied: optimalApplied }"
              :disabled="!modelId || loadingOptimal"
              @click="applyOptimalSettings"
              :title="`Apply temperature, top-p, repeat-penalty, and max-tokens tuned for '${taskMode}' tasks with this specific model`"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" width="11" height="11"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>
              {{ loadingOptimal ? 'Loading…' : optimalApplied ? '✓ Applied' : 'Optimal' }}
            </button>

            <!-- Token usage -->
            <span v-if="tokenUsage" class="token-count">
              {{ tokenUsage.prompt_tokens > 0 ? `${tokenUsage.prompt_tokens}↑ ` : '' }}{{ tokenUsage.completion_tokens }}↓ tok
            </span>
          </div>

          <div v-if="showParams" class="params-body">
            <div class="params-row">
              <label class="param-item">
                <span class="param-label">Temp</span>
                <input type="range" v-model.number="p.temperature" min="0" max="2" step="0.05" class="param-range" />
                <span class="param-val">{{ p.temperature.toFixed(2) }}</span>
              </label>
              <label class="param-item">
                <span class="param-label">Top-P</span>
                <input type="range" v-model.number="p.topP" min="0" max="1" step="0.05" class="param-range" />
                <span class="param-val">{{ p.topP.toFixed(2) }}</span>
              </label>
            </div>

            <div class="params-row">
              <label class="param-item">
                <span class="param-label" title="Max output tokens per response. For reasoning models (DeepSeek, Qwen3) set this high (16K+) to allow full thinking chains.">Max output tokens</span>
                <input type="number" v-model.number="p.maxTokens" min="64" max="131072" step="64" class="param-number" />
              </label>
              <label class="param-item">
                <span class="param-label">Rep. penalty</span>
                <input type="range" v-model.number="p.repetitionPenalty" min="1" max="1.5" step="0.01" class="param-range" />
                <span class="param-val">{{ p.repetitionPenalty.toFixed(2) }}</span>
              </label>
            </div>

            <button class="advanced-toggle" @click="showAdvanced = !showAdvanced">
              <span>Advanced</span>
              <svg class="params-chevron" :class="{ open: showAdvanced }" viewBox="0 0 20 20" fill="currentColor" width="11" height="11"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
            </button>

            <div v-if="showAdvanced" class="params-row">
              <label class="param-item">
                <span class="param-label">Top-K</span>
                <input type="number" v-model.number="p.topK" min="0" max="200" step="1" class="param-number" />
                <span class="param-hint">0 = off</span>
              </label>
              <label class="param-item">
                <span class="param-label">Min-P</span>
                <input type="range" v-model.number="p.minP" min="0" max="0.5" step="0.01" class="param-range" />
                <span class="param-val">{{ p.minP.toFixed(2) }}</span>
              </label>
              <label class="param-item">
                <span class="param-label">Seed</span>
                <input type="number" v-model.number="p.seed" min="0" max="9999999" step="1" class="param-number" />
                <span class="param-hint">0 = random</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Input row -->
        <div class="input-row" @dragover.prevent @drop="onInputDrop">
          <!-- Image attachment preview strip (only visible for multimodal models) -->
          <div v-if="serverStore.isMultimodal && attachedImages.length" class="image-preview-strip">
            <div v-for="(img, idx) in attachedImages" :key="idx" class="preview-thumb-wrap">
              <img :src="img" class="preview-thumb" alt="Image to send" />
              <button class="remove-img-btn" title="Remove" @click="removeImage(idx)">×</button>
            </div>
          </div>

          <div class="textarea-wrap">
            <!-- Hidden file input for image selection -->
            <input
              v-if="serverStore.isMultimodal"
              ref="imageInputEl"
              type="file"
              accept="image/*"
              multiple
              style="display:none"
              @change="onImageInputChange"
            />
            <!-- Image attach button — only shown for multimodal (MLLM) models -->
            <button
              v-if="serverStore.isMultimodal"
              class="attach-img-btn"
              title="Attach image(s)"
              :disabled="sending"
              @click="imageInputEl?.click()"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16">
                <rect x="2" y="4" width="16" height="13" rx="2"/>
                <circle cx="7" cy="9" r="1.5"/>
                <path d="M2 14l4-4 3 3 3-4 4 6" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <textarea
              ref="inputEl"
              v-model="input"
              class="chat-input"
              :class="{ 'with-attach': serverStore.isMultimodal }"
              :placeholder="autoStarting ? 'Starting server…' : 'Message… (Enter to send, Shift+Enter for newline)'"
              rows="1"
              :disabled="sending || autoStarting"
              @keydown="onKeydown"
              @input="autoResize"
            />
            <!-- Auto-start spinner -->
            <div v-if="autoStarting" class="autostart-indicator" title="Starting inference server…">
              <svg class="autostart-spinner" viewBox="0 0 16 16" fill="none" width="14" height="14">
                <circle cx="8" cy="8" r="6" stroke="var(--tx-muted)" stroke-width="2" stroke-dasharray="28" stroke-dashoffset="10" />
              </svg>
            </div>
            <!-- Stop button while streaming; Send button otherwise -->
            <button v-if="sending" class="stop-btn" title="Stop generating" @click="stopStreaming">
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                <rect x="5" y="5" width="10" height="10" rx="1"/>
              </svg>
            </button>
            <AppButton
              v-else
              class="send-btn"
              variant="primary"
              size="sm"
              :loading="false"
              :disabled="!input.trim() && !attachedImages.length"
              @click="send"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
              </svg>
            </AppButton>
          </div>
          <p class="input-hint">Enter to send · Shift+Enter for newline<span v-if="serverStore.isMultimodal"> · Drag &amp; drop images</span></p>
        </div>
      </div>
    </div>

    <!-- ── Saved chats panel ──────────────────────────────────────────────── -->
    <aside class="saved-panel">
      <div class="saved-header">
        <span class="saved-title">History</span>
        <span class="saved-count">{{ savedChats.length }}</span>
        <button class="new-chat-btn" title="New chat (auto-saves current)" @click="newChat">
          <svg viewBox="0 0 20 20" fill="currentColor" width="12" height="12"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
          New
        </button>
      </div>
      <div class="saved-list">
        <div v-if="savedChats.length === 0" class="saved-empty">
          No saved chats yet. Start a conversation and click <strong>Save</strong> or <strong>New</strong> to keep it.
        </div>
        <div
          v-for="chat in savedChats"
          :key="chat.id"
          class="saved-item"
        >
          <button class="saved-load-btn" @click="loadChat(chat)">
            <span class="saved-item-title">{{ chat.title }}</span>
            <span class="saved-item-meta">
              {{ chat.messages.length }} msg · {{ new Date(chat.savedAt).toLocaleDateString() }}
            </span>
          </button>
          <button class="saved-delete-btn" @click="deleteChat(chat.id)" title="Delete">✕</button>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
/* ── Layout ─────────────────────────────────────────────────────────────── */
.chat-view {
  display: flex;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-width: 820px;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
  flex-shrink: 0;
  gap: var(--space-3);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  overflow: hidden;
}

.page-title {
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -.3px;
  color: var(--tx-primary);
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  flex-shrink: 0;
}

/* Model/Engine picker — same pattern as Serve page */
.model-picker-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.model-picker-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.model-picker-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.model-select {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 13px;
  padding: 4px 24px 4px 8px;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7280'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 7px center;
  cursor: pointer;
  transition: border-color var(--transition-fast);
  min-width: 120px;
  max-width: 220px;
}
.model-select:focus    { outline: none; border-color: var(--bd-focus); box-shadow: 0 0 0 3px rgba(91, 106, 208, .12); }
.model-select:disabled { opacity: 0.6; cursor: not-allowed; }

/* Small icon button (system prompt toggle) */
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: none;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-muted);
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
  flex-shrink: 0;
}
.icon-btn:hover { color: var(--tx-secondary); border-color: var(--bd-emphasis); }
.icon-btn.active { color: var(--si-300); border-color: var(--ac-border); background: var(--ac-bg); }

/* ── Chat body (flex column holds messages + toolbar + input) ────────────── */
.chat-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
  position: relative;
}

/* ── System prompt bar ──────────────────────────────────────────────────── */
.system-prompt-bar {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
  background: var(--bg-elevated);
}
.system-prompt-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--si-400);
  margin-bottom: var(--space-2);
}
.system-prompt-input {
  width: 100%;
  background: var(--bg-base);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.5;
  padding: var(--space-2) var(--space-3);
  resize: none;
  box-sizing: border-box;
  transition: border-color var(--transition-fast);
}
.system-prompt-input:focus { outline: none; border-color: var(--bd-focus); }

/* ── Messages area ──────────────────────────────────────────────────────── */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── Empty state ────────────────────────────────────────────────────────── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  height: 100%;
  padding: var(--space-8);
  text-align: center;
}

.server-warning {
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: 14px;
  color: var(--cr-300, #f87171);
  max-width: 380px;
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-secondary);
  margin: 0;
}

.empty-sub {
  font-size: var(--text-sm);
  color: var(--tx-muted);
  margin: 0;
}

.starter-prompts {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 400px;
  width: 100%;
}

.starter-btn {
  text-align: left;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-secondary);
  font-size: 14px;
  font-family: inherit;
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
  line-height: 1.4;
}
.starter-btn:hover { border-color: var(--si-500); color: var(--tx-primary); }

/* ── Message bubbles ────────────────────────────────────────────────────── */
.message { display: flex; }
.message.user      { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

/* msg-content wraps bubble + hover actions as a column */
.msg-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 76%;
}
.msg-content.user      { align-items: flex-end; }
.msg-content.assistant { align-items: flex-start; }

.message-bubble {
  padding: 10px var(--space-4);
  border-radius: var(--r-lg);
  font-size: var(--text-sm);
  line-height: 1.5;
  word-break: break-word;
  position: relative;
}

/* User: right-aligned indigo bubble */
.user .message-bubble {
  background: var(--si-600, #4c56b8);
  color: #fff;
  border-bottom-right-radius: var(--r-sm);
  white-space: pre-wrap;  /* preserve user's line breaks */
}

/* Assistant: left-aligned neutral bubble; markdown handles whitespace */
.assistant .message-bubble {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-primary);
  border-bottom-left-radius: var(--r-sm);
  white-space: normal;
}

/* Subtle outline on stopped messages */
.message-bubble.stopped {
  border-color: rgba(249, 115, 22, 0.30);
}

/* Image thumbnails attached to a user message */
.msg-images {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
  justify-content: flex-end;
}
.msg-image-thumb {
  max-width: 220px;
  max-height: 180px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--bd);
  display: block;
}

/* Image preview strip above the input (pending images before send) */
.image-preview-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 2px 4px;
}
.preview-thumb-wrap {
  position: relative;
}
.preview-thumb {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--bd);
  display: block;
}
.remove-img-btn {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--bg3);
  border: 1px solid var(--bd);
  color: var(--tx2);
  font-size: 14px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
}
.remove-img-btn:hover { background: var(--bg4); color: var(--tx1); }

/* Image attach button in input row */
.attach-img-btn {
  position: absolute;
  left: 8px;
  bottom: 8px;
  background: transparent;
  border: none;
  color: var(--tx3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
}
.attach-img-btn:hover { color: var(--tx1); background: var(--bg3); }
.attach-img-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Shift textarea right when attach button is visible */
.chat-input.with-attach {
  padding-left: 36px;
}

/* "(stopped)" label appended to aborted messages */
.stopped-badge {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: #f97316;
  opacity: 0.75;
  vertical-align: middle;
}

/* ── Hover actions ──────────────────────────────────────────────────────── */
.msg-actions {
  display: flex;
  gap: var(--space-1);
  opacity: 0;
  transition: opacity 150ms ease;
}
/* Show on parent .message hover */
.message:hover .msg-actions { opacity: 1; }

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  font-size: 12px;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
  white-space: nowrap;
}
.action-btn:hover { color: var(--tx-secondary); border-color: var(--bd-emphasis); }

/* ── Scroll to bottom button ────────────────────────────────────────────── */
.scroll-to-bottom {
  position: absolute;
  bottom: 140px;  /* above the input area */
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-emphasis);
  border-radius: 50%;
  color: var(--tx-secondary);
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
  transition: background var(--transition-fast), color var(--transition-fast);
  z-index: 10;
}
.scroll-to-bottom:hover { background: var(--bg-surface); color: var(--tx-primary); }

/* ── Error ──────────────────────────────────────────────────────────────── */
.chat-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: 0 var(--space-4) var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: 14px;
  color: var(--cr-300, #f87171);
  flex-shrink: 0;
}
.error-dismiss {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.7;
  flex-shrink: 0;
  padding: 0 2px;
}
.error-dismiss:hover { opacity: 1; }

/* ── Parameters panel ───────────────────────────────────────────────────── */
.chat-params {
  border-top: 1px solid var(--bd-subtle);
  padding: var(--space-2) var(--space-4);
  flex-shrink: 0;
}

.params-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.params-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: none;
  border: none;
  color: var(--tx-muted);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  padding: 2px 0;
  transition: color var(--transition-fast);
}
.params-toggle:hover { color: var(--tx-secondary); }

.params-chevron {
  transition: transform .15s ease;
  color: var(--tx-muted);
}
.params-chevron.open { transform: rotate(180deg); }

.stream-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  margin-left: auto;
}
.stream-check { accent-color: var(--si-500); width: 13px; height: 13px; cursor: pointer; }
.stream-label {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tx-muted);
  user-select: none;
}

/* Task mode selector */
.task-mode-group {
  display: flex;
  gap: 1px;
  background: var(--bd-subtle);
  border-radius: var(--r-sm);
  overflow: hidden;
  flex-shrink: 0;
}
.task-mode-btn {
  padding: 3px 7px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .03em;
  font-family: inherit;
  background: var(--bg-elevated);
  border: none;
  color: var(--tx-muted);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  text-transform: capitalize;
  white-space: nowrap;
}
.task-mode-btn:hover { background: var(--bg-inset); color: var(--tx-secondary); }
.task-mode-btn.active {
  background: var(--bg-inset);
  color: var(--si-300);
}

.optimal-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  font-size: 13px;
  font-family: inherit;
  font-weight: 500;
  color: var(--tx-secondary);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
}
.optimal-btn:hover:not(:disabled) { border-color: var(--si-500); color: var(--si-300); }
.optimal-btn:disabled { opacity: .4; cursor: default; }
.optimal-btn.applied { border-color: var(--cu-500); color: var(--cu-300); }

/* Token count indicator */
.token-count {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--tx-muted);
  margin-left: auto;
  white-space: nowrap;
}

.params-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-3);
}

.params-row {
  display: flex;
  gap: var(--space-5);
  flex-wrap: wrap;
}

.param-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 180px;
}

.param-label {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
  color: var(--tx-muted);
  width: 76px;
  flex-shrink: 0;
}

.param-range {
  flex: 1;
  accent-color: var(--si-500);
  height: 3px;
}

.param-val {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--tx-secondary);
  width: 36px;
  text-align: right;
}

.param-number {
  width: 90px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: 14px;
  padding: 3px 8px;
}

.param-hint {
  font-size: 12.5px;
  color: var(--tx-muted);
  white-space: nowrap;
}

.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  font-size: 13px;
  font-family: inherit;
  color: var(--tx-muted);
  cursor: pointer;
  padding: 2px 0;
  transition: color var(--transition-fast);
}
.advanced-toggle:hover { color: var(--tx-secondary); }

/* ── Input area ─────────────────────────────────────────────────────────── */
.input-row {
  padding: var(--space-3);
  border-top: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.textarea-wrap {
  position: relative;
}

.chat-input {
  width: 100%;
  min-height: 40px;
  max-height: 200px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.5;
  padding: 10px 52px 10px var(--space-3);
  resize: none;
  box-sizing: border-box;
  overflow-y: auto;
  transition: border-color var(--transition-fast);
}
.chat-input::placeholder { color: var(--tx-muted); }
.chat-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}
.chat-input:disabled { opacity: 0.65; cursor: not-allowed; }

.autostart-indicator {
  position: absolute;
  right: var(--space-3);
  bottom: 8px;
  display: flex;
  align-items: center;
}
.autostart-spinner {
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.send-btn, .stop-btn {
  position: absolute;
  right: var(--space-3);
  bottom: 8px;
}

/* Stop button — square red-tinted style */
.stop-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  background: rgba(239, 68, 68, .10);
  border: 1px solid rgba(239, 68, 68, .35);
  border-radius: var(--r-md);
  color: var(--cr-300, #f87171);
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.stop-btn:hover {
  background: rgba(239, 68, 68, .18);
  border-color: rgba(239, 68, 68, .55);
}

.input-hint {
  font-size: 12px;
  color: var(--tx-muted);
  margin: 4px 0 0;
  text-align: right;
  opacity: 0.6;
}

/* ── Saved panel ────────────────────────────────────────────────────────── */
.saved-panel {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.saved-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.saved-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--si-400);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.saved-title::before {
  content: '';
  display: block;
  width: 3px;
  height: 11px;
  background: var(--si-500);
  border-radius: 2px;
  flex-shrink: 0;
}

.saved-count {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--tx-muted);
}

/* "New chat" button in the saved panel header */
.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 3px 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  font-size: 12px;
  font-family: inherit;
  font-weight: 600;
  color: var(--tx-secondary);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
}
.new-chat-btn:hover { border-color: var(--si-500); color: var(--si-300); }

.saved-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2) 0;
}

.saved-empty {
  padding: var(--space-4);
  font-size: 14px;
  color: var(--tx-muted);
  line-height: 1.5;
  text-align: center;
}
.saved-empty strong { color: var(--tx-secondary); font-weight: 600; }

.saved-item {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--bd-subtle);
}
.saved-item:last-child { border-bottom: none; }

.saved-load-btn {
  flex: 1;
  text-align: left;
  background: none;
  border: none;
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-radius: 0;
  transition: background var(--transition-fast);
  min-width: 0;
}
.saved-load-btn:hover { background: var(--bg-elevated); }

.saved-item-title {
  font-size: 14px;
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.saved-item-meta {
  font-size: 12.5px;
  color: var(--tx-muted);
  font-family: var(--font-mono);
}

.saved-delete-btn {
  background: none;
  border: none;
  color: var(--tx-muted);
  cursor: pointer;
  padding: 0 var(--space-2);
  font-size: 13px;
  transition: color var(--transition-fast);
  flex-shrink: 0;
}
.saved-delete-btn:hover { color: var(--cr-300, #f87171); }
</style>
