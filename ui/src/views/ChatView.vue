<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useServerStore } from '@/stores/server'
import { api } from '@/api/client'
import AppButton from '@/components/shared/AppButton.vue'

const serverStore = useServerStore()

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface SavedChat {
  id: string
  title: string
  savedAt: number
  messages: Message[]
}

const LS_KEY = 'vmui_saved_chats'

function loadSavedChats(): SavedChat[] {
  try { return JSON.parse(localStorage.getItem(LS_KEY) ?? '[]') }
  catch { return [] }
}

function persistSavedChats(chats: SavedChat[]) {
  localStorage.setItem(LS_KEY, JSON.stringify(chats))
}

const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const error = ref('')
const messagesEl = ref<HTMLElement | null>(null)
const savedChats = ref<SavedChat[]>(loadSavedChats())

const modelId = computed(() => serverStore.modelId)

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return

  if (!serverStore.isRunning) {
    error.value = 'The inference server is not running. Start it on the Serve page first.'
    return
  }

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true
  error.value = ''
  await scrollToBottom()

  try {
    const body = {
      model: modelId.value ?? 'default',
      messages: messages.value.map(m => ({ role: m.role, content: m.content })),
      stream: false,
    }
    const data = await api.post<{ choices: Array<{ message: { content: string } }> }>(
      '/v1/chat/completions',
      body
    )
    const reply = data?.choices?.[0]?.message?.content ?? '(no response)'
    messages.value.push({ role: 'assistant', content: reply })
  } catch (e) {
    const msg = String(e)
    if (msg.includes('502') || msg.includes('Load failed')) {
      error.value = 'The inference server is not responding. Make sure it is started on the Serve page.'
    } else {
      error.value = `Request failed: ${msg}`
    }
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
}

function clear() { messages.value = []; error.value = '' }

function saveChat() {
  if (!messages.value.length) return
  const firstUser = messages.value.find(m => m.role === 'user')?.content ?? 'Chat'
  const title = firstUser.length > 50 ? firstUser.slice(0, 50) + '…' : firstUser
  const chat: SavedChat = {
    id: crypto.randomUUID(),
    title,
    savedAt: Date.now(),
    messages: [...messages.value],
  }
  savedChats.value.unshift(chat)
  persistSavedChats(savedChats.value)
}

function loadChat(chat: SavedChat) {
  messages.value = [...chat.messages]
  error.value = ''
  nextTick(() => scrollToBottom())
}

function deleteChat(id: string) {
  savedChats.value = savedChats.value.filter(c => c.id !== id)
  persistSavedChats(savedChats.value)
}
</script>

<template>
  <div class="chat-view">
    <!-- Main chat area -->
    <div class="chat-main">
      <div class="chat-header">
        <h1 class="page-title">Test Chat</h1>
        <div class="chat-meta">
          <span class="model-tag" :class="{ offline: !modelId }">
            {{ modelId ?? 'No model loaded' }}
          </span>
          <AppButton v-if="messages.length" variant="ghost" size="sm" @click="saveChat" title="Save this conversation">
            Save
          </AppButton>
          <AppButton v-if="messages.length" variant="ghost" size="sm" @click="clear">Clear</AppButton>
        </div>
      </div>

      <div class="chat-body">
        <div class="messages" ref="messagesEl">
          <div v-if="!messages.length" class="empty-state">
            <div v-if="!modelId" class="server-warning">
              ⚠ No model loaded — start the server on the Serve page first.
            </div>
            <p class="empty-title">Ready to test</p>
            <p class="empty-sub">Send a message to verify your inference endpoint is responding correctly.</p>
          </div>
          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="message"
            :class="msg.role"
          >
            <div class="message-bubble">{{ msg.content }}</div>
          </div>
        </div>

        <div v-if="error" class="chat-error">{{ error }}</div>

        <div class="input-row">
          <div class="textarea-wrap">
            <textarea
              v-model="input"
              class="chat-input"
              placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
              rows="3"
              @keydown="onKeydown"
            />
            <AppButton
              class="send-btn"
              variant="primary"
              size="sm"
              :loading="sending"
              :disabled="!input.trim()"
              @click="send"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
              </svg>
            </AppButton>
          </div>
        </div>
      </div>
    </div>

    <!-- Saved chats sidebar -->
    <aside class="saved-panel">
      <div class="saved-header">
        <span class="saved-title">Saved</span>
        <span class="saved-count">{{ savedChats.length }}</span>
      </div>
      <div class="saved-list">
        <div v-if="savedChats.length === 0" class="saved-empty">
          No saved chats yet. Save a conversation to access it here.
        </div>
        <div
          v-for="chat in savedChats"
          :key="chat.id"
          class="saved-item"
        >
          <button class="saved-load-btn" @click="loadChat(chat)">
            <span class="saved-item-title">{{ chat.title }}</span>
            <span class="saved-item-meta">{{ new Date(chat.savedAt).toLocaleDateString() }}</span>
          </button>
          <button class="saved-delete-btn" @click="deleteChat(chat.id)" title="Delete">✕</button>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
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
  max-width: 800px;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
  flex-shrink: 0;
}

.page-title {
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -.3px;
  color: var(--tx-primary);
}

.chat-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.model-tag {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--si-300);
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  border-radius: var(--r-pill);
  padding: 2px 10px;
}
.model-tag.offline { color: var(--tx-muted); background: var(--bg-elevated); border-color: var(--bd-default); }

.chat-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 100%;
  padding: var(--space-8);
  text-align: center;
}

.server-warning {
  padding: var(--space-2) var(--space-4);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: 12px;
  color: var(--cr-300, #f87171);
  text-align: center;
  width: 100%;
  max-width: 380px;
}

.empty-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--tx-secondary);
}

.empty-sub {
  font-size: var(--text-sm);
  color: var(--tx-muted);
  line-height: 1.5;
  max-width: 320px;
}

.message { display: flex; }
.message.user { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.message-bubble {
  max-width: 72%;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--r-lg);
  font-size: var(--text-sm);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.user .message-bubble {
  background: var(--si-600, #4c56b8);
  color: #fff;
  border-bottom-right-radius: var(--r-sm);
}

.assistant .message-bubble {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-primary);
  border-bottom-left-radius: var(--r-sm);
}

.chat-error {
  margin: 0 var(--space-4) var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: rgba(239, 68, 68, .08);
  border: 1px solid rgba(239, 68, 68, .25);
  border-radius: var(--r-md);
  font-size: 12px;
  color: var(--cr-300, #f87171);
  flex-shrink: 0;
}

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
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.5;
  padding: var(--space-3) 52px var(--space-3) var(--space-3);
  resize: none;
  box-sizing: border-box;
  transition: border-color var(--transition-fast);
}
.chat-input::placeholder { color: var(--tx-muted); }
.chat-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.send-btn {
  position: absolute;
  right: var(--space-3);
  bottom: var(--space-3);
}

/* Saved chats sidebar */
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
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.saved-title {
  font-size: 10px;
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
}

.saved-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--tx-muted);
}

.saved-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2) 0;
}

.saved-empty {
  padding: var(--space-4);
  font-size: 12px;
  color: var(--tx-muted);
  line-height: 1.5;
  text-align: center;
}

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
}
.saved-load-btn:hover { background: var(--bg-elevated); }

.saved-item-title {
  font-size: 12px;
  color: var(--tx-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
  display: block;
}

.saved-item-meta {
  font-size: 10.5px;
  color: var(--tx-muted);
  font-family: var(--font-mono);
}

.saved-delete-btn {
  background: none;
  border: none;
  color: var(--tx-muted);
  cursor: pointer;
  padding: 0 var(--space-2);
  font-size: 11px;
  transition: color var(--transition-fast);
  flex-shrink: 0;
}
.saved-delete-btn:hover { color: var(--cr-300, #f87171); }
</style>
