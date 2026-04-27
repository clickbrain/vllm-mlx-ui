<!--
  DocsView — in-app documentation viewer.

  Fetches markdown content from /api/docs and renders it in-page so users
  never leave the dashboard to read documentation. The sidebar is dynamically
  built from the docs index returned by the API.

  Features:
  - Left nav with search
  - Right-side in-page TOC with scroll-spy
  - Heading anchors for deep linking (#section-slug)
  - URL hash navigation: clicking a TOC item updates the hash
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

interface DocItem { path: string; title: string }
interface Section { section: string; items: DocItem[] }
interface TocItem { id: string; text: string; level: number }

const sections      = ref<Section[]>([])
const activePath    = ref('index.md')
const content       = ref('')
const loading       = ref(false)
const error         = ref('')
const searchQuery   = ref('')
const tocItems      = ref<TocItem[]>([])
const activeSection = ref('')
const contentEl     = ref<HTMLElement | null>(null)

let observer: IntersectionObserver | null = null

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

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, '')      // strip HTML tags
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function parseToc(html: string): TocItem[] {
  if (typeof document === 'undefined') return []
  const tmp = document.createElement('div')
  tmp.innerHTML = html
  const items: TocItem[] = []
  tmp.querySelectorAll('h2, h3').forEach(el => {
    const text = (el.textContent ?? '').replace('¶', '').trim()
    if (text) items.push({ id: el.id, text, level: parseInt(el.tagName[1]) })
  })
  return items
}

function setupScrollSpy() {
  if (observer) observer.disconnect()
  if (!contentEl.value) return
  const headings = contentEl.value.querySelectorAll('h2[id], h3[id]')
  if (!headings.length) { activeSection.value = ''; return }

  observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        activeSection.value = (entry.target as HTMLElement).id
        break
      }
    }
  }, { root: contentEl.value, rootMargin: '-10% 0px -80% 0px', threshold: 0 })

  headings.forEach(h => observer!.observe(h))
}

function scrollToHash(hash: string) {
  if (!hash || !contentEl.value) return
  const el = contentEl.value.querySelector(`#${CSS.escape(hash)}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function tocClick(id: string) {
  activeSection.value = id
  window.location.hash = id
  nextTick(() => scrollToHash(id))
}

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

async function loadDoc(path: string, scrollHash?: string) {
  activePath.value = path
  loading.value = true
  error.value = ''
  content.value = ''
  tocItems.value = []
  activeSection.value = ''

  try {
    const r = await fetch(`${BASE}/api/docs/${encodeURIComponent(path)}`)
    if (!r.ok) throw new Error(`${r.status}`)
    const md = await r.text()

    marked.setOptions({
      // @ts-ignore
      gfm: true,
      breaks: false,
    })

    const renderer = new marked.Renderer()

    renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      const highlighted = hljs.highlight(text, { language }).value
      return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
    }

    // Add id + anchor icon to headings
    renderer.heading = ({ text, depth }: { text: string; depth: number }) => {
      const id = slugify(text)
      const tag = `h${depth}`
      if (depth <= 3) {
        return `<${tag} id="${id}"><a class="heading-anchor" href="#${id}" tabindex="-1">¶</a>${text}</${tag}>\n`
      }
      return `<${tag}>${text}</${tag}>\n`
    }

    const raw = await marked(md, { renderer })
    content.value = DOMPurify.sanitize(raw as string, {
      ADD_ATTR: ['id', 'tabindex'],
    })
    tocItems.value = parseToc(content.value)

    await nextTick()
    setupScrollSpy()
    if (scrollHash) scrollToHash(scrollHash)
    else if (contentEl.value) contentEl.value.scrollTop = 0

  } catch (e) {
    error.value = `Could not load document: ${e}`
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadToc()
  const last = localStorage.getItem('vmui_last_doc')
  const hash = window.location.hash.replace('#', '')
  loadDoc(last ?? 'index.md', hash || undefined)
})

onUnmounted(() => { if (observer) observer.disconnect() })

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

    <!-- Doc content + right TOC wrapper -->
    <div class="docs-body">
      <main class="docs-content" ref="contentEl">
        <div v-if="loading" class="docs-loading">
          <span class="loading-spin" />
          Loading…
        </div>
        <div v-else-if="error" class="docs-error">{{ error }}</div>
        <div
          v-else
          class="markdown-body"
          v-html="content"
          @click.prevent="(e) => {
            const a = (e.target as HTMLElement).closest('a.heading-anchor')
            if (a) {
              const id = a.getAttribute('href')?.slice(1)
              if (id) tocClick(id)
            }
          }"
        />
      </main>

      <!-- Right-side in-page TOC -->
      <aside v-if="tocItems.length >= 2" class="docs-toc">
        <div class="toc-label">On this page</div>
        <nav class="toc-nav">
          <a
            v-for="item in tocItems"
            :key="item.id"
            class="toc-item"
            :class="[`toc-h${item.level}`, { active: activeSection === item.id }]"
            href="#"
            @click.prevent="tocClick(item.id)"
          >{{ item.text }}</a>
        </nav>
      </aside>
    </div>
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

/* ── Center + right TOC wrapper ───────────────────────────────────────────── */
.docs-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-width: 0;
}

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

/* ── Right in-page TOC ────────────────────────────────────────────────────── */
.docs-toc {
  width: 196px;
  flex-shrink: 0;
  border-left: 1px solid var(--bd-subtle);
  padding: var(--space-5) var(--space-3) var(--space-4) var(--space-3);
  overflow-y: auto;
}

.toc-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
}

.toc-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toc-item {
  display: block;
  font-size: 11.5px;
  color: var(--tx-muted);
  text-decoration: none;
  padding: 3px var(--space-2);
  border-left: 2px solid transparent;
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  transition: color var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.toc-item:hover { color: var(--tx-secondary); background: var(--bg-elevated); }
.toc-item.active { color: var(--si-300); border-left-color: var(--si-400); font-weight: 600; }
.toc-h3 { padding-left: calc(var(--space-2) + 10px); font-size: 11px; }

/* ── Markdown body ────────────────────────────────────────────────────────── */
.markdown-body {
  max-width: 760px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--tx-secondary);
}
.markdown-body :deep(h1) { font-size: 22px; font-weight: 700; color: var(--tx-primary); margin: 0 0 var(--space-4); letter-spacing: -.3px; }
.markdown-body :deep(h2) {
  font-size: 16px; font-weight: 700; color: var(--tx-primary);
  margin: var(--space-6) 0 var(--space-3);
  border-bottom: 1px solid var(--bd-subtle); padding-bottom: var(--space-2);
  position: relative;
}
.markdown-body :deep(h3) { font-size: 13.5px; font-weight: 700; color: var(--tx-primary); margin: var(--space-4) 0 var(--space-2); position: relative; }
.markdown-body :deep(h4) { font-size: 12px; font-weight: 700; color: var(--tx-secondary); margin: var(--space-3) 0 var(--space-1); text-transform: uppercase; letter-spacing: .05em; }
.markdown-body :deep(p) { margin: 0 0 var(--space-3); }
.markdown-body :deep(a) { color: var(--si-400); text-decoration: none; }
.markdown-body :deep(a:hover) { text-decoration: underline; color: var(--si-300); }

/* Heading anchor ¶ — visible on hover */
.markdown-body :deep(.heading-anchor) {
  opacity: 0;
  margin-right: var(--space-2);
  font-size: .85em;
  color: var(--tx-muted);
  text-decoration: none;
  transition: opacity .15s;
  user-select: none;
}
.markdown-body :deep(h2:hover .heading-anchor),
.markdown-body :deep(h3:hover .heading-anchor) { opacity: 1; }
.markdown-body :deep(.heading-anchor:hover) { color: var(--si-400); }

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
