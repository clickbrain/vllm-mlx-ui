<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
  BenchmarkView — Performance & Data hub.

  Sections (tabbed):
    Live     — real-time server metrics: request charts, GPU memory chart,
               active requests table, cache statistics panel
    Speed    — tok/s benchmarks (existing BenchmarkPanel, promoted here)
    Quality  — placeholder for MMLU / GSM8K / HumanEval runs
    Saved    — all prior benchmark runs with save/favorite/compare
    Advisor  — describe a task → AI recommends best model + config
-->
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Line, Bar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import type { ChartData, ChartOptions } from 'chart.js'
import { useServerStore } from '@/stores/server'
import { useModelsStore } from '@/stores/models'
import BenchmarkPanel from '@/components/models/BenchmarkPanel.vue'
import AppButton from '@/components/shared/AppButton.vue'
import { api } from '@/api/client'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Filler, Tooltip, Legend,
)

const serverStore = useServerStore()
const modelsStore = useModelsStore()

// ── Tab state ─────────────────────────────────────────────────────────────
const tabs = ['Live', 'Speed', 'Quality', 'Saved', 'Advisor'] as const
type Tab = typeof tabs[number]
const activeTab = ref<Tab>('Live')

// ── Live tab — polling ─────────────────────────────────────────────────────
let stopPoll: (() => void) | null = null
let cacheInterval: ReturnType<typeof setInterval> | null = null
const cacheStats = ref<Record<string, unknown> | null>(null)
const cacheError = ref(false)

async function refreshCache() {
  if (!serverStore.isRunning) { cacheStats.value = null; return }
  const result = await serverStore.fetchCacheStats()
  if (result && !result.error) { cacheStats.value = result; cacheError.value = false }
  else cacheError.value = true
}

onMounted(() => {
  stopPoll = serverStore.startPolling(3000)
  refreshCache()
  cacheInterval = setInterval(refreshCache, 15_000)
})

onUnmounted(() => {
  stopPoll?.()
  if (cacheInterval) clearInterval(cacheInterval)
})

watch(() => serverStore.isRunning, (running) => {
  if (running) refreshCache()
  else { cacheStats.value = null; cacheError.value = false }
})

// ── Live tab — chart data ──────────────────────────────────────────────────
const lineOpts: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: { legend: { display: false }, tooltip: {
    backgroundColor: '#1c1c1e',
    borderColor: 'rgba(255,255,255,.08)',
    borderWidth: 1,
    titleColor: '#e5e5ea',
    bodyColor: '#aeaeb2',
  }},
  scales: {
    x: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#636366', maxTicksLimit: 8, font: { size: 10 } } },
    y: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#636366', font: { size: 10 } }, beginAtZero: true },
  },
}

const requestsChartData = computed((): ChartData<'line'> => {
  const h = serverStore.metricsHistory
  return {
    labels: h.map(e => e.time),
    datasets: [
      {
        label: 'Active',
        data: h.map(e => e.active),
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167,139,250,.12)',
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      },
      {
        label: 'Queued',
        data: h.map(e => e.queued),
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245,158,11,.08)',
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      },
    ],
  }
})

const memoryChartData = computed((): ChartData<'line'> => {
  const h = serverStore.metricsHistory
  return {
    labels: h.map(e => e.time),
    datasets: [{
      label: 'GPU Memory (GB)',
      data: h.map(e => e.memory_gb),
      borderColor: '#34d399',
      backgroundColor: 'rgba(52,211,153,.1)',
      borderWidth: 1.5,
      fill: true,
      tension: 0.3,
      pointRadius: 0,
    }],
  }
})

// ── Uptime formatter (reused from ServeView) ────────────────────────────────
const uptime = computed(() => {
  const s = serverStore.uptimeSeconds
  if (!s) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
})

// ── Cache stats display ─────────────────────────────────────────────────────
const cacheEntries = computed(() => {
  if (!cacheStats.value) return []
  return Object.entries(cacheStats.value).map(([k, v]) => ({ key: k, value: v }))
})

// ── Cost Analysis (Saved tab) ────────────────────────────────────────────────
interface CostByModel {
  model_id: string
  tier: 'small' | 'medium' | 'large'
  tokens_generated: number
  estimated_cost_usd: number
}

interface CostStats {
  benchmarks_analyzed: number
  total_input_tokens: number
  total_output_tokens: number
  estimated_cloud_cost_usd: number
  estimated_monthly_savings_usd: number
  by_model: CostByModel[]
  rates_used: Record<string, { input_per_1m: number; output_per_1m: number }>
}

const costStats = ref<CostStats | null>(null)
const costLoading = ref(false)
const costError = ref(false)

async function fetchCostStats() {
  costLoading.value = true
  costError.value = false
  try {
    const data = await api.get<CostStats>('/stats/cost')
    costStats.value = data
  } catch {
    costError.value = true
  } finally {
    costLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'Saved') fetchCostStats()
})
</script>

<template>
  <div class="benchmark-view">
    <!-- Page header -->
    <div class="page-header">
      <div class="page-title">Benchmarks <span class="amp">&amp;</span> Data</div>
      <p class="page-desc">Performance metrics, model benchmarks, and data to guide every inference decision.</p>
    </div>

    <!-- Tab bar -->
    <div class="tab-bar-wrap">
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab"
          class="tab-btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >{{ tab }}</button>
      </div>
    </div>

    <!-- ── LIVE TAB ──────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'Live'" class="tab-body">

      <!-- Status banner -->
      <div
        class="status-banner"
        :class="{
          'banner-green': serverStore.isRunning && serverStore.status?.healthy,
          'banner-yellow': serverStore.isRunning && !serverStore.status?.healthy,
          'banner-red': !serverStore.isRunning,
        }"
      >
        <span class="banner-dot" />
        <span v-if="serverStore.isRunning && serverStore.status?.healthy">
          <strong>Running</strong> — {{ serverStore.modelId ?? 'loading model…' }}
          <span class="banner-dim">· PID {{ serverStore.status?.pid }}</span>
        </span>
        <span v-else-if="serverStore.isRunning">
          <strong>Starting</strong> — waiting for model to load…
        </span>
        <span v-else><strong>Server stopped</strong> — go to Serve to start it.</span>
      </div>

      <!-- 8 metric cards -->
      <div class="metrics-grid-8">
        <div class="mcard">
          <div class="mcard-label">Uptime</div>
          <div class="mcard-val mono">{{ uptime }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Active</div>
          <div class="mcard-val">{{ serverStore.isRunning ? serverStore.numRunning : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Queued</div>
          <div class="mcard-val">{{ serverStore.isRunning ? serverStore.numWaiting : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Completed</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalRequests.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Prompt Tokens</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalPromptTokens.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Output Tokens</div>
          <div class="mcard-val mono">{{ serverStore.isRunning ? serverStore.totalCompletionTokens.toLocaleString() : '—' }}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">GPU Memory</div>
          <div class="mcard-val mono">
            {{ serverStore.metalMemoryGb != null ? serverStore.metalMemoryGb.toFixed(2) + ' GB' : '—' }}
          </div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Peak Memory</div>
          <div class="mcard-val mono">
            {{ serverStore.peakMemoryGb != null ? serverStore.peakMemoryGb.toFixed(2) + ' GB' : '—' }}
          </div>
        </div>
      </div>

      <!-- Charts row -->
      <div class="charts-row">
        <div class="chart-card">
          <div class="chart-title">Requests over time</div>
          <div class="chart-legend">
            <span class="legend-dot" style="background:#a78bfa" />Active
            <span class="legend-dot" style="background:#f59e0b" />Queued
          </div>
          <div class="chart-area">
            <Line
              v-if="serverStore.metricsHistory.length > 1"
              :data="requestsChartData"
              :options="lineOpts"
            />
            <div v-else class="chart-empty">Waiting for data…</div>
          </div>
        </div>

        <div class="chart-card">
          <div class="chart-title">GPU memory (GB)</div>
          <div class="chart-area">
            <Line
              v-if="serverStore.metricsHistory.length > 1"
              :data="memoryChartData"
              :options="lineOpts"
            />
            <div v-else class="chart-empty">Waiting for data…</div>
          </div>
        </div>
      </div>

      <!-- Active requests table -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Active requests</div>
          <span v-if="serverStore.metrics?.requests?.length" class="panel-count">
            {{ serverStore.metrics.requests.length }}
          </span>
        </div>
        <div
          v-if="serverStore.isRunning && serverStore.metrics?.requests?.length"
          class="table-wrap"
        >
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Model</th>
                <th class="num">Tokens</th>
                <th class="num">Elapsed (s)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="req in serverStore.metrics!.requests" :key="req.id">
                <td class="mono dim">{{ req.id?.slice(0, 12) ?? '—' }}</td>
                <td class="mono">{{ (req.model || '').split('/').pop() }}</td>
                <td class="num mono">{{ req.tokens_generated ?? '—' }}</td>
                <td class="num mono">{{ req.elapsed_s?.toFixed(1) ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="panel-empty">
          {{ serverStore.isRunning ? 'No active requests right now.' : 'Server not running.' }}
        </div>
      </div>

      <!-- Cache statistics -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">Cache statistics</div>
        </div>
        <div v-if="cacheStats && cacheEntries.length" class="cache-grid">
          <div v-for="entry in cacheEntries" :key="entry.key" class="cache-item">
            <div class="cache-key">{{ entry.key }}</div>
            <div class="cache-val mono">
              {{ typeof entry.value === 'object' ? JSON.stringify(entry.value) : String(entry.value) }}
            </div>
          </div>
        </div>
        <div v-else-if="cacheError" class="panel-empty warn">Cache stats unavailable.</div>
        <div v-else class="panel-empty">
          {{ serverStore.isRunning ? 'Loading…' : 'Server not running.' }}
        </div>
      </div>
    </div>

    <!-- ── SPEED TAB ─────────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Speed'" class="tab-body">
      <BenchmarkPanel />
    </div>

    <!-- ── QUALITY TAB ───────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Quality'" class="tab-body">
      <div class="coming-soon-card">
        <div class="cs-icon">
          <svg viewBox="0 0 20 20" fill="currentColor" width="28" height="28" aria-hidden="true">
            <path fill-rule="evenodd" d="M7 2a1 1 0 00-.707 1.707L7 4.414v3.758a1 1 0 01-.293.707l-4 4C.817 14.769 2.156 18 4.828 18h10.343c2.673 0 4.012-3.231 2.122-5.121l-4-4A1 1 0 0113 8.172V4.414l.707-.707A1 1 0 0013 2H7zm2 6.172V4h2v4.172a3 3 0 00.879 2.12l1.027 1.028a4 4 0 00-2.171.102l-.47.156a4 4 0 01-2.53 0l-.563-.187a1.993 1.993 0 00-.114-.035l1.063-1.063A3 3 0 009 8.172z" clip-rule="evenodd" />
          </svg>
        </div>
        <h3>Quality Benchmarks</h3>
        <p>
          Run standardised quality evaluations — MMLU, GSM8K, HumanEval — against your
          locally-cached models. Results feed into the Kilroy collective intelligence
          layer so the network can recommend the best model for every task type.
        </p>
        <div class="cs-tags">
          <span class="cs-tag">MMLU</span>
          <span class="cs-tag">GSM8K</span>
          <span class="cs-tag">HumanEval</span>
          <span class="cs-tag">TTFT</span>
          <span class="cs-tag">Memory</span>
          <span class="cs-tag">Coherence</span>
        </div>
        <p class="cs-note">Coming next release.</p>
      </div>
    </div>

    <!-- ── SAVED TAB ─────────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Saved'" class="tab-body">

      <!-- Cost Analysis panel -->
      <div class="cost-panel">
        <div class="panel-header">
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14" aria-hidden="true" class="panel-header-icon">
            <path d="M8.433 7.418c.155-.103.346-.196.567-.267v1.698a2.305 2.305 0 01-.567-.267C8.07 8.34 8 8.114 8 8c0-.114.07-.34.433-.582zM11 12.849v-1.698c.22.071.412.164.567.267.364.243.433.468.433.582 0 .114-.07.34-.433.582a2.305 2.305 0 01-.567.267z" />
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a4.535 4.535 0 00-1.676.662C6.602 6.234 6 7.009 6 8c0 .99.602 1.765 1.324 2.246.48.32 1.054.545 1.676.662v1.941c-.391-.127-.68-.317-.843-.504a1 1 0 10-1.51 1.31c.562.649 1.413 1.076 2.353 1.253V15a1 1 0 102 0v-.092a4.535 4.535 0 001.676-.662C13.398 13.766 14 12.991 14 12c0-.99-.602-1.765-1.324-2.246A4.535 4.535 0 0011 9.092V7.151c.391.127.68.317.843.504a1 1 0 101.511-1.31c-.563-.649-1.413-1.076-2.354-1.253V5z" clip-rule="evenodd" />
          </svg>
          <div class="panel-title">Cost Analysis</div>
        </div>

        <!-- Loading skeleton -->
        <div v-if="costLoading" class="cost-body">
          <div class="cost-skeleton-row" />
          <div class="cost-skeleton-row short" />
        </div>

        <!-- Error -->
        <div v-else-if="costError" class="panel-empty warn">
          Could not load cost data.
        </div>

        <!-- Empty state -->
        <div v-else-if="!costStats || costStats.benchmarks_analyzed === 0" class="panel-empty">
          No benchmark data yet — run a benchmark from the Speed tab to see cost estimates.
        </div>

        <!-- Data -->
        <div v-else class="cost-body">
          <div class="cost-summary-row">
            <div class="cost-summary-card">
              <div class="cost-summary-label">Estimated cloud cost to date</div>
              <div class="cost-summary-value cu">${{ costStats.estimated_cloud_cost_usd.toFixed(2) }}</div>
              <div class="cost-summary-sub">
                {{ costStats.total_input_tokens.toLocaleString() }} input &plus;
                {{ costStats.total_output_tokens.toLocaleString() }} output tokens
                across {{ costStats.benchmarks_analyzed }} benchmark runs
              </div>
            </div>
            <div class="cost-summary-card">
              <div class="cost-summary-label">Estimated monthly savings at current usage</div>
              <div class="cost-summary-value si">${{ costStats.estimated_monthly_savings_usd.toFixed(2) }}</div>
              <div class="cost-summary-sub">vs equivalent cloud API calls</div>
            </div>
          </div>

          <div class="table-wrap" v-if="costStats.by_model.length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Tier</th>
                  <th class="num">Tokens generated</th>
                  <th class="num">Equiv. cloud cost</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in costStats.by_model" :key="row.model_id">
                  <td class="mono">{{ row.model_id.split('/').pop() }}</td>
                  <td>
                    <span :class="['tier-badge', `tier-${row.tier}`]">{{ row.tier }}</span>
                  </td>
                  <td class="num mono">{{ row.tokens_generated.toLocaleString() }}</td>
                  <td class="num mono">${{ row.estimated_cost_usd.toFixed(4) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="cost-rates-note">
            Based on equivalent GPT-4o-mini / Claude Haiku / GPT-4o rates for comparable model sizes.
            Small (&lt;7B): ${{ costStats.rates_used.small.input_per_1m }}/1M in &middot;
            ${{ costStats.rates_used.small.output_per_1m }}/1M out&nbsp;&nbsp;
            Medium (7–30B): ${{ costStats.rates_used.medium.input_per_1m }}/1M in &middot;
            ${{ costStats.rates_used.medium.output_per_1m }}/1M out&nbsp;&nbsp;
            Large (30B+): ${{ costStats.rates_used.large.input_per_1m }}/1M in &middot;
            ${{ costStats.rates_used.large.output_per_1m }}/1M out
          </div>
        </div>
      </div>

      <!-- Saved runs list -->
      <div v-if="modelsStore.benchmarkHistory?.length">
        <div class="saved-header">
          <span class="saved-count">{{ modelsStore.benchmarkHistory.length }} saved runs</span>
          <AppButton variant="secondary" size="sm" @click="modelsStore.clearAllBenchmarks?.()">
            Clear all
          </AppButton>
        </div>
        <div class="saved-list">
          <div
            v-for="run in modelsStore.benchmarkHistory"
            :key="run.id"
            class="saved-row"
          >
            <div class="saved-date mono dim">{{ new Date(run.timestamp).toLocaleString() }}</div>
            <div class="saved-model mono">{{ (run.model_id || '').split('/').pop() || '—' }}</div>
            <div class="saved-tps">
              <span v-if="run.avg_tps > 0 && !isNaN(run.avg_tps)" class="tps-badge">
                {{ run.avg_tps.toFixed(1) }} t/s
              </span>
              <span v-else class="dim">—</span>
            </div>
            <div class="saved-actions">
              <button class="icon-btn" title="Delete" @click="modelsStore.deleteBenchmarkResult(run.id)">✕</button>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="coming-soon-card">
        <div class="cs-icon">
          <svg viewBox="0 0 20 20" fill="currentColor" width="28" height="28" aria-hidden="true">
            <path d="M4 3a2 2 0 100 4h12a2 2 0 100-4H4z" />
            <path fill-rule="evenodd" d="M3 8h14v7a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm5 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z" clip-rule="evenodd" />
          </svg>
        </div>
        <h3>Saved Results</h3>
        <p>
          Run a benchmark from the Speed tab — results appear here automatically.
          Pin favourites and compare across runs.
        </p>
        <p class="cs-note">Favorites and comparison coming soon.</p>
      </div>
    </div>

    <!-- ── ADVISOR TAB ───────────────────────────────────────────────────── -->
    <div v-else-if="activeTab === 'Advisor'" class="tab-body">
      <div class="coming-soon-card">
        <div class="cs-icon">
          <svg viewBox="0 0 20 20" fill="currentColor" width="28" height="28" aria-hidden="true">
            <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" />
          </svg>
        </div>
        <h3>AI Advisor</h3>
        <p>
          Describe what you're building — code generation, document summarisation,
          multilingual chat, fast Q&amp;A — and the Advisor will run targeted benchmarks
          across your downloaded models, then recommend the best model and inference
          configuration for that exact task.
        </p>
        <div class="cs-tags">
          <span class="cs-tag">Task matching</span>
          <span class="cs-tag">Auto benchmark</span>
          <span class="cs-tag">Config recommendation</span>
          <span class="cs-tag">Collective data</span>
        </div>
        <p class="cs-note">Coming next release.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Layout ──────────────────────────────────────────────────────────────── */
.benchmark-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-5);
}

.page-header { margin-bottom: var(--space-1); }

.page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--tx-primary);
  letter-spacing: -.02em;
}
.amp { color: var(--tx-muted); font-weight: 400; }

.page-desc {
  font-size: var(--text-sm);
  color: var(--tx-muted);
  margin: var(--space-1) 0 0;
}

/* ── Tab bar ─────────────────────────────────────────────────────────────── */
.tab-bar-wrap {
  border-bottom: 1px solid var(--bd-default);
  margin-bottom: var(--space-1);
}

.tab-bar {
  display: flex;
  gap: 0;
}

.tab-btn {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--tx-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color var(--transition-fast), border-color var(--transition-fast);
  margin-bottom: -1px;
  font-family: inherit;
}

.tab-btn:hover:not(.active) { color: var(--tx-secondary); }

.tab-btn.active {
  color: var(--tx-primary);
  border-bottom-color: var(--si-400);
  font-weight: 600;
}

.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Status banner ───────────────────────────────────────────────────────── */
.status-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 16px;
  border-radius: var(--r-lg);
  font-size: var(--text-sm);
  border: 1px solid transparent;
}
.banner-green  { background: rgba(52,211,153,.08); border-color: rgba(52,211,153,.25); color: #34d399; }
.banner-yellow { background: rgba(245,158,11,.08); border-color: rgba(245,158,11,.25); color: #f59e0b; }
.banner-red    { background: rgba(239,68,68,.08);  border-color: rgba(239,68,68,.2);   color: #f87171; }
.banner-dim    { opacity: .6; }

.banner-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.banner-green  .banner-dot { background: #34d399; box-shadow: 0 0 0 2px rgba(52,211,153,.25); }
.banner-yellow .banner-dot { background: #f59e0b; box-shadow: 0 0 0 2px rgba(245,158,11,.25); }
.banner-red    .banner-dot { background: #f87171; box-shadow: 0 0 0 2px rgba(239,68,68,.2); }

/* ── 8-card metrics grid ─────────────────────────────────────────────────── */
.metrics-grid-8 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

@media (max-width: 900px) { .metrics-grid-8 { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 500px) { .metrics-grid-8 { grid-template-columns: 1fr; } }

.mcard {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
}

.mcard-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.mcard-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--tx-primary);
  line-height: 1.2;
}

/* ── Charts row ──────────────────────────────────────────────────────────── */
.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

@media (max-width: 720px) { .charts-row { grid-template-columns: 1fr; } }

.chart-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  padding: var(--space-4);
}

.chart-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.chart-legend {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  font-size: 11px;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
}

.legend-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.chart-area {
  height: 180px;
  position: relative;
}

.chart-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  color: var(--tx-muted);
}

/* ── Generic panel ───────────────────────────────────────────────────────── */
.panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  background: var(--bg-elevated);
}

.panel-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  flex: 1;
}

.panel-count {
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  padding: 1px 8px;
  color: var(--tx-muted);
}

.panel-empty {
  padding: var(--space-4);
  font-size: var(--text-sm);
  color: var(--tx-muted);
}
.panel-empty.warn { color: #f87171; }

/* ── Data table ──────────────────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; }

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.data-table th {
  padding: var(--space-2) var(--space-4);
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  border-bottom: 1px solid var(--bd-default);
}

.data-table th.num { text-align: right; }

.data-table td {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  color: var(--tx-secondary);
}

.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(255,255,255,.012); }
.data-table .num { text-align: right; }
.data-table .mono { font-family: var(--font-mono); font-size: 12px; }
.data-table .dim  { color: var(--tx-muted); }

/* ── Cache grid ──────────────────────────────────────────────────────────── */
.cache-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1px;
  background: var(--bd-subtle);
}

.cache-item {
  background: var(--bg-surface);
  padding: var(--space-3) var(--space-4);
}

.cache-key {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: 3px;
}

.cache-val {
  font-size: 12px;
  color: var(--tx-secondary);
  word-break: break-all;
}

/* ── Cost Analysis panel ─────────────────────────────────────────────────── */
.cost-panel {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.panel-header-icon {
  color: var(--tx-muted);
  flex-shrink: 0;
}

.cost-body {
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.cost-summary-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

@media (max-width: 600px) { .cost-summary-row { grid-template-columns: 1fr; } }

.cost-summary-card {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
  border-radius: var(--r-lg);
  padding: var(--space-3) var(--space-4);
}

.cost-summary-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-1);
}

.cost-summary-value {
  font-size: 26px;
  font-weight: 700;
  font-family: var(--font-mono);
  line-height: 1.15;
  margin-bottom: 4px;
}
.cost-summary-value.cu { color: var(--cu-400); }
.cost-summary-value.si { color: var(--si-400); }

.cost-summary-sub {
  font-size: 11px;
  color: var(--tx-muted);
  line-height: 1.5;
}

.cost-rates-note {
  font-size: 11px;
  color: var(--tx-muted);
  line-height: 1.6;
  padding-top: var(--space-1);
  border-top: 1px solid var(--bd-subtle);
}

.cost-skeleton-row {
  height: 20px;
  background: var(--bg-elevated);
  border-radius: var(--r-sm);
  margin-bottom: var(--space-2);
  animation: pulse 1.4s ease-in-out infinite;
}
.cost-skeleton-row.short { width: 55%; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}

.tier-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  border: 1px solid var(--bd-default);
}
.tier-small  { color: var(--si-400); background: rgba(var(--si-400-rgb, 99,179,237),.08); }
.tier-medium { color: var(--cu-400); background: rgba(var(--cu-400-rgb, 251,146,60),.08); }
.tier-large  { color: var(--ph-400); background: rgba(var(--ph-400-rgb, 167,139,250),.08); }

/* ── Saved tab ───────────────────────────────────────────────────────────── */
.saved-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.saved-count {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.saved-list {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  overflow: hidden;
}

.saved-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  font-size: 12.5px;
  transition: background var(--transition-fast);
}
.saved-row:last-child { border-bottom: none; }
.saved-row:hover { background: var(--bg-elevated); }

.saved-date  { min-width: 150px; font-size: 11px; }
.saved-model { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.saved-tps   { min-width: 80px; text-align: right; }
.saved-actions { margin-left: var(--space-2); }

.tps-badge {
  font-size: 11.5px;
  font-family: var(--font-mono);
  color: var(--si-300);
  font-weight: 600;
}

/* ── Coming soon card ────────────────────────────────────────────────────── */
.coming-soon-card {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  padding: var(--space-8) var(--space-6);
  text-align: center;
  max-width: 520px;
  margin: var(--space-6) auto;
}

.cs-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--r-lg);
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  color: var(--si-400);
  margin: 0 auto var(--space-3);
}

.coming-soon-card h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--tx-primary);
  margin: 0 0 var(--space-3);
}

.coming-soon-card p {
  font-size: var(--text-sm);
  color: var(--tx-secondary);
  line-height: 1.6;
  margin: 0 0 var(--space-4);
}

.cs-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: center;
  margin-bottom: var(--space-4);
}

.cs-tag {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-muted);
}

.cs-note {
  font-size: 11px !important;
  color: var(--tx-muted) !important;
  margin-bottom: 0 !important;
}

/* ── Shared utilities ────────────────────────────────────────────────────── */
.mono { font-family: var(--font-mono); }
.dim  { color: var(--tx-muted); }

.icon-btn {
  background: none;
  border: none;
  color: var(--tx-muted);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: var(--r-sm);
  transition: color var(--transition-fast);
}
.icon-btn:hover { color: #fca5a5; }
</style>
