// SPDX-License-Identifier: Apache-2.0
/**
 * Chat store — manages the active conversation.
 *
 * Persistence: the active message list is saved to localStorage on every
 * mutation so it survives page refreshes. Saved/named chats are managed
 * separately in ChatView.vue under LS_CHATS_KEY.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  streaming?: boolean
  stopped?: boolean  // true when generation was aborted mid-stream
}

const LS_SESSION_KEY = 'vmui_active_session'

function loadSession(): Message[] {
  try {
    const raw = localStorage.getItem(LS_SESSION_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Message[]
    // Strip any partially-streamed messages that were interrupted
    return parsed.filter(m => !m.streaming)
  } catch { return [] }
}

function saveSession(msgs: Message[]) {
  try {
    localStorage.setItem(LS_SESSION_KEY, JSON.stringify(msgs.filter(m => !m.streaming)))
  } catch { /* quota exceeded — ignore */ }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>(loadSession())

  function clearMessages() {
    messages.value = []
    saveSession([])
  }

  function addMessage(msg: Message) {
    messages.value.push({ ...msg })
    if (!msg.streaming) saveSession(messages.value)
  }

  function updateLastMessage(delta: string) {
    const last = messages.value.at(-1)
    if (last) last.content += delta
    // Don't persist every streaming token — save on finalize
  }

  function updateLastReasoning(delta: string) {
    const last = messages.value.at(-1)
    if (last) last.reasoning = (last.reasoning ?? '') + delta
  }

  function setMessages(msgs: Message[]) {
    messages.value = msgs.map(m => ({ ...m }))
    saveSession(messages.value)
  }

  /** Remove the message at `index` and everything after it (for edit-and-resend). */
  function removeMessagesFrom(index: number) {
    messages.value = messages.value.slice(0, index)
    saveSession(messages.value)
  }

  /** Remove the last message (for regenerate). */
  function popLastMessage() {
    messages.value = messages.value.slice(0, -1)
    saveSession(messages.value)
  }

  /** Mark the last message as stopped (aborted mid-stream). */
  function finalizeLastMessage(stopped = false) {
    const last = messages.value.at(-1)
    if (last) {
      last.streaming = false
      if (stopped) last.stopped = true
    }
    saveSession(messages.value)
  }

  return {
    messages,
    clearMessages,
    addMessage,
    updateLastMessage,
    updateLastReasoning,
    finalizeLastMessage,
    setMessages,
    removeMessagesFrom,
    popLastMessage,
  }
})
