<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useServerStore } from '@/stores/server'
import { useMachinesStore } from '@/stores/machines'

const route = useRoute()
const serverStore = useServerStore()
const machinesStore = useMachinesStore()

// Memory arc gauge
const memPct = computed(() => serverStore.memory?.percent ?? 0)
const arcFillColor = computed(() => memPct.value > 75 ? 'var(--cu-500)' : 'var(--si-500)')
const arcDashOffset = computed(() => {
  const arc = 157
  return arc - arc * (memPct.value / 100)
})
const memUsedGb = computed(() => serverStore.memory?.used_gb.toFixed(1) ?? '—')
const memTotalGb = computed(() => serverStore.memory?.total_gb.toFixed(0) ?? '—')
const loadedModel = computed(() => serverStore.status?.model ?? null)

// Machine switcher
const showAddForm = ref(false)

function selectMachine(id: string) {
  machinesStore.setActive(id)
}

// Nav active state
const isActive = (path: string): boolean => {
  if (path === '/serve') return route.path === '/serve' || route.path === '/'
  return route.path.startsWith(path)
}
</script>

<template>
  <aside class="sidebar">
    <!-- Wordmark -->
    <div class="sidebar-logo">
      <span class="logo-mark">vm</span><span class="logo-accent">UI</span>
    </div>

    <!-- Machine Switcher -->
    <div class="sidebar-section">
      <div class="section-label">Fleet</div>
      <div class="machine-list">
        <button
          v-for="m in machinesStore.machines"
          :key="m.id"
          class="machine-item"
          :class="{ active: m.id === machinesStore.activeMachineId }"
          @click="selectMachine(m.id)"
        >
          <span class="machine-dot" :class="m.online ? 'online' : 'offline'" />
          <span class="machine-name">{{ m.name }}</span>
          <span v-if="m.type === 'remote'" class="machine-host">{{ m.host }}</span>
        </button>
      </div>
      <button class="add-machine-btn" @click="showAddForm = !showAddForm">
        <span>+ Add machine</span>
      </button>
      <div v-if="showAddForm" class="add-machine-placeholder">
        <p class="placeholder-note">Machine configuration form — coming next</p>
      </div>
    </div>

    <!-- Memory Arc Gauge — signature element -->
    <div class="sidebar-section gauge-section">
      <svg viewBox="0 0 120 72" xmlns="http://www.w3.org/2000/svg" class="arc-svg" aria-label="Memory usage gauge">
        <!-- Track -->
        <path
          d="M 10 65 A 50 50 0 0 1 110 65"
          fill="none"
          stroke="var(--arc-track)"
          stroke-width="9"
          stroke-linecap="round"
        />
        <!-- Fill -->
        <path
          d="M 10 65 A 50 50 0 0 1 110 65"
          fill="none"
          :stroke="arcFillColor"
          stroke-width="9"
          stroke-linecap="round"
          stroke-dasharray="157"
          :stroke-dashoffset="arcDashOffset"
          class="arc-fill"
        />
        <!-- Usage text -->
        <text
          x="60" y="50"
          text-anchor="middle"
          font-family="var(--font-mono)"
          font-size="17"
          font-weight="700"
          fill="var(--tx-primary)"
        >{{ memUsedGb }}</text>
        <text
          x="60" y="62"
          text-anchor="middle"
          font-size="9.5"
          fill="var(--tx-muted)"
        >of {{ memTotalGb }} GB</text>
      </svg>
      <div v-if="loadedModel" class="gauge-model-name">{{ loadedModel }}</div>
    </div>

    <!-- Nav -->
    <nav class="sidebar-nav">
      <RouterLink to="/serve" class="nav-item" :class="{ active: isActive('/serve') }">
        <!-- Home icon -->
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" />
        </svg>
        <span>Serve</span>
      </RouterLink>

      <RouterLink to="/models" class="nav-item" :class="{ active: isActive('/models') }">
        <!-- Layers icon -->
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path d="M4.25 2A2.25 2.25 0 002 4.25v2.5A2.25 2.25 0 004.25 9h2.5A2.25 2.25 0 009 6.75v-2.5A2.25 2.25 0 006.75 2h-2.5zm0 9A2.25 2.25 0 002 13.25v2.5A2.25 2.25 0 004.25 18h2.5A2.25 2.25 0 009 15.75v-2.5A2.25 2.25 0 006.75 11h-2.5zm6.5-9A2.25 2.25 0 008.5 4.25v2.5A2.25 2.25 0 0010.75 9h2.5A2.25 2.25 0 0015.5 6.75v-2.5A2.25 2.25 0 0013.25 2h-2.5zm0 9a2.25 2.25 0 00-2.25 2.25v2.5A2.25 2.25 0 0010.75 18h2.5a2.25 2.25 0 002.25-2.25v-2.5a2.25 2.25 0 00-2.25-2.25h-2.5z" />
        </svg>
        <span>Models</span>
      </RouterLink>

      <RouterLink to="/settings" class="nav-item" :class="{ active: isActive('/settings') }">
        <!-- Cog icon -->
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M7.84 1.804A1 1 0 018.82 1h2.36a1 1 0 01.98.804l.331 1.652a6.993 6.993 0 011.929 1.115l1.598-.54a1 1 0 011.186.447l1.18 2.044a1 1 0 01-.205 1.251l-1.267 1.113a7.047 7.047 0 010 2.228l1.267 1.113a1 1 0 01.206 1.25l-1.18 2.045a1 1 0 01-1.187.447l-1.598-.54a6.993 6.993 0 01-1.929 1.115l-.33 1.652a1 1 0 01-.98.804H8.82a1 1 0 01-.98-.804l-.331-1.652a6.993 6.993 0 01-1.929-1.115l-1.598.54a1 1 0 01-1.186-.447l-1.18-2.044a1 1 0 01.205-1.251l1.267-1.114a7.05 7.05 0 010-2.227L1.821 7.773a1 1 0 01-.206-1.25l1.18-2.045a1 1 0 011.187-.447l1.598.54A6.993 6.993 0 017.51 3.456l.33-1.652zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
        </svg>
        <span>Settings</span>
      </RouterLink>

      <div class="nav-divider" />

      <RouterLink to="/chat" class="nav-item nav-item-util" :class="{ active: isActive('/chat') }">
        <!-- Chat icon -->
        <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15" aria-hidden="true">
          <path fill-rule="evenodd" d="M2 5a2 2 0 012-2h8a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V5zm3 1h6v4H5V6zm6 6H5v2h6v-2z" clip-rule="evenodd" />
          <path d="M15 7h1a2 2 0 012 2v5.5a.5.5 0 01-.5.5H15V7z" />
        </svg>
        <span>Test Chat</span>
      </RouterLink>
    </nav>

    <!-- Footer -->
    <div class="sidebar-footer">
      <span class="footer-version">v0.1.0</span>
      <span class="footer-dot" :class="serverStore.isRunning ? 'running' : 'stopped'" />
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 224px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--bd-default);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* Wordmark */
.sidebar-logo {
  padding: var(--space-4) var(--space-4) var(--space-3);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -.4px;
  line-height: 1;
  flex-shrink: 0;
}
.logo-mark { color: var(--tx-primary); }
.logo-accent { color: var(--si-400); }

/* Sections */
.sidebar-section {
  padding: var(--space-3) var(--space-3);
  border-bottom: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  padding: 0 var(--space-1) var(--space-2);
}

/* Machine list */
.machine-list { display: flex; flex-direction: column; gap: 2px; }

.machine-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 5px var(--space-2);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  cursor: pointer;
  color: var(--tx-secondary);
  font-size: var(--text-sm);
  font-family: inherit;
  text-align: left;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.machine-item:hover {
  background: var(--bg-elevated);
}
.machine-item.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
}

.machine-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.machine-dot.online  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.machine-dot.offline { background: var(--g-600); }

.machine-name { flex: 1; font-weight: 500; }
.machine-host { font-size: 11px; color: var(--tx-muted); font-family: var(--font-mono); }

.add-machine-btn {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 4px var(--space-2);
  margin-top: var(--space-1);
  background: transparent;
  border: none;
  color: var(--tx-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  border-radius: var(--r-md);
  transition: color var(--transition-fast), background var(--transition-fast);
}
.add-machine-btn:hover { color: var(--tx-secondary); background: var(--bg-elevated); }

.add-machine-placeholder {
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
}
.placeholder-note {
  font-size: 11px;
  color: var(--tx-muted);
  font-style: italic;
}

/* Arc gauge */
.gauge-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: var(--space-4);
  padding-bottom: var(--space-3);
}

.arc-svg {
  width: 140px;
  height: auto;
  display: block;
}

.arc-fill {
  transition: stroke-dashoffset .5s ease, stroke .3s ease;
}

.gauge-model-name {
  margin-top: var(--space-2);
  font-size: 11px;
  color: var(--tx-tertiary);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
}

/* Nav */
.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: var(--space-2) var(--space-2);
  gap: 2px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px var(--space-2);
  border-radius: var(--r-md);
  border: 1px solid transparent;
  color: var(--tx-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
}
.nav-item:hover {
  background: var(--bg-elevated);
  color: var(--tx-primary);
}
.nav-item.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
}

.nav-item-util { color: var(--tx-tertiary); }
.nav-item-util.active { color: var(--si-300); }

.nav-divider {
  height: 1px;
  background: var(--bd-subtle);
  margin: var(--space-1) var(--space-1);
}

/* Footer */
.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--bd-subtle);
  flex-shrink: 0;
}

.footer-version {
  font-size: 11px;
  color: var(--tx-muted);
  font-family: var(--font-mono);
}

.footer-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.footer-dot.running  { background: var(--ph-500); box-shadow: 0 0 0 2px rgba(34,197,94,.2); }
.footer-dot.stopped  { background: var(--g-600); }

/* Responsive: hide sidebar below 720px */
@media (max-width: 720px) {
  .sidebar { display: none; }
}
</style>
