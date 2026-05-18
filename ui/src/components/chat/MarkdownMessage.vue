<!--
  MarkdownMessage — renders markdown text as sanitised HTML with code highlighting.

  Converts raw markdown (from LLM responses) using `marked`, then sanitises
  via DOMPurify to prevent XSS before inserting as innerHTML. Syntax
  highlighting is applied client-side via highlight.js after DOM insertion.

  Props:
  - content: raw markdown string to render

  Note: renders lazily — watchEffect re-renders only when content changes.
-->
<script setup lang="ts">
import { ref, watchEffect, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import js from 'highlight.js/lib/languages/javascript'
import ts from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import rust from 'highlight.js/lib/languages/rust'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import cpp from 'highlight.js/lib/languages/cpp'
import c from 'highlight.js/lib/languages/c'

hljs.registerLanguage('javascript', js)
hljs.registerLanguage('js', js)
hljs.registerLanguage('typescript', ts)
hljs.registerLanguage('ts', ts)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('go', go)
hljs.registerLanguage('java', java)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('c', c)

marked.use({
  breaks: false,  // don't convert single newlines to <br> — reduces spurious line breaks
  gfm: true,
})

/** Normalize model markdown before parsing to prevent loose lists */
function tightenMarkdown(md: string): string {
  return md
    // Collapse 3+ blank lines → 1
    .replace(/\n{3,}/g, '\n\n')
    // Collapse blank line between consecutive bullet items
    .replace(/(\n[ \t]*[*\-+] [^\n]+)\n\n(?=[ \t]*[*\-+] )/g, '$1\n')
    // Collapse blank line between consecutive numbered items
    .replace(/(\n[ \t]*\d+[.)][^\n]+)\n\n(?=[ \t]*\d+[.)])/g, '$1\n')
}

const props = defineProps<{
  content: string
  reasoning?: string
  streaming: boolean
}>()

const containerRef = ref<HTMLElement | null>(null)
const renderedHtml = ref('')
const reasoningHtml = ref('')
const reasoningOpen = ref(false)

watchEffect(async () => {
  if (props.reasoning) {
    const raw = String(marked.parse(props.reasoning))
    reasoningHtml.value = DOMPurify.sanitize(raw, { ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'pre'] })
  } else {
    reasoningHtml.value = ''
  }
})

watchEffect(async () => {
  let raw = String(marked.parse(tightenMarkdown(props.content)))
  // Strip <p> wrappers from inside <li> — marked wraps loose list items in <p>
  // tags which adds huge gaps between bullets. This is the most reliable fix.
  raw = raw.replace(/<li>\s*<p>/g, '<li>').replace(/<\/p>\s*<\/li>/g, '</li>')
  renderedHtml.value = DOMPurify.sanitize(raw, {
    ADD_TAGS: ['svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'text', 'g', 'defs', 'use', 'clipPath', 'linearGradient', 'stop', 'animate', 'animateTransform'],
    ADD_ATTR: ['viewBox', 'd', 'fill', 'stroke', 'stroke-width', 'cx', 'cy', 'r', 'x', 'y', 'width', 'height', 'transform', 'xmlns', 'class', 'style', 'opacity', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2', 'points', 'offset', 'stop-color', 'gradientUnits', 'id', 'clip-path', 'dur', 'repeatCount', 'from', 'to', 'attributeName'],
  })

  await nextTick()

  if (!containerRef.value) return

  // Make all links open in new tab
  containerRef.value.querySelectorAll('a').forEach(a => {
    a.setAttribute('target', '_blank')
    a.setAttribute('rel', 'noopener noreferrer')
  })

  // Highlight code blocks and add copy buttons
  containerRef.value.querySelectorAll('pre').forEach(pre => {
    const codeEl = pre.querySelector('code')
    if (!codeEl) return

    // Highlight if not already done
    if (!codeEl.dataset.highlighted) {
      hljs.highlightElement(codeEl)
    }

    // Add code header with language label + copy button (once only)
    if (pre.querySelector('.code-header')) return

    const langMatch = codeEl.className.match(/language-(\w+)/)
    const lang = langMatch ? langMatch[1] : ''

    const header = document.createElement('div')
    header.className = 'code-header'

    const langLabel = document.createElement('span')
    langLabel.className = 'code-lang'
    langLabel.textContent = lang
    header.appendChild(langLabel)

    const copyBtn = document.createElement('button')
    copyBtn.className = 'copy-btn'
    copyBtn.textContent = 'Copy'
    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(codeEl.textContent ?? '')
        copyBtn.textContent = 'Copied!'
        setTimeout(() => { copyBtn.textContent = 'Copy' }, 1500)
      } catch {
        copyBtn.textContent = 'Failed'
        setTimeout(() => { copyBtn.textContent = 'Copy' }, 1500)
      }
    })
    header.appendChild(copyBtn)

    pre.insertBefore(header, codeEl)
  })

  // ── HTML live preview (only after streaming completes) ────────────────────
  if (!props.streaming) {
    containerRef.value.querySelectorAll('pre').forEach(pre => {
      const codeEl = pre.querySelector('code.language-html, code.language-htm')
      if (!codeEl) return
      if (pre.querySelector('.preview-btn')) return  // already wired up

      const htmlContent = codeEl.textContent ?? ''
      if (htmlContent.trim().length < 50) return

      const header = pre.querySelector('.code-header')
      if (!header) return

      // ── Preview toggle button ──────────────────────────────────────────────
      const previewBtn = document.createElement('button')
      previewBtn.className = 'preview-btn'
      previewBtn.setAttribute('aria-label', 'Toggle live HTML preview')

      // ── Iframe preview wrapper ─────────────────────────────────────────────
      const wrapper = document.createElement('div')
      wrapper.className = 'html-preview-wrapper'

      // Controls bar: size presets + open-in-new-tab
      const controlsBar = document.createElement('div')
      controlsBar.className = 'html-preview-controls'

      const sizeLabel = document.createElement('span')
      sizeLabel.className = 'preview-size-label'
      sizeLabel.textContent = 'Height:'
      controlsBar.appendChild(sizeLabel)

      const iframe = document.createElement('iframe')
      iframe.className = 'html-preview-iframe'
      // allow-scripts without allow-same-origin gives the iframe an opaque
      // origin so it cannot read the app's localStorage or cookies.
      // allow-pointer-lock enables mouse-lock for games.
      iframe.setAttribute('sandbox', 'allow-scripts allow-pointer-lock')
      iframe.setAttribute('allowfullscreen', '')

      const heights: Array<[string, number]> = [
        ['S', 300], ['M', 500], ['L', 700], ['Full', 900],
      ]
      heights.forEach(([label, h]) => {
        const btn = document.createElement('button')
        btn.className = 'size-btn' + (h === 500 ? ' active' : '')
        btn.textContent = label
        btn.addEventListener('click', () => {
          iframe.style.height = h + 'px'
          controlsBar.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'))
          btn.classList.add('active')
        })
        controlsBar.appendChild(btn)
      })

      // "Open" button — wraps the HTML in a sandboxed shell to prevent the
      // Blob URL (same-origin) from accessing the app's localStorage/cookies.
      const openBtn = document.createElement('button')
      openBtn.className = 'preview-open-btn'
      openBtn.textContent = '⤢ Open'
      openBtn.title = 'Open in new tab'
      openBtn.addEventListener('click', () => {
        const shell = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0}html,body,iframe{width:100%;height:100%;border:none;display:block;background:#fff}</style></head><body><iframe sandbox="allow-scripts allow-pointer-lock" srcdoc=${JSON.stringify(htmlContent)}></iframe></body></html>`
        const blob = new Blob([shell], { type: 'text/html' })
        const url = URL.createObjectURL(blob)
        window.open(url, '_blank', 'noopener,noreferrer')
        setTimeout(() => URL.revokeObjectURL(url), 60_000)
      })
      controlsBar.appendChild(openBtn)

      wrapper.appendChild(controlsBar)
      wrapper.appendChild(iframe)
      pre.after(wrapper)

      let previewVisible = false

      function openPreview() {
        if (!iframe.srcdoc) iframe.srcdoc = htmlContent  // lazy-load
        wrapper.style.display = 'block'
        pre.style.display = 'none'
        previewBtn.textContent = '{ } Code'
        previewVisible = true
      }
      function closePreview() {
        wrapper.style.display = 'none'
        pre.style.display = ''
        previewBtn.textContent = '▶ Preview'
        previewVisible = false
      }
      closePreview()  // initial state

      previewBtn.addEventListener('click', () => {
        previewVisible ? closePreview() : openPreview()
      })

      // Insert preview button before the copy button
      const copyBtn = header.querySelector('.copy-btn')
      header.insertBefore(previewBtn, copyBtn)

      // Auto-show preview for complete HTML documents
      const isCompleteDoc = htmlContent.includes('<!DOCTYPE') || /<html[\s>]/i.test(htmlContent)
      if (isCompleteDoc) openPreview()
    })
  }
})
</script>

<template>
  <div class="message-wrapper">
    <!-- Collapsible thinking block -->
    <details v-if="reasoningHtml" class="thinking-block" :open="reasoningOpen" @toggle="reasoningOpen = ($event.target as HTMLDetailsElement).open">
      <summary class="thinking-summary">
        <span class="thinking-icon">💭</span>
        <span>Thinking</span>
        <span class="thinking-chevron">{{ reasoningOpen ? '▲' : '▼' }}</span>
      </summary>
      <div class="thinking-content" v-html="reasoningHtml" />
    </details>

    <!-- Main response -->
    <div
      ref="containerRef"
      class="markdown-body"
      :class="{ streaming }"
      v-html="renderedHtml"
    />
  </div>
</template>

<style scoped>
.message-wrapper {
  display: flex;
  flex-direction: column;
  gap: 0.5em;
  min-width: 0;
}

/* ── Thinking block ── */
.thinking-block {
  border: 1px solid var(--bd-subtle, rgba(255,255,255,0.08));
  border-radius: 8px;
  background: var(--bg-2, rgba(255,255,255,0.03));
  overflow: hidden;
}

.thinking-summary {
  display: flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.4em 0.75em;
  cursor: pointer;
  font-size: var(--text-xs, 0.75rem);
  color: var(--tx-secondary, rgba(255,255,255,0.5));
  user-select: none;
  list-style: none;
}
.thinking-summary::-webkit-details-marker { display: none; }
.thinking-summary:hover { color: var(--tx-primary); }

.thinking-icon { font-size: 0.9em; }
.thinking-chevron { margin-left: auto; font-size: 0.7em; opacity: 0.6; }

.thinking-content {
  padding: 0.6em 0.9em 0.75em;
  font-size: var(--text-xs, 0.75rem);
  color: var(--tx-secondary, rgba(255,255,255,0.5));
  line-height: 1.5;
  border-top: 1px solid var(--bd-subtle, rgba(255,255,255,0.06));
  word-break: break-word;
}
.thinking-content :deep(p) { margin: 0 0 0.4em; }
.thinking-content :deep(p:last-child) { margin-bottom: 0; }
.thinking-content :deep(ul), .thinking-content :deep(ol) { margin: 0.3em 0 0.4em 1.2em; padding: 0; }
.thinking-content :deep(li) { margin: 0.15em 0; }
.thinking-content :deep(code) { font-family: monospace; font-size: 0.9em; opacity: 0.8; }

.markdown-body {
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--tx-primary);
  word-break: break-word;
  min-width: 0;
}

/* Streaming cursor at end */
.markdown-body.streaming::after {
  content: '▋';
  display: inline;
  color: var(--si-400);
  animation: blink .8s step-end infinite;
  margin-left: 1px;
}
@keyframes blink { 50% { opacity: 0; } }

/* ── Prose ── */
.markdown-body :deep(p) {
  margin: 0 0 0.25em;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.2em 0 0.3em 1.3em;
  padding: 0;
}
.markdown-body :deep(li) {
  margin: 0.2em 0;
}
/* Prevent paragraph margins from adding huge gaps inside loose lists */
.markdown-body :deep(li > p) {
  margin: 0;
}
.markdown-body :deep(li > p + p) {
  margin-top: 0.1em;
}
/* Nested lists */
.markdown-body :deep(li > ul),
.markdown-body :deep(li > ol) {
  margin: 0.05em 0 0.05em 1em;
}

/* ── Headings ── */
.markdown-body :deep(h1) { font-size: 1.35em; font-weight: 700; margin: 0.8em 0 0.4em; color: var(--tx-primary); }
.markdown-body :deep(h2) { font-size: 1.2em;  font-weight: 700; margin: 0.8em 0 0.4em; color: var(--tx-primary); }
.markdown-body :deep(h3) { font-size: 1.08em; font-weight: 600; margin: 0.7em 0 0.3em; color: var(--tx-primary); }
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) { font-size: 1em; font-weight: 600; margin: 0.6em 0 0.3em; color: var(--tx-secondary); }

/* ── Inline code ── */
.markdown-body :deep(code) {
  font-family: var(--font-mono);
  background: var(--bg-elevated);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.9em;
  color: var(--si-300);
  border: 1px solid var(--bd-subtle);
}

/* ── Code blocks ── */
.markdown-body :deep(pre) {
  background: var(--g-900, #1C1C1E);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  overflow-x: auto;
  margin: 0.6em 0;
  position: relative;
}

.markdown-body :deep(pre code) {
  background: transparent;
  border: none;
  padding: var(--space-3) var(--space-4);
  border-radius: 0;
  font-size: 0.88em;
  color: var(--tx-primary);
  display: block;
  line-height: 1.55;
}

/* ── Code header (language + copy button) ── */
.markdown-body :deep(.code-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px var(--space-3);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--bd-subtle);
  border-radius: var(--r-md) var(--r-md) 0 0;
}

.markdown-body :deep(.code-lang) {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--tx-muted);
  text-transform: lowercase;
  letter-spacing: .04em;
}

.markdown-body :deep(.copy-btn) {
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  font-size: 12px;
  font-family: var(--font-sans, inherit);
  padding: 2px 8px;
  cursor: pointer;
  transition: color 100ms ease, border-color 100ms ease;
  line-height: 1.4;
}
.markdown-body :deep(.copy-btn:hover) {
  color: var(--tx-secondary);
  border-color: var(--bd-emphasis);
}

/* ── Tables ── */
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.6em 0;
  font-size: 0.92em;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--bd-default);
  padding: 5px 10px;
  text-align: left;
}
.markdown-body :deep(th) {
  background: var(--bg-elevated);
  font-weight: 600;
  color: var(--tx-secondary);
}

/* ── Blockquote ── */
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--si-500);
  margin: 0.6em 0;
  padding: 4px var(--space-3);
  color: var(--tx-secondary);
  background: var(--ac-bg);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
}
.markdown-body :deep(blockquote p) { margin: 0; }

/* ── Links ── */
.markdown-body :deep(a) {
  color: var(--si-300);
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

/* ── HR ── */
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--bd-default);
  margin: 0.8em 0;
}

/* ── Strong / em ── */
.markdown-body :deep(strong) { font-weight: 600; color: var(--tx-primary); }
.markdown-body :deep(em) { font-style: italic; color: var(--tx-secondary); }

/* ── HTML live preview ── */
.markdown-body :deep(.preview-btn) {
  background: transparent;
  border: 1px solid var(--si-700, #2d4a8a);
  border-radius: var(--r-sm);
  color: var(--si-300);
  font-size: 12px;
  font-family: var(--font-sans, inherit);
  padding: 2px 8px;
  cursor: pointer;
  transition: color 100ms ease, border-color 100ms ease;
  line-height: 1.4;
  margin-right: 4px;
}
.markdown-body :deep(.preview-btn:hover) {
  color: var(--si-200);
  border-color: var(--si-500);
}

.markdown-body :deep(.html-preview-wrapper) {
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  overflow: hidden;
  margin: 0.6em 0;
}

.markdown-body :deep(.html-preview-controls) {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px var(--space-3, 12px);
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--bd-subtle);
}

.markdown-body :deep(.preview-size-label) {
  font-size: 11px;
  color: var(--tx-muted);
  margin-right: 2px;
  font-family: var(--font-mono);
}

.markdown-body :deep(.size-btn) {
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: 3px;
  color: var(--tx-muted);
  font-size: 11px;
  padding: 1px 6px;
  cursor: pointer;
  transition: all 100ms ease;
  line-height: 1.4;
}
.markdown-body :deep(.size-btn.active),
.markdown-body :deep(.size-btn:hover) {
  color: var(--tx-primary);
  border-color: var(--bd-emphasis);
  background: var(--bg-elevated);
}

.markdown-body :deep(.preview-open-btn) {
  background: transparent;
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-muted);
  font-size: 11px;
  padding: 1px 6px;
  cursor: pointer;
  margin-left: auto;
  transition: all 100ms ease;
  line-height: 1.4;
}
.markdown-body :deep(.preview-open-btn:hover) {
  color: var(--si-300);
  border-color: var(--si-500);
}

.markdown-body :deep(.html-preview-iframe) {
  display: block;
  width: 100%;
  height: 500px;
  border: none;
  background: #fff;
}
</style>
