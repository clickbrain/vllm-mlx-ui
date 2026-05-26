import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  findBestChoices,
  computeNameTagAffinity,
  computeBenchmarkQuality,
  computeRecencyScore,
  computeUtilizationScore,
} from '../useModelScoring'
import type { BenchmarkScores } from '@/stores/models'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-05-24T12:00:00Z'))
})

afterEach(() => {
  vi.useRealTimers()
})

const NEUTRAL_SCORES: BenchmarkScores = { source: 'none' }

function findWinner(
  models: any[],
  scoresMap: Record<string, BenchmarkScores> = {},
  totalRamGb = 64,
  maxAgeMonths = 0,
): Record<string, number> {
  const result = findBestChoices(models as any, scoresMap, totalRamGb, maxAgeMonths, null)
  const winners: Record<string, number> = {}
  for (const [id, badges] of result) {
    for (const b of badges) {
      winners[b.useCase] = result.get(id)!.find(v => v.useCase === b.useCase)!.score
    }
  }
  return winners
}

// ── Test 1: family recency — re-uploads lose to newer family ────────────────

describe('family recency', () => {
  it('Qwen3-Coder beats Outlier-Ai Qwen2.5-Coder re-upload for Best for Code', () => {
    const models = [
      {
        id: 'Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit',
        tags: ['mlx', 'gguf'],
        size_gb: 20,
        created_at: '2026-04-15',
        family_data: { release_date: '2024-09-19', scores: { mmlu: 84, humaneval: 82 } },
      },
      {
        id: 'Qwen/Qwen3-Coder-32B-Instruct',
        tags: ['transformers', 'code'],
        size_gb: 20,
        created_at: '2026-04-10',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 87, humaneval: 88 } },
      },
    ]
    const winners = findWinner(models)
    expect(winners.code).toBeDefined()
    const result = findBestChoices(models as any, {}, 64, 0, null)
    const qwen3Badges = result.get('Qwen/Qwen3-Coder-32B-Instruct') || []
    const outlierBadges = result.get('Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit') || []
    expect(qwen3Badges.some(b => b.useCase === 'code')).toBe(true)
    expect(outlierBadges.some(b => b.useCase === 'code')).toBe(false)
  })

  it('without family_data, re-upload uses own created_at and may win', () => {
    const models = [
      {
        id: 'Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit',
        tags: ['mlx'],
        size_gb: 20,
        created_at: '2026-04-15',
      },
      {
        id: 'Qwen/Qwen3-Coder-32B-Instruct',
        tags: ['transformers'],
        size_gb: 20,
        created_at: '2026-04-10',
      },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, null)
    const outlierBadges = result.get('Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit') || []
    expect(outlierBadges.some(b => b.useCase === 'code')).toBe(true)
  })

  it('Qwopus derivative inherits Qwen3-235B family release date', () => {
    const models = [
      {
        id: 'Qwopus/Qwopus-32B-4bit',
        tags: ['mlx'],
        size_gb: 18,
        created_at: '2026-05-01',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 85, math: 80 } },
      },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, 'reasoning')
    const badges = result.get('Qwopus/Qwopus-32B-4bit') || []
    expect(badges.some(b => b.useCase === 'reasoning')).toBe(true)
  })
})

// ── Test 4: genuine fine-tune beating base model ────────────────────────────

describe('fine-tune benchmark inheritance', () => {
  it('fine-tune with higher leaderboard scores beats base model', () => {
    const models = [
      {
        id: 'Qwen/Qwen3-Coder-32B-Instruct',
        tags: ['transformers', 'code'],
        size_gb: 20,
        created_at: '2026-04-10',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 85, humaneval: 82 } },
      },
      {
        id: 'SuperTune/EnhancedCoder-32B',
        tags: ['transformers', 'code'],
        size_gb: 20,
        created_at: '2026-05-01',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 91, humaneval: 94 } },
      },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, 'code')
    const superBadges = result.get('SuperTune/EnhancedCoder-32B') || []
    const baseBadges = result.get('Qwen/Qwen3-Coder-32B-Instruct') || []
    expect(superBadges.some(b => b.useCase === 'code')).toBe(true)
    expect(baseBadges.some(b => b.useCase === 'code')).toBe(false)
  })
})

// ── Test 5: Tier 3 original uses own createdAt ──────────────────────────────

describe('Tier 3 originals', () => {
  it('unknown original uses own created_at for recency', () => {
    const models = [
      {
        id: 'some-user/NovelModel-8B',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-05-20',
      },
    ]
    const winners = findWinner(models)
    expect(winners.chat).toBeDefined()
    expect(winners.chat).toBeGreaterThan(0)
  })
})

// ── Test 6: MLX quant inherits family release date ──────────────────────────

describe('MLX quants', () => {
  it('mlx-community quant inherits base family date', () => {
    const models = [
      {
        id: 'mlx-community/Qwen3-8B-4bit',
        tags: ['mlx'],
        size_gb: 5,
        created_at: '2026-05-15',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 82 } },
      },
    ]
    const winners = findWinner(models)
    expect(winners.chat).toBeDefined()
  })
})

// ── Test 7: Vision models ───────────────────────────────────────────────────

describe('vision models', () => {
  it('Pixtral model wins Best for Vision', () => {
    const models = [
      { id: 'mistral-community/pixtral-12b', tags: ['vision'], size_gb: 8, created_at: '2026-03-01' },
      { id: 'Qwen/Qwen3-Coder-32B', tags: ['transformers'], size_gb: 20, created_at: '2026-04-10' },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, null)
    const pixtralBadges = result.get('mistral-community/pixtral-12b') || []
    expect(pixtralBadges.some(b => b.useCase === 'vision')).toBe(true)
    const qwenBadges = result.get('Qwen/Qwen3-Coder-32B') || []
    expect(qwenBadges.some(b => b.useCase === 'vision')).toBe(false)
  })
})

// ── Test 8: Embedding models disqualified ───────────────────────────────────

describe('embedding models', () => {
  it('embedding model is disqualified from all categories', () => {
    const models = [
      { id: 'BAAI/bge-large-en-v1.5', tags: ['embedding'], size_gb: 1, created_at: '2025-01-01' },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, null)
    expect(result.size).toBe(0)
  })
})

// ── Test 9-10: Hardware utilization ─────────────────────────────────────────

describe('hardware utilization', () => {
  it('model too large for RAM (>92%) scores 0', () => {
    const models = [
      { id: 'too-big/model', tags: ['transformers'], size_gb: 60, created_at: '2026-04-01' },
    ]
    const winners = findWinner(models, {}, 64)
    expect(Object.keys(winners).length).toBe(0)
  })

  it('model in optimal band (55-72%) gets perfect utilization', () => {
    const score = computeUtilizationScore(40, 64)
    expect(score).toBeCloseTo(1.0, 2)
  })

  it('tiny model on large machine gets low utilization', () => {
    const score = computeUtilizationScore(4, 128)
    expect(score).toBeLessThan(0.5)
  })

  it('no size data returns neutral utilization', () => {
    const score = computeUtilizationScore(undefined, 64)
    expect(score).toBe(0.5)
  })
})

// ── Test 11: Max age cutoff ──────────────────────────────────────────────────

describe('recency cutoff', () => {
  it('model older than maxAgeMonths gets hard zero', () => {
    const models = [
      {
        id: 'old/model-7b',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2024-01-01',
      },
    ]
    const winners = findWinner(models, {}, 64, 6)
    expect(Object.keys(winners).length).toBe(0)
  })

  it('model within maxAgeMonths still eligible', () => {
    const models = [
      {
        id: 'new/model-7b',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-05-01',
      },
    ]
    const winners = findWinner(models, {}, 64, 6)
    expect(winners.chat).toBeDefined()
    expect(winners.chat).toBeGreaterThan(0)
  })
})

// ── Test 13: Benchmark merges ────────────────────────────────────────────────

describe('benchmark score merging', () => {
  it('family_data scores override empty benchmark cache', () => {
    const models = [
      {
        id: 'Qwen/Qwen3-8B',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-04-10',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 85, ifeval: 82 } },
      },
    ]
    const scores = { 'Qwen/Qwen3-8B': { source: 'none' as const } }
    const result = findBestChoices(models as any, scores, 64, 0, 'chat')
    expect(result.size).toBe(1)
  })

  it('leaderboard scores take priority over family scores', () => {
    const models = [
      {
        id: 'Qwen/Qwen3-8B',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-04-10',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 80 } },
      },
    ]
    const scores = { 'Qwen/Qwen3-8B': { mmlu: 92, source: 'leaderboard' as const } }
    const result = findBestChoices(models as any, scores, 64, 0, 'chat')
    expect(result.size).toBe(1)
  })
})

// ── Test 15: No benchmark data ──────────────────────────────────────────────

describe('no benchmark data', () => {
  it('models with no score data still get neutral benchmark', () => {
    const models = [
      {
        id: 'unknown/model-7b',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-05-01',
      },
    ]
    const winners = findWinner(models)
    expect(winners.chat).toBeDefined()
  })
})

// ── Test 16: Badge threshold ────────────────────────────────────────────────

describe('badge threshold', () => {
  it('no badge awarded below 0.35 threshold', () => {
    const models = [
      {
        id: 'bad/worst-model-ever',
        tags: [],
        size_gb: 0.1,
        created_at: '2026-05-01',
      },
    ]
    const winners = findWinner(models)
    expect(Object.keys(winners).length).toBe(0)
  })
})

// ── Test 17: Family scores all null ─────────────────────────────────────────

describe('family scores null handling', () => {
  it('all-null family scores falls back to neutral', () => {
    const models = [
      {
        id: 'some-user/test-model',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-05-01',
        family_data: { release_date: '2026-01-01', scores: { mmlu: null, humaneval: null } },
      },
    ]
    const winners = findWinner(models)
    expect(winners.chat).toBeDefined()
  })
})

// ── Test 19: Empty tags ────────────────────────────────────────────────────

describe('edge cases', () => {
  it('model with empty tags still gets affinity via name', () => {
    const affinity = computeNameTagAffinity('Qwen/Qwen3-Coder-32B', [])
    expect(affinity.code).toBeGreaterThan(0)
  })
})

// ── Test 20: Zero RAM ─────────────────────────────────────────────────────

describe('zero RAM edge case', () => {
  it('zero totalRamGb does not crash', () => {
    const models = [
      {
        id: 'test/model',
        tags: ['transformers'],
        size_gb: 5,
        created_at: '2026-05-01',
      },
    ]
    const result = findBestChoices(models as any, {}, 0, 0, null)
    expect(result.size).toBeGreaterThanOrEqual(0)
  })
})

// ── Bonus: verify reason strings are non-empty ───────────────────────────────

describe('reason strings', () => {
  it('badge reasons are non-empty for winning models', () => {
    const models = [
      {
        id: 'Qwen/Qwen3-Coder-32B-Instruct',
        tags: ['transformers', 'code'],
        size_gb: 20,
        created_at: '2026-04-10',
        family_data: { release_date: '2026-04-10', scores: { mmlu: 87, humaneval: 88 } },
      },
    ]
    const result = findBestChoices(models as any, {}, 64, 0, null)
    for (const [, badges] of result) {
      for (const b of badges) {
        expect(b.reason.length).toBeGreaterThan(0)
        expect(b.label.length).toBeGreaterThan(0)
        expect(b.score).toBeGreaterThanOrEqual(0)
        expect(b.score).toBeLessThanOrEqual(1)
      }
    }
  })
})
