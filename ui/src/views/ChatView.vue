<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import { useServerStore } from '@/stores/server'
import AppButton from '@/components/shared/AppButton.vue'

const serverStore = useServerStore()

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const error = ref('')
const messagesEl = ref<HTMLElement | null>(null)

const modelId = computed(() => serverStore.status?.model ?? null)

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true
  error.value = ''
  await scrollToBottom()

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: messages.value.map(m => ({ role: m.role, content: m.content })) })
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json() as { content: string }
    messages.value.push({ role: 'assistant', content: data.content })
  } catch (e) {
    error.value = `Request failed: ${e}`
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
</script>

<template>
  <div class="chat-view">
    <div class="chat-header">
      <h1 class="page-title">Test Chat</h1>
      <div class="chat-meta">
        <span v-if="modelId" class="model-tag">{{ modelId }}</span>
        <span v-else class="model-tag offline">No model loaded</span>
        <AppButton v-if="messages.length" variant="ghost" size="sm" @click="clear">Clear</AppButton>
      </div>
    </div>

    <div class="chat-body">
      <div class="messages" ref="messagesEl">
        <div v-if="!messages.length" class="empty-state">
          <p class="empty-title">Ready to test</p>
          <p class="empty-sub">Send a message to verify your inference endpoint is responding correctly.</p>
        </div>
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="message"
          :class="msg.role"
        >
          <span class="msg-role">{{ msg.role === 'user' ? 'You' : 'Model' }}</span>
          <div class="msg-content">{{ msg.content }}</div>
        </div>
        <div v-if="sending" class="message assistant">
          <span class="msg-role">Model</span>
          <div class="msg-content thinking">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
        </div>
      </div>

      <div v-if="error" class="chat-error">{{ error }}</div>

      <div class="chat-input-wrap">
        <textarea
          v-model="input"
          class="chat-input"
          placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
          rows="3"
          :disabled="sending || !serverStore.isRunning"
          @keydown="onKeydown"
        />
        <AppButton
          variant="primary"
          size="sm"
          class="send-btn"
          :loading="sending"
          :disabled="!input.trim() || !serverStore.isRunning"
          @click="send"
        >Send ↵</AppButton>
      </div>
      <p v-if="!serverStore.isRunning" class="server-warn">Server is not running. Start it from the Serve page first.</p>
    </div>
  </div>
</template>

<style scoped>
.chat-view { display: flex; flex-direction: column; height: 100%; gap: var(--space-4); max-width: 800px; }

.chat-header { display: flex; align-items: center; justify-content: space-between; }
.page-title { font-size: var(--text-lg); font-weight: 700; letter-spacing: -.3px; color: var(--tx-primary); }
.chat-meta { display: flex; align-items: center; gap: var(--space-3); }

.model-tag { font-family: var(--font-mono); font-size: 11.5px; color: var(--tx-tertiary); background: var(--bg-elevated); border: 1px solid var(--bd-default); border-radius: var(--r-pill); padding: 2px 10px; }
.model-tag.offline { color: var(--tx-muted); }

.chat-body { display: flex; flex-direction: column; gap: var(--space-3); flex: 1; min-height: 0; }

.messages {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-height: 320px;
  max-height: 520px;
}

.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: var(--space-2); text-align: center; }
.empty-title { font-size: var(--text-base); font-weight: 600; color: var(--tx-secondary); }
.empty-sub { font-size: 13px; color: var(--tx-muted); max-width: 340px; }

.message { display: flex; flex-direction: column; gap: 4px; }

.msg-role { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--tx-muted); }
.message.assistant .msg-role { color: var(--si-400); }

.msg-content { font-size: var(--text-sm); color: var(--tx-primary); line-height: 1.6; white-space: pre-wrap; }
.message.user .msg-content { color: var(--tx-secondary); }

/* Typing dots */
.thinking { display: flex; align-items: center; gap: 4px; padding: 4px 0; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--tx-muted); animation: blink 1.2s infinite; }
.dot:nth-child(2) { animation-delay: .2s; }
.dot:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }

.chat-error { font-size: 12px; color: var(--cr-500); padding: var(--space-2) var(--space-3); background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.2); border-radius: var(--r-md); }

.chat-input-wrap {
  position: relative;
}
.chat-input {
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  padding: var(--space-3);
  padding-bottom: 44px;
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  color: var(--tx-primary);
  resize: none;
  outline: none;
  transition: border-color var(--transition-fast);
  line-height: 1.5;
  box-sizing: border-box;
}
.chat-input:focus { border-color: var(--bd-focus); }
.chat-input::placeholder { color: var(--tx-muted); }
.chat-input:disabled { opacity: .5; cursor: not-allowed; }

.send-btn {
  position: absolute;
  bottom: var(--space-3);
  right: var(--space-3);
}

.server-warn { font-size: 12px; color: var(--cu-400); }
</style>
