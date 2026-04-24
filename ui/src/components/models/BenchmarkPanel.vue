<script setup lang="ts">
import { ref, computed } from 'vue'
import { Bar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
  Legend,
} from 'chart.js'
import type { ChartData, ChartOptions } from 'chart.js'
import AppButton from '@/components/shared/AppButton.vue'
import { useModelsStore } from '@/stores/models'
import type { BenchmarkConfig } from '@/stores/models'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)

const modelsStore = useModelsStore()

const cachedModels = computed(() => modelsStore.models.filter(m => m.cached))
const selectedModels = ref<string[]>([])

const config = ref<BenchmarkConfig>({
  prompt: 'Tell me about the history of computing in 3 paragraphs.',
  runs: 3,
  max_tokens: 256,
})

const selectedUseCase = ref<string | null>(null)
const useCases = ['Agentic', 'Research', 'Personal', 'Business', 'Code']

function toggleModel(id: string) {
  const idx = selectedModels.value.indexOf(id)
  if (idx === -1) selectedModels.value.push(id)
  else selectedModels.value.splice(idx, 1)
}

async function runBenchmark() {
  if (selectedModels.value.length === 0) return
  await modelsStore.runBenchmark(selectedModels.value, config.value)
}

function runAgain() {
  modelsStore.benchmarkResults = null
  selectedUseCase.value = null
}

const chartData = computed((): ChartData<'bar'> | null => {
  const results = modelsStore.benchmarkResults
  if (!results || results.length === 0) return null

  const maxIdx = results.reduce(
    (best, r, idx, arr) => (r.avg_tps > arr[best].avg_tps ? idx : best),
    0
  )

  return {
    labels: results.map(r => r.model_id.split('/').pop() ?? r.model_id),
    datasets: [
      {
        label: 'Avg tokens/sec',
        data: results.map(r => r.avg_tps),
        backgroundColor: results.map((_, idx) =>
          idx === maxIdx ? 'rgba(245, 158, 11, 0.70)' : 'rgba(91, 106, 208, 0.70)'
        ),
        borderColor: results.map((_, idx) =>
          idx === maxIdx ? '#F59E0B' : '#5B6AD0'
        ),
        borderWidth: 1,
        borderRadius: 4,
      },
    ],
  }
})

const chartDataSafe = computed((): ChartData<'bar'> =>
  chartData.value ?? { labels: [], datasets: [] }
)

const chartOptions: ChartOptions<'bar'> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#2C2C2E',
      borderColor: 'rgba(255,255,255,.09)',
      borderWidth: 1,
      titleColor: '#E5E5EA',
      bodyColor: '#AEAEB2',
    },
  },
  scales: {
    x: {
      grid: { color: 'rgba(255,255,255,.05)' },
      ticks: { color: '#AEAEB2' },
    },
    y: {
      grid: { color: 'rgba(255,255,255,.05)' },
      ticks: { color: '#AEAEB2' },
      title: {
        display: true,
        text: 'tokens/sec',
        color: '#636366',
      },
    },
  },
}

function bestModelForUseCase(_useCase: string): string | null {
  const results = modelsStore.benchmarkResults
  if (!results || results.length === 0) return null
  const best = results.reduce((a, b) => (a.avg_tps > b.avg_tps ? a : b))
  return best.model_id.split('/').pop() ?? best.model_id
}
</script>

<template>
  <div class="benchmark-panel">
    <!-- Configure state -->
    <template v-if="!modelsStore.benchmarkResults">
      <div class="configure-section">
        <div class="section-label">Select Models</div>
        <div v-if="cachedModels.length === 0" class="empty-hint">
          No cached models. Download models in the Library tab first.
        </div>
        <div v-else class="model-checklist">
          <label
            v-for="model in cachedModels"
            :key="model.id"
            class="model-check-item"
          >
            <input
              type="checkbox"
              :value="model.id"
              :checked="selectedModels.includes(model.id)"
              class="check-input"
              @change="toggleModel(model.id)"
            />
            <span class="check-name">{{ model.name || model.id.split('/').pop() }}</span>
            <span class="check-quant">{{ model.quantization }}</span>
            <span class="check-size">{{ model.size_gb.toFixed(1) }} GB</span>
          </label>
        </div>
      </div>

      <div class="configure-section">
        <div class="section-label">Configuration</div>
        <div class="config-grid">
          <div class="config-field full-width">
            <label class="field-label">Prompt</label>
            <textarea
              v-model="config.prompt"
              class="config-textarea"
              rows="3"
            />
          </div>
          <div class="config-field">
            <label class="field-label">Runs per model</label>
            <input
              v-model.number="config.runs"
              type="number"
              min="1"
              max="20"
              class="config-input"
            />
          </div>
          <div class="config-field">
            <label class="field-label">Max tokens</label>
            <input
              v-model.number="config.max_tokens"
              type="number"
              min="64"
              max="2048"
              class="config-input"
            />
          </div>
        </div>
      </div>

      <div class="run-row">
        <AppButton
          variant="primary"
          :loading="modelsStore.benchmarking"
          :disabled="selectedModels.length === 0 || modelsStore.benchmarking"
          @click="runBenchmark"
        >
          <template v-if="modelsStore.benchmarking">Running…</template>
          <template v-else>Run Benchmark</template>
        </AppButton>
        <span v-if="modelsStore.benchmarking" class="bench-progress">
          Running {{ selectedModels.length }} model{{ selectedModels.length > 1 ? 's' : '' }}…
        </span>
      </div>
    </template>

    <!-- Results state -->
    <template v-else>
      <div class="results-header">
        <span class="results-title">Results</span>
        <AppButton variant="secondary" size="sm" @click="runAgain">Run Again</AppButton>
      </div>

      <div class="results-table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th>Model</th>
              <th class="num">Avg t/s</th>
              <th class="num">Median t/s</th>
              <th class="num">Min</th>
              <th class="num">Max</th>
              <th class="num">Runs</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in modelsStore.benchmarkResults" :key="r.model_id">
              <td class="mono-cell">{{ r.model_id.split('/').pop() }}</td>
              <td class="num mono-cell">{{ r.avg_tps.toFixed(1) }}</td>
              <td class="num mono-cell">{{ r.median_tps.toFixed(1) }}</td>
              <td class="num mono-cell">{{ r.min_tps.toFixed(1) }}</td>
              <td class="num mono-cell">{{ r.max_tps.toFixed(1) }}</td>
              <td class="num mono-cell">{{ r.runs }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="chartData" class="chart-wrap">
        <Bar :data="chartDataSafe" :options="chartOptions" />
      </div>

      <div class="usecase-section">
        <div class="section-label">Use-Case Analysis</div>
        <div class="usecase-chips">
          <button
            v-for="uc in useCases"
            :key="uc"
            class="uc-chip"
            :class="{ active: selectedUseCase === uc }"
            @click="selectedUseCase = selectedUseCase === uc ? null : uc"
          >{{ uc }}</button>
        </div>
        <div v-if="selectedUseCase" class="uc-result-card">
          <div class="uc-label">Best for {{ selectedUseCase }}</div>
          <div class="uc-model">{{ bestModelForUseCase(selectedUseCase) }}</div>
          <div class="uc-reason">Highest average throughput among benchmarked models.</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.benchmark-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-3);
}

/* Configure */
.configure-section {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-4) var(--space-5);
}

.empty-hint {
  font-size: var(--text-sm);
  color: var(--tx-muted);
}

.model-checklist {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.model-check-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.model-check-item:hover { background: var(--bg-elevated); }

.check-input {
  accent-color: var(--si-500);
  width: 14px;
  height: 14px;
  cursor: pointer;
  flex-shrink: 0;
}

.check-name {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--tx-primary);
  flex: 1;
}

.check-quant {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--tx-muted);
}

.check-size {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--tx-muted);
  min-width: 48px;
  text-align: right;
}

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.config-field.full-width { grid-column: 1 / -1; }

.field-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
}

.config-textarea,
.config-input {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-md);
  color: var(--tx-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  padding: 7px 12px;
  resize: vertical;
  box-sizing: border-box;
  transition: border-color var(--transition-fast);
}

.config-textarea:focus,
.config-input:focus {
  outline: none;
  border-color: var(--bd-focus);
  box-shadow: 0 0 0 3px rgba(91, 106, 208, .12);
}

.run-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.bench-progress {
  font-size: var(--text-sm);
  color: var(--tx-muted);
}

/* Results */
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.results-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--tx-muted);
}

.results-table-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  overflow: hidden;
}

.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.results-table th {
  padding: var(--space-2) var(--space-4);
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  border-bottom: 1px solid var(--bd-default);
  background: var(--bg-elevated);
}

.results-table th.num { text-align: right; }

.results-table td {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--bd-subtle);
  color: var(--tx-secondary);
}

.results-table tr:last-child td { border-bottom: none; }
.results-table tr:hover td { background: rgba(255, 255, 255, .012); }

.mono-cell {
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.num { text-align: right; }

.chart-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-4);
  height: 260px;
}

/* Use-case */
.usecase-section {
  background: var(--bg-surface);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-lg);
  padding: var(--space-4) var(--space-5);
}

.usecase-chips {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}

.uc-chip {
  padding: 4px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--bd-default);
  border-radius: var(--r-pill);
  color: var(--tx-secondary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.uc-chip:hover:not(.active) {
  border-color: var(--bd-emphasis);
  color: var(--tx-primary);
}

.uc-chip.active {
  background: var(--ac-bg);
  border-color: var(--ac-border);
  color: var(--si-300);
  font-weight: 600;
}

.uc-result-card {
  background: var(--bg-elevated);
  border: 1px solid var(--ac-border);
  border-radius: var(--r-lg);
  padding: var(--space-4);
}

.uc-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--tx-muted);
  margin-bottom: var(--space-2);
}

.uc-model {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--si-300);
  margin-bottom: var(--space-1);
}

.uc-reason {
  font-size: var(--text-sm);
  color: var(--tx-tertiary);
}
</style>
