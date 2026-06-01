<!-- SPDX-License-Identifier: Apache-2.0 -->
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import html2canvas from 'html2canvas'
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js'
import type { ChartConfiguration } from 'chart.js'
import type { BenchmarkHistoryEntry, QualitySuiteResult } from '@/stores/models'
import { useToastStore } from '@/stores/toast'
import AppButton from '@/components/shared/AppButton.vue'

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Legend, Tooltip)

const SUITE_KEYS = ['gsm8k', 'mmlu', 'humaneval', 'math', 'ifeval'] as const
const SUITE_LABELS: Record<(typeof SUITE_KEYS)[number], string> = {
  gsm8k: 'GSM8K',
  mmlu: 'MMLU',
  humaneval: 'HumanEval',
  math: 'MATH',
  ifeval: 'IFEval',
}

const props = defineProps<{
  runs: BenchmarkHistoryEntry[]
}>()

const emit = defineEmits<{
  close: []
}>()

const toastStore = useToastStore()
const reportEl = ref<HTMLElement | null>(null)
const speedCanvas = ref<HTMLCanvasElement | null>(null)
const qualityCanvas = ref<HTMLCanvasElement | null>(null)
const breakdownCanvas = ref<HTMLCanvasElement | null>(null)
const ttftCanvas = ref<HTMLCanvasElement | null>(null)
const createdAt = ref(new Date())
const previousBodyOverflow = ref('')
const charts: Chart[] = []

const reportRuns = computed(() =>
  [...props.runs].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
)

const hardwareSummaries = computed(() => {
  const items = reportRuns.value
    .map(run => formatHardware(run.hardware))
    .filter((value): value is string => Boolean(value))
  return [...new Set(items)]
})

const speedRuns = computed(() =>
  [...reportRuns.value]
    .filter(run => Number.isFinite(run.avg_tps) && run.avg_tps > 0)
    .sort((a, b) => b.avg_tps - a.avg_tps)
)

const qualityRuns = computed(() =>
  [...reportRuns.value]
    .filter((run): run is BenchmarkHistoryEntry & { overall_score: number } => typeof run.overall_score === 'number')
    .sort((a, b) => b.overall_score - a.overall_score)
)

const ttftRuns = computed(() =>
  [...reportRuns.value]
    .filter((run): run is BenchmarkHistoryEntry & { avg_ttft_ms: number } => typeof run.avg_ttft_ms === 'number')
    .sort((a, b) => a.avg_ttft_ms - b.avg_ttft_ms)
)

const presentSuites = computed(() =>
  SUITE_KEYS.filter((suite) => reportRuns.value.some(run => getSuite(run, suite)?.accuracy != null))
)

const hasQualityData = computed(() => qualityRuns.value.length > 0)
const hasSuiteData = computed(() => presentSuites.value.length > 0)

const chartHeights = computed(() => ({
  speed: `${Math.max(260, speedRuns.value.length * 56)}px`,
  quality: `${Math.max(260, qualityRuns.value.length * 56)}px`,
  ttft: `${Math.max(260, ttftRuns.value.length * 56)}px`,
  breakdown: `${Math.max(320, reportRuns.value.length * 58)}px`,
}))

watch(
  () => props.runs.map(run => `${run.id}-${run.timestamp}-${run.avg_tps}-${run.avg_ttft_ms ?? ''}-${run.overall_score ?? ''}`).join('|'),
  async () => {
    createdAt.value = new Date()
    await nextTick()
    renderCharts()
  },
  { immediate: true }
)

onMounted(async () => {
  previousBodyOverflow.value = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', handleEscape)
  await nextTick()
  renderCharts()
})

onUnmounted(() => {
  document.body.style.overflow = previousBodyOverflow.value
  document.removeEventListener('keydown', handleEscape)
  destroyCharts()
})

function close() {
  emit('close')
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

function destroyCharts() {
  while (charts.length) {
    charts.pop()?.destroy()
  }
}

function renderCharts() {
  destroyCharts()
  const palette = getPalette()
  const suitePalette = getSuitePalette()
  const gridColor = cssVar('--bd-default', 'rgba(148, 163, 184, .22)')
  const tickColor = cssVar('--tx-secondary', '#94a3b8')
  const tooltipBg = cssVar('--bg-surface', '#111827')
  const tooltipBorder = cssVar('--bd-emphasis', 'rgba(255,255,255,.12)')
  const tooltipText = cssVar('--tx-primary', '#f8fafc')

  if (speedCanvas.value && speedRuns.value.length) {
    charts.push(new Chart(speedCanvas.value, horizontalBarConfig({
      labels: speedRuns.value.map(runDisplayName),
      data: speedRuns.value.map(run => round(run.avg_tps, 1)),
      colors: speedRuns.value.map((_, index) => palette[index % palette.length]),
      label: 'Tokens / second',
      tickColor,
      gridColor,
      tooltipBg,
      tooltipBorder,
      tooltipText,
      valueFormatter: value => `${round(value, 1).toFixed(1)} tok/s`,
    })))
  }

  if (qualityCanvas.value && qualityRuns.value.length) {
    charts.push(new Chart(qualityCanvas.value, horizontalBarConfig({
      labels: qualityRuns.value.map(runDisplayName),
      data: qualityRuns.value.map(run => round((run.overall_score ?? 0) * 100, 1)),
      colors: qualityRuns.value.map((_, index) => palette[index % palette.length]),
      label: 'Overall score',
      tickColor,
      gridColor,
      tooltipBg,
      tooltipBorder,
      tooltipText,
      max: 100,
      valueFormatter: value => `${round(value, 1).toFixed(1)}%`,
    })))
  }

  if (ttftCanvas.value && ttftRuns.value.length) {
    charts.push(new Chart(ttftCanvas.value, horizontalBarConfig({
      labels: ttftRuns.value.map(runDisplayName),
      data: ttftRuns.value.map(run => Math.round(run.avg_ttft_ms)),
      colors: ttftRuns.value.map((_, index) => palette[index % palette.length]),
      label: 'TTFT',
      tickColor,
      gridColor,
      tooltipBg,
      tooltipBorder,
      tooltipText,
      valueFormatter: value => `${Math.round(value)} ms`,
    })))
  }

  if (breakdownCanvas.value && hasSuiteData.value) {
    const datasets = presentSuites.value.map((suite, index) => ({
      label: SUITE_LABELS[suite],
      data: reportRuns.value.map(run => {
        const score = getSuite(run, suite)?.accuracy
        return typeof score === 'number' ? round(score * 100, 1) : null
      }),
      backgroundColor: suitePalette[index % suitePalette.length],
      borderRadius: 8,
      borderSkipped: false as const,
      barThickness: 16,
    }))

    charts.push(new Chart(breakdownCanvas.value, {
      type: 'bar',
      data: {
        labels: reportRuns.value.map(runDisplayName),
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        interaction: { mode: 'nearest', intersect: false },
        scales: {
          x: {
            beginAtZero: true,
            max: 100,
            grid: { color: gridColor },
            ticks: {
              color: tickColor,
              callback: value => `${value}%`,
            },
          },
          y: {
            grid: { display: false },
            ticks: { color: tickColor },
          },
        },
        plugins: {
          legend: {
            labels: {
              color: tickColor,
              boxWidth: 12,
              boxHeight: 12,
            },
          },
          tooltip: {
            backgroundColor: tooltipBg,
            borderColor: tooltipBorder,
            borderWidth: 1,
            titleColor: tooltipText,
            bodyColor: tooltipText,
            callbacks: {
              label: context => `${context.dataset.label}: ${round(Number(context.raw ?? 0), 1).toFixed(1)}%`,
            },
          },
        },
      },
    }))
  }
}

function horizontalBarConfig({
  labels,
  data,
  colors,
  label,
  tickColor,
  gridColor,
  tooltipBg,
  tooltipBorder,
  tooltipText,
  valueFormatter,
  max,
}: {
  labels: string[]
  data: number[]
  colors: string[]
  label: string
  tickColor: string
  gridColor: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  valueFormatter: (value: number) => string
  max?: number
}): ChartConfiguration<'bar'> {
  return {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label,
        data,
        backgroundColor: colors,
        borderRadius: 10,
        borderSkipped: false,
        barThickness: 20,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: tooltipBg,
          borderColor: tooltipBorder,
          borderWidth: 1,
          titleColor: tooltipText,
          bodyColor: tooltipText,
          callbacks: {
            label: context => valueFormatter(Number(context.raw ?? 0)),
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          max,
          grid: { color: gridColor },
          ticks: { color: tickColor },
        },
        y: {
          grid: { display: false },
          ticks: { color: tickColor },
        },
      },
    },
  }
}

function cssVar(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function getPalette() {
  return [
    cssVar('--si-500', '#5B6AD0'),
    cssVar('--ph-500', '#22C55E'),
    cssVar('--cu-500', '#D97706'),
    cssVar('--purple-300', '#C4B5FD'),
    cssVar('--cyan-300', '#67E8F9'),
    cssVar('--si-300', '#9AA3E6'),
  ]
}

function getSuitePalette() {
  return [
    cssVar('--si-500', '#5B6AD0'),
    cssVar('--ph-500', '#22C55E'),
    cssVar('--cu-500', '#D97706'),
    cssVar('--purple-300', '#C4B5FD'),
    cssVar('--cyan-300', '#67E8F9'),
  ]
}

function runDisplayName(run: BenchmarkHistoryEntry) {
  return (run.model_id || '').split('/').pop() || run.label || `Run ${run.id}`
}

function formatDate(value?: string) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function formatPercent(value?: number | null) {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—'
}

function formatPercentPrecise(value?: number | null) {
  return typeof value === 'number' ? `${round(value * 100, 1).toFixed(1)}%` : '—'
}

function formatTps(value?: number | null) {
  return typeof value === 'number' && value > 0 ? value.toFixed(1) : '—'
}

function formatTtft(value?: number | null) {
  return typeof value === 'number' ? `${Math.round(value)} ms` : '—'
}

function round(value: number, digits: number) {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

function formatHardware(hardware?: BenchmarkHistoryEntry['hardware']) {
  if (!hardware) return ''
  const parts = [
    hardware.chip,
    hardware.chip_gen,
    hardware.total_ram_gb ? `${hardware.total_ram_gb} GB RAM` : '',
    hardware.os_version,
  ].filter(Boolean)
  return parts.join(' · ')
}

function getSuite(run: BenchmarkHistoryEntry, suite: (typeof SUITE_KEYS)[number]) {
  return run.suites?.[suite] as QualitySuiteResult | undefined
}

function suiteConfidence(suite?: QualitySuiteResult) {
  if (!suite?.accuracy_ci_95) return '—'
  const halfWidth = ((suite.accuracy_ci_95[1] - suite.accuracy_ci_95[0]) / 2) * 100
  return `±${Math.round(halfWidth)}%`
}

function kvQuantLabel(run: BenchmarkHistoryEntry) {
  return run.server_settings?.kv_cache_quantization
    ? `${run.server_settings.kv_cache_quantization_bits ?? 8}-bit`
    : 'Disabled'
}

async function printReport() {
  await nextTick()
  window.print()
}

async function exportImage() {
  if (!reportEl.value) return
  try {
    const canvas = await html2canvas(reportEl.value, {
      scale: 2,
      backgroundColor: '#ffffff',
      useCORS: true,
      logging: false,
    })
    const link = document.createElement('a')
    const stamp = createdAt.value.toISOString().replace(/[:.]/g, '-').slice(0, 19)
    link.href = canvas.toDataURL('image/png')
    link.download = `benchmark-report-${stamp}.png`
    link.click()
    toastStore.success('Benchmark report exported as PNG.')
  } catch (error) {
    console.error('Failed to export benchmark report image', error)
    toastStore.error('Failed to export benchmark report image.')
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="report-overlay" @click.self="close">
      <div class="report-shell" role="dialog" aria-modal="true" aria-labelledby="benchmark-report-title">
        <div class="report-actions no-print">
          <div class="report-actions-left">
            <span class="report-eyebrow">Comparative benchmark</span>
            <span class="report-count">{{ reportRuns.length }} runs selected</span>
          </div>
          <div class="report-actions-right">
            <AppButton variant="secondary" size="sm" @click="printReport">Print / Save as PDF</AppButton>
            <AppButton variant="secondary" size="sm" @click="exportImage">Export Image</AppButton>
            <AppButton variant="ghost" size="sm" class="report-close" aria-label="Close benchmark report" @click="close">Close</AppButton>
          </div>
        </div>

        <article ref="reportEl" class="report-document">
          <header class="report-header">
            <div>
              <p class="report-kicker">vllm-mlx-ui</p>
              <h1 id="benchmark-report-title">Benchmark Comparison Report</h1>
              <p class="report-subtitle">Generated {{ formatDate(createdAt.toISOString()) }}</p>
            </div>
            <div class="report-hardware">
              <div class="summary-stat">
                <span class="summary-stat-label">Runs</span>
                <strong class="summary-stat-value">{{ reportRuns.length }}</strong>
              </div>
              <div class="summary-stat">
                <span class="summary-stat-label">Hardware</span>
                <strong class="summary-stat-value multiline">{{ hardwareSummaries.length ? hardwareSummaries.join('\n') : 'Unknown' }}</strong>
              </div>
            </div>
          </header>

          <section class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Share</h2>
                <p class="section-copy">Models included in this comparison.</p>
              </div>
            </div>
            <div class="share-chips">
              <span v-for="run in reportRuns" :key="run.id" class="share-chip">
                {{ runDisplayName(run) }}
                <small>{{ run.engine_id ?? 'vllm-mlx' }}</small>
              </span>
            </div>
          </section>

          <section class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Summary table</h2>
                <p class="section-copy">High-level comparison across throughput, startup latency, and quality.</p>
              </div>
            </div>
            <div class="table-wrap">
              <table class="report-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Engine</th>
                    <th>Type</th>
                    <th>Date</th>
                    <th class="num">Speed (t/s)</th>
                    <th class="num">TTFT (ms)</th>
                    <th class="num">Overall</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="run in reportRuns" :key="`summary-${run.id}`">
                    <td>
                      <div class="table-title">{{ runDisplayName(run) }}</div>
                      <div class="table-subtitle mono">{{ run.model_id }}</div>
                    </td>
                    <td><span class="engine-pill">{{ run.engine_id ?? 'vllm-mlx' }}</span></td>
                    <td><span class="type-pill" :class="run.benchmark_type ?? 'speed'">{{ run.benchmark_type ?? 'speed' }}</span></td>
                    <td>{{ formatDate(run.timestamp) }}</td>
                    <td class="num mono">{{ formatTps(run.avg_tps) }}</td>
                    <td class="num mono">{{ formatTtft(run.avg_ttft_ms) }}</td>
                    <td class="num mono">{{ formatPercent(run.overall_score) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="speedRuns.length" class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Speed (tok/s)</h2>
                <p class="section-copy">Sorted by average token throughput, highest first.</p>
              </div>
            </div>
            <div class="chart-card" :style="{ height: chartHeights.speed }">
              <canvas ref="speedCanvas" aria-label="Speed chart" />
            </div>
          </section>

          <section v-if="hasQualityData" class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Quality (overall %)</h2>
                <p class="section-copy">Sorted by overall benchmark score, highest first.</p>
              </div>
            </div>
            <div class="chart-card" :style="{ height: chartHeights.quality }">
              <canvas ref="qualityCanvas" aria-label="Quality chart" />
            </div>
          </section>

          <section v-if="hasSuiteData" class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Quality breakdown</h2>
                <p class="section-copy">Grouped view of available benchmark suites for each selected run.</p>
              </div>
            </div>
            <div class="chart-card" :style="{ height: chartHeights.breakdown }">
              <canvas ref="breakdownCanvas" aria-label="Quality breakdown chart" />
            </div>
          </section>

          <section v-if="ttftRuns.length" class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>TTFT (ms)</h2>
                <p class="section-copy">Sorted by time to first token, lowest first.</p>
              </div>
            </div>
            <div class="chart-card" :style="{ height: chartHeights.ttft }">
              <canvas ref="ttftCanvas" aria-label="TTFT chart" />
            </div>
          </section>

          <section class="report-section">
            <div class="section-heading-row">
              <div>
                <h2>Per-model detail</h2>
                <p class="section-copy">All available benchmark metadata and recorded quality/speed details.</p>
              </div>
            </div>
            <div class="detail-grid">
              <article v-for="run in reportRuns" :key="`detail-${run.id}`" class="detail-card">
                <div class="detail-card-header">
                  <div>
                    <h3>{{ runDisplayName(run) }}</h3>
                    <p class="detail-card-subtitle mono">{{ run.model_id }}</p>
                  </div>
                  <span class="type-pill" :class="run.benchmark_type ?? 'speed'">{{ run.benchmark_type ?? 'speed' }}</span>
                </div>

                <div class="detail-kv-grid">
                  <div class="detail-kv"><span>Engine</span><strong>{{ run.engine_id ?? 'vllm-mlx' }}</strong></div>
                  <div class="detail-kv"><span>Date</span><strong>{{ formatDate(run.timestamp) }}</strong></div>
                  <div class="detail-kv"><span>Label</span><strong>{{ run.label || '—' }}</strong></div>
                  <div class="detail-kv"><span>Speed</span><strong class="mono">{{ formatTps(run.avg_tps) }}</strong></div>
                  <div class="detail-kv"><span>TTFT</span><strong class="mono">{{ formatTtft(run.avg_ttft_ms) }}</strong></div>
                  <div class="detail-kv"><span>Overall</span><strong class="mono">{{ formatPercent(run.overall_score) }}</strong></div>
                  <div class="detail-kv"><span>Max tokens</span><strong class="mono">{{ run.max_tokens ?? '—' }}</strong></div>
                  <div class="detail-kv"><span>Thinking</span><strong>{{ run.enable_thinking == null ? '—' : run.enable_thinking ? 'Enabled' : 'Disabled' }}</strong></div>
                  <div class="detail-kv"><span>KV cache quant</span><strong>{{ kvQuantLabel(run) }}</strong></div>
                  <div class="detail-kv"><span>Hardware</span><strong>{{ formatHardware(run.hardware) || '—' }}</strong></div>
                </div>

                <div v-if="presentSuites.length" class="detail-subsection">
                  <h4>Suite scores</h4>
                  <div class="suite-grid">
                    <div v-for="suite in presentSuites" :key="`${run.id}-${suite}`" class="suite-card">
                      <span>{{ SUITE_LABELS[suite] }}</span>
                      <strong>{{ formatPercentPrecise(getSuite(run, suite)?.accuracy) }}</strong>
                      <small>{{ suiteConfidence(getSuite(run, suite)) }}</small>
                      <small>
                        {{ getSuite(run, suite)?.correct ?? 0 }}/{{ getSuite(run, suite)?.total ?? 0 }} correct
                      </small>
                    </div>
                  </div>
                </div>

                <div v-if="run.per_prompt?.length" class="detail-subsection">
                  <h4>Per-prompt results</h4>
                  <div class="table-wrap">
                    <table class="report-table prompt-table">
                      <thead>
                        <tr>
                          <th>Prompt</th>
                          <th class="num">TTFT</th>
                          <th class="num">t/s</th>
                          <th class="num">Total</th>
                          <th class="num">Tokens</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(prompt, index) in run.per_prompt" :key="`${run.id}-prompt-${index}`">
                          <td>{{ prompt.prompt }}</td>
                          <td class="num mono">{{ formatTtft(prompt.ttft_ms) }}</td>
                          <td class="num mono">{{ formatTps(prompt.tps) }}</td>
                          <td class="num mono">{{ prompt.total_ms != null ? Math.round(prompt.total_ms) + ' ms' : '—' }}</td>
                          <td class="num mono">{{ prompt.tokens ?? '—' }}</td>
                          <td>{{ prompt.error ? `Error: ${prompt.error}` : 'OK' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </article>
            </div>
          </section>
        </article>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.report-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(8, 8, 9, .78);
  backdrop-filter: blur(16px);
  padding: var(--space-5);
  overflow: auto;
}

.report-shell {
  width: min(1320px, 100%);
  margin: 0 auto;
}

.report-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  color: var(--tx-primary);
}

.report-actions-left,
.report-actions-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.report-eyebrow,
.report-count {
  color: var(--tx-secondary);
  font-size: 14px;
}

.report-document {
  background:
    radial-gradient(circle at top right, rgba(91, 106, 208, .12), transparent 28%),
    linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,0)),
    var(--bg-surface);
  border: 1px solid var(--bd-emphasis);
  border-radius: 24px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, .35);
  padding: var(--space-8);
  color: var(--tx-primary);
}

.report-header {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, .8fr);
  gap: var(--space-6);
  align-items: start;
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--bd-default);
}

.report-kicker {
  margin: 0 0 var(--space-2);
  color: var(--ac-primary);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(28px, 4vw, 42px);
  line-height: 1.05;
}

.report-subtitle {
  margin: var(--space-3) 0 0;
  color: var(--tx-secondary);
}

.report-hardware {
  display: grid;
  gap: var(--space-3);
}

.summary-stat {
  padding: var(--space-4);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-xl);
  background: rgba(255, 255, 255, .03);
}

.summary-stat-label {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--tx-secondary);
  font-size: 14px;
}

.summary-stat-value {
  display: block;
  font-size: 18px;
  line-height: 1.4;
}

.multiline {
  white-space: pre-line;
}

.report-section {
  margin-top: var(--space-7);
}

.section-heading-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.section-heading-row h2,
.detail-card h3,
.detail-subsection h4 {
  margin: 0;
}

.section-copy,
.detail-card-subtitle {
  margin: var(--space-2) 0 0;
  color: var(--tx-secondary);
}

.share-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.share-chip {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--r-xl);
  border: 1px solid var(--ac-border);
  background: var(--ac-bg);
  font-weight: 600;
}

.share-chip small {
  color: var(--tx-secondary);
  font-size: 12px;
}

.table-wrap {
  overflow-x: auto;
}

.report-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}

.report-table th,
.report-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--bd-subtle);
  text-align: left;
  vertical-align: top;
}

.report-table th {
  color: var(--tx-secondary);
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.report-table .num {
  text-align: right;
}

.table-title {
  font-weight: 600;
}

.table-subtitle {
  margin-top: 4px;
  color: var(--tx-tertiary);
  font-size: 13px;
}

.chart-card {
  position: relative;
  padding: var(--space-4);
  border-radius: 22px;
  border: 1px solid var(--bd-default);
  background: rgba(255, 255, 255, .03);
}

.chart-card canvas {
  width: 100% !important;
  height: 100% !important;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--space-5);
}

.detail-card {
  padding: var(--space-5);
  border-radius: 22px;
  border: 1px solid var(--bd-default);
  background: rgba(255, 255, 255, .03);
  break-inside: avoid;
}

.detail-card-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: flex-start;
}

.detail-kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.detail-kv {
  padding: var(--space-3);
  border-radius: var(--r-lg);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
}

.detail-kv span {
  display: block;
  margin-bottom: 6px;
  color: var(--tx-secondary);
  font-size: 13px;
}

.detail-subsection {
  margin-top: var(--space-5);
}

.suite-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.suite-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3);
  border-radius: var(--r-lg);
  background: var(--bg-elevated);
  border: 1px solid var(--bd-subtle);
}

.suite-card span,
.suite-card small {
  color: var(--tx-secondary);
}

.engine-pill,
.type-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--r-pill);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .02em;
}

.engine-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  color: var(--tx-primary);
}

.type-pill.speed {
  background: rgba(74, 222, 128, .12);
  color: var(--ph-500);
}

.type-pill.quality {
  background: rgba(91, 106, 208, .12);
  color: var(--si-500);
}

.type-pill.custom {
  background: rgba(245, 158, 11, .12);
  color: var(--cu-500);
}

.mono {
  font-family: var(--font-mono);
}

.prompt-table td:first-child {
  max-width: 420px;
  white-space: pre-wrap;
}

@media (max-width: 920px) {
  .report-overlay {
    padding: var(--space-3);
  }

  .report-document {
    padding: var(--space-5);
    border-radius: 18px;
  }

  .report-header,
  .detail-kv-grid {
    grid-template-columns: 1fr;
  }

  .report-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .report-actions-right {
    justify-content: flex-end;
  }
}

@media print {
  .report-overlay {
    position: static;
    inset: auto;
    background: #fff;
    backdrop-filter: none;
    padding: 0;
    overflow: visible;
  }

  .report-shell {
    width: 100%;
    max-width: none;
  }

  .report-document {
    background: #fff;
    color: #111827;
    box-shadow: none;
    border: none;
    border-radius: 0;
    padding: 0;
  }

  .summary-stat,
  .chart-card,
  .detail-card,
  .detail-kv,
  .suite-card,
  .engine-pill,
  .share-chip {
    background: #fff !important;
    color: #111827 !important;
    border-color: rgba(17, 24, 39, .12) !important;
  }

  .report-table th,
  .summary-stat-label,
  .section-copy,
  .detail-card-subtitle,
  .suite-card span,
  .suite-card small,
  .share-chip small,
  .report-subtitle {
    color: #4b5563 !important;
  }

  .no-print {
    display: none !important;
  }

  .report-section,
  .detail-card,
  .chart-card {
    break-inside: avoid;
    page-break-inside: avoid;
  }
}
</style>
