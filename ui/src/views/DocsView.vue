<!--
  DocsView — in-app documentation viewer.

  Fetches markdown content from /api/docs and renders it in-page so users
  never leave the dashboard to read documentation. The sidebar is dynamically
  built from the docs index returned by the API.

  Navigation: anchors in the rendered HTML are intercepted and resolved
  against the in-app docs tree rather than triggering full page loads.
-->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

interface DocItem { path: string; title: string }
interface Section { section: string; items: DocItem[] }

const sections    = ref<Section[]>([])
const activePath  = ref('index.md')
const content     = ref('')
const loading     = ref(false)
const error       = ref('')
const searchQuery = ref('')

const sectionLabels: Record<string, string> = {
  '.'               : 'Overview',
  'getting-started' : 'Getting Started',
  'guides'          : 'User Guides',
  'reference'       : 'Reference',
  'benchmarks'      : 'Benchmarks',
  'development'     : 'Development',
  'dashboard'       : 'Dashboard',
}

function labelFor(section: string): string {
  return sectionLabels[section] ?? section.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const filteredSections = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return sections.value
  return sections.value
    .map(s => ({ ...s, items: s.items.filter(i => i.title.toLowerCase().includes(q) || i.path.toLowerCase().includes(q)) }))
    .filter(s => s.items.length)
})

const BASE = import.meta.env.DEV ? '/api' : ''

async function loadToc() {
  try {
    const r = await fetch(`${BASE}/api/docs`)
    if (!r.ok) throw new Error(`${r.status}`)
    const data = await r.json() as { sections: Section[] }
    sections.value = data.sections
  } catch (e) {
    error.value = `Could not load docs: ${e}`
  }
}

async function loadDoc(path: string) {
  activePath.value = path
  loading.value = true
  error.value = ''
  content.value = ''
  try {
    const r = await fetch(`${BASE}/api/docs/${encodeURIComponent(path)}`)
    if (!r.ok) throw new Error(`${r.status}`)
    const md = await r.text()

    // Configure marked with highlight.js
    marked.setOptions({
      // @ts-ignore — gfm and breaks are valid options
      gfm: true,
      breaks: false,
    })

    const renderer = new marked.Renderer()
    renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      const highlighted = hljs.highlight(text, { language }).value
      return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
    }

    const raw = await marked(md, { renderer })
    content.value = DOMPurify.sanitize(raw as string)
  } catch (e) {
    error.value = `Could not load document: ${e}`
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadToc()
  // Restore last viewed doc
  const last = localStorage.getItem('vmui_last_doc')
  loadDoc(last ?? 'index.md')
})

watch(activePath, p => { localStorage.setItem('vmui_last_doc', p) })
</script>

<template>
  <div class="docs-layout">
    <!-- Left nav -->
    <aside class="docs-nav">
      <div class="docs-search-wrap">
        <input
          v-model="searchQuery"
          class="docs-search"
          type="search"
          placeholder="Search docs…"
          autocomplete="off"
        />
      </div>
      <nav>
        <template v-for="sec in filteredSections" :key="sec.section">
          <div class="nav-section-label">{{ labelFor(sec.section) }}</div>
          <button
            v-for="item in sec.items"
            :key="item.path"
            class="nav-doc-item"
            :class="{ active: activePath === item.path }"
            @click="loadDoc(item.path)"
          >{{ item.title }}</button>
        </template>
        <div v-if="filteredSections.length === 0 && searchQuery" class="nav-empty">
          No results for "{{ searchQuery }}"
        </div>
      </nav>
    </aside>

    <!-- Doc content -->
    <main class="docs-content">
      <div v-if="loading" class="docs-loading">
        <span class="loading-spin" />
        Loading…
      </div>
      <div v-else-if="error" class="docs-error">{{ error }}</div>
      <div
        v-else
        class="markdown-body"
        v-html="content"
      />
    </main>
  </div>
</template>

<style scoped>
.docs-layout {
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* ── Left nav ─────────────────────────────────────────────────────────────── */
.docs-nav {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--bd-subtle);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-surface);
}

.docs-search-wrap {
  padding: var(--space-3) var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--bd-subtle);
}
.docs-search {
  width: 100%;
  padding: 5px 8px;
  font-size: 12px;
  font-family: inherit;
  background: var(--bg-inset);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-sm);
  color: var(--tx-primary);
  outline: none;
}
.docs-search:focus { border-color: var(--si-500); }

nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2) 0 var(--space-4);
}

.nav-section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  padding: var(--space-3) var(--space-3) var(--space-1);
}
.nav-doc-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 5px var(--space-3);
  font-size: 12.5px;
  font-family: inherit;
  background: transparent;
  border: none;
  color: var(--tx-secondary);
  cursor: pointer;
  border-radius: 0;
  transition: background var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav-doc-item:hover { background: var(--bg-elevated); color: var(--tx-primary); }
.nav-doc-item.active {
  background: color-mix(in srgb, var(--si-500) 12%, transparent);
  color: var(--si-300);
  font-weight: 600;
}
.nav-empty { padding: var(--space-3); font-size: 12px; color: var(--tx-muted); }

/* ── Doc content ──────────────────────────────────────────────────────────── */
.docs-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  min-width: 0;
}

.docs-loading, .docs-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
  color: var(--tx-muted);
  padding: var(--space-4);
}
.docs-error { color: var(--cu-400); }
.loading-spin {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--bd-default);
  border-top-color: var(--si-400);
  border-radius: 50%;
  animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Markdown body ────────────────────────────────────────────────────────── */
.markdown-body {
  max-width: 760px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--tx-secondary);
}
.markdown-body :deep(h1) { font-size: 22px; font-weight: 700; color: var(--tx-primary); margin: 0 0 var(--space-4); letter-spacing: -.3px; }
.markdown-body :deep(h2) { font-size: 16px; font-weight: 700; color: var(--tx-primary); margin: var(--space-6) 0 var(--space-3); border-bottom: 1px solid var(--bd-subtle); padding-bottom: var(--space-2); }
.markdown-body :deep(h3) { font-size: 13.5px; font-weight: 700; color: var(--tx-primary); margin: var(--space-4) 0 var(--space-2); }
.markdown-body :deep(h4) { font-size: 12px; font-weight: 700; color: var(--tx-secondary); margin: var(--space-3) 0 var(--space-1); text-transform: uppercase; letter-spacing: .05em; }
.markdown-body :deep(p) { margin: 0 0 var(--space-3); }
.markdown-body :deep(a) { color: var(--si-400); text-decoration: none; }
.markdown-body :deep(a:hover) { text-decoration: underline; color: var(--si-300); }
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 0 0 var(--space-3); padding-left: 1.4em; }
.markdown-body :deep(li) { margin-bottom: var(--space-1); }
.markdown-body :deep(code) { font-family: var(--font-mono); font-size: 12px; background: var(--bg-inset); border: 1px solid var(--bd-subtle); border-radius: 3px; padding: 1px 4px; color: var(--si-300); }
.markdown-body :deep(pre) { background: var(--bg-inset); border: 1px solid var(--bd-subtle); border-radius: var(--r-md); padding: var(--space-3) var(--space-4); overflow-x: auto; margin: 0 0 var(--space-3); }
.markdown-body :deep(pre code) { background: none; border: none; padding: 0; color: var(--tx-secondary); font-size: 12px; }
.markdown-body :deep(blockquote) { border-left: 3px solid var(--si-500); padding: var(--space-2) var(--space-3); margin: 0 0 var(--space-3); background: color-mix(in srgb, var(--si-500) 6%, transparent); border-radius: 0 var(--r-sm) var(--r-sm) 0; }
.markdown-body :deep(blockquote p) { margin: 0; color: var(--tx-secondary); }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 0 0 var(--space-3); font-size: 12.5px; }
.markdown-body :deep(th) { text-align: left; padding: var(--space-2) var(--space-3); font-weight: 700; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: var(--tx-muted); border-bottom: 1px solid var(--bd-default); }
.markdown-body :deep(td) { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--bd-subtle); color: var(--tx-secondary); }
.markdown-body :deep(tr:hover td) { background: var(--bg-elevated); }
.markdown-body :deep(hr) { border: none; border-top: 1px solid var(--bd-subtle); margin: var(--space-5) 0; }
.markdown-body :deep(strong) { font-weight: 700; color: var(--tx-primary); }
</style>
