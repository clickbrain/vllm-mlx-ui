/**
 * Multi-signal model scoring engine.
 *
 * Produces "Best Choice" badges by combining:
 *   1. Name/tag affinity   (35%) — what task the model was designed for
 *   2. Benchmark quality   (30%) — empirical performance from our cache
 *   3. Recency             (25%) — punishes old models, hard-zeros at maxAgeMonths
 *   4. Hardware utilization(10%) — peaks when model fits optimally, not just barely
 *   5. Popularity          (10%) — log-scaled download count, floored at 0.15
 *
 * Final score is in [0, ~1]; threshold 0.35 required for a badge.
 *
 * This module has NO Vue reactive state — it exports pure functions.
 * ModelsView calls findBestChoices() inside a computed().
 */

import type { BenchmarkScores } from '@/stores/models'

export type UseCase = 'chat' | 'code' | 'reasoning' | 'vision'

export interface ModelBadge {
  useCase: UseCase
  label: string       // e.g. "Best for Chat"
  reason: string      // e.g. "40 GB fits your 64 GB well · MMLU ~87% · 1mo ago"
  score: number       // 0–1, useful for debugging
  color: string       // CSS custom property reference, e.g. "var(--badge-chat)"
}

// ── Use-case label config ────────────────────────────────────────────────────
const BADGE_CONFIG: Record<UseCase, { label: string; color: string; icon: string }> = {
  chat:      { label: 'Best for Chat',      color: 'var(--badge-chat)',      icon: '💬' },
  code:      { label: 'Best for Code',      color: 'var(--badge-code)',      icon: '💻' },
  reasoning: { label: 'Best for Reasoning', color: 'var(--badge-reasoning)', icon: '🧠' },
  vision:    { label: 'Best for Vision',    color: 'var(--badge-vision)',    icon: '🖼️' },
}

// ── 1. Name/tag affinity ─────────────────────────────────────────────────────

interface AffinityVector {
  chat: number
  code: number
  reasoning: number
  vision: number
  disqualified: boolean  // embedding/reranking models
}

const VISION_RE   = /\bvl\b|-vl-|vlm|pixtral|llava|internvl|qwen.*vl|phi.*vis|moondream|idefics|paligemma/i
const EMBED_RE    = /embed(?:ding)?|bge-|e5-|nomic-embed|rerank|gte-|bge_m3/i
const CODE_RE     = /\bcoder\b|coding|-code\b|starcoder|codestral|deepseek-coder|qwen.*coder|granite.*code|yi.*coder/i
const REASONING_RE = /\bthinking\b|r1\b|r2\b|qwq\b|deepseek-r[12]|reasoning|skywork-o|phi.*reasoning|nemotron.*think|llama.*instruct.*3[56]/i
const INSTRUCT_RE  = /instruct|chat|-it\b|assistant|-chat\b/i

export function computeNameTagAffinity(modelId: string, tags: string[]): AffinityVector {
  const name = modelId.toLowerCase()
  const tagStr = tags.join(' ').toLowerCase()
  const combined = name + ' ' + tagStr

  if (EMBED_RE.test(combined)) {
    return { chat: 0, code: 0, reasoning: 0, vision: 0, disqualified: true }
  }

  if (VISION_RE.test(combined)) {
    // Vision models can do some chat but are primarily vision
    return { chat: 0.5, code: 0, reasoning: 0, vision: 1.0, disqualified: false }
  }

  const isInstruct = INSTRUCT_RE.test(combined)
  const isCode     = CODE_RE.test(combined)
  const isReasoning = REASONING_RE.test(combined)

  let chat = isInstruct ? 0.90 : 0.40
  let code = isCode ? 0.95 : (isInstruct ? 0.45 : 0.20)
  let reasoning = isReasoning ? 0.95 : (isInstruct ? 0.40 : 0.15)

  // Code specialists: modest chat ability
  if (isCode && !isReasoning)      { chat = Math.min(chat, 0.60); reasoning = 0.30 }
  // Reasoning specialists: lower instruct chat score (they tend to over-think)
  if (isReasoning && !isCode)      { chat = chat * 0.75 }
  // Both code + reasoning (e.g. Qwen-Coder thinking variants)
  if (isCode && isReasoning)       { chat = chat * 0.65 }

  return { chat, code, reasoning, vision: 0.10, disqualified: false }
}

// ── 2. Benchmark quality per use case ────────────────────────────────────────

/** Returns 0–1. Missing metrics are skipped (not zero) and re-normalized. */
export function computeBenchmarkQuality(scores: BenchmarkScores, useCase: UseCase): number {
  if (scores.source === 'none') return 0.5  // neutral — no data

  const hasMmlu      = scores.mmlu      != null
  const hasHuman     = scores.humaneval != null
  const hasMath      = scores.math      != null
  const hasGpqa      = scores.gpqa      != null
  const hasIfeval    = scores.ifeval    != null

  const n  = (v: number | undefined) => (v ?? 0) / 100
  const has = (v: number | undefined): v is number => v != null

  switch (useCase) {
    case 'chat': {
      // chat = avg(mmlu, ifeval) — measures instruction following and broad knowledge
      const vals: number[] = []
      if (hasMmlu)   vals.push(n(scores.mmlu))
      if (hasIfeval)  vals.push(n(scores.ifeval))
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0.5
    }
    case 'code': {
      // code = humaneval (1.5x) + mmlu (0.5x), re-normalized
      const parts: [number, number][] = []
      if (hasHuman)  parts.push([n(scores.humaneval), 1.5])
      if (hasMmlu)   parts.push([n(scores.mmlu),      0.5])
      if (!parts.length) return 0.5
      const wsum = parts.reduce((a, [v, w]) => a + v * w, 0)
      const wden = parts.reduce((a, [, w]) => a + w, 0)
      return wsum / wden
    }
    case 'reasoning': {
      // reasoning = math + gpqa (1.5x) + mmlu (0.5x)
      const parts: [number, number][] = []
      if (hasMath)   parts.push([n(scores.math), 1.0])
      if (hasGpqa)   parts.push([n(scores.gpqa), 1.5])
      if (hasMmlu)   parts.push([n(scores.mmlu), 0.5])
      if (!parts.length) return 0.5
      const wsum = parts.reduce((a, [v, w]) => a + v * w, 0)
      const wden = parts.reduce((a, [, w]) => a + w, 0)
      return wsum / wden
    }
    case 'vision': {
      // No vision-specific benchmarks available; use MMLU as general intelligence proxy
      return hasMmlu ? n(scores.mmlu) : 0.5
    }
  }
}

// ── 3. Hardware utilization ───────────────────────────────────────────────────

/**
 * Score peaks when model fills 55–72% of total RAM.
 * A tiny model on a large machine is wasteful (low score).
 * A barely-fitting model risks OOM (low score).
 */
export function computeUtilizationScore(sizeGb: number | undefined, totalRamGb: number): number {
  if (!sizeGb || !totalRamGb || totalRamGb <= 0) return 0.50
  const r = sizeGb / totalRamGb
  if (r < 0.10) return 0.10
  if (r < 0.30) return 0.10 + (r - 0.10) / 0.20 * 0.30   // 0.10 → 0.40
  if (r < 0.55) return 0.40 + (r - 0.30) / 0.25 * 0.35   // 0.40 → 0.75
  if (r < 0.72) return 1.00                                 // optimal band
  if (r < 0.88) return 1.00 - (r - 0.72) / 0.16 * 0.30   // 1.00 → 0.70
  return 0.20
}

// ── 4. Recency decay ──────────────────────────────────────────────────────────

/**
 * Returns 0–1 based on age in months.
 * Hard zero applied only when maxAgeMonths > 0 and model exceeds it.
 * Unknown date → neutral 0.5.
 */
export function computeRecencyScore(lastModified: string | undefined, maxAgeMonths: number): number {
  if (!lastModified) return 0.5

  const ageMs = Date.now() - new Date(lastModified).getTime()
  if (isNaN(ageMs)) return 0.5
  const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44)

  // Hard cutoff
  if (maxAgeMonths > 0 && ageMonths > maxAgeMonths) return 0

  if (ageMonths <=  6) return 1.00
  if (ageMonths <= 12) return 0.90
  if (ageMonths <= 18) return 0.65
  if (ageMonths <= 24) return 0.40
  if (ageMonths <= 36) return 0.20
  return 0.05
}

// ── 5. Popularity damping ─────────────────────────────────────────────────────

export function computePopularityScore(downloads: number): number {
  return Math.max(0.15, Math.min(1.0, Math.log10(downloads + 10) / 6))
}

// ── Composite score ──────────────────────────────────────────────────────────

interface ScoringInput {
  id: string
  downloads: number
  tags: string[]
  last_modified?: string
  size_gb?: number
}

// Minimum affinity required to win a given use case.
// Vision requires explicit vision signal — a text model should never win "Best for Vision".
// Code and Reasoning have lower gates since instruct models have partial capability.
const MIN_AFFINITY: Record<UseCase, number> = {
  vision:    0.80,  // must match VISION_RE
  code:      0.40,  // must have at least some code signal
  reasoning: 0.35,  // must have at least some reasoning signal
  chat:      0.30,  // broad default — instruct models qualify easily
}

function scoreModel(
  model: ScoringInput,
  scores: BenchmarkScores,
  useCase: UseCase,
  totalRamGb: number,
  maxAgeMonths: number,
): number {
  const affinity = computeNameTagAffinity(model.id, model.tags)
  if (affinity.disqualified) return 0

  const af = affinity[useCase]

  // Gate: model must have meaningful affinity for this use case
  if (af < MIN_AFFINITY[useCase]) return 0

  // Gate: do not recommend models that cannot fit in hardware RAM
  if (model.size_gb && totalRamGb > 0 && model.size_gb / totalRamGb >= 0.92) return 0

  const bq = computeBenchmarkQuality(scores, useCase)
  const rc = computeRecencyScore(model.last_modified, maxAgeMonths)
  const ut = computeUtilizationScore(model.size_gb, totalRamGb)
  const pp = computePopularityScore(model.downloads)

  // Hard zero from recency cutoff
  if (rc === 0) return 0

  return af * 0.35 + bq * 0.30 + rc * 0.25 + ut * 0.10 + pp * 0.10 - 0.10
}

// ── Badge reason string ───────────────────────────────────────────────────────

function reasonString(
  model: ScoringInput,
  scores: BenchmarkScores,
  useCase: UseCase,
  totalRamGb: number,
): string {
  const parts: string[] = []

  // RAM utilization
  if (model.size_gb && totalRamGb > 0) {
    const pct = Math.round((model.size_gb / totalRamGb) * 100)
    parts.push(`${model.size_gb.toFixed(1)} GB · ${pct}% of your ${totalRamGb} GB`)
  }

  // Benchmark score
  if (scores.source !== 'none') {
    const bq = computeBenchmarkQuality(scores, useCase)
    const prefix = scores.source === 'fallback' ? '~' : ''
    parts.push(`${prefix}${Math.round(bq * 100)}% quality score`)
  }

  // Age
  if (model.last_modified) {
    const ageMs = Date.now() - new Date(model.last_modified).getTime()
    const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44)
    if (!isNaN(ageMonths)) {
      if (ageMonths < 1)       parts.push('< 1mo ago')
      else if (ageMonths < 12) parts.push(`${Math.round(ageMonths)}mo ago`)
      else                     parts.push(`${(ageMonths / 12).toFixed(1)}yr ago`)
    }
  }

  return parts.join(' · ')
}

// ── Main entry point ──────────────────────────────────────────────────────────

const BADGE_THRESHOLD = 0.35

/**
 * Evaluate all models and return a Map of model ID → badges.
 *
 * Each use case has exactly one winner (the highest-scoring eligible model).
 * A single model can win multiple categories.
 *
 * @param models       List of HF search results
 * @param scoresMap    Benchmark scores keyed by model HF ID
 * @param totalRamGb   Total unified memory (hardware spec)
 * @param maxAgeMonths Hard age cutoff (0 = no cutoff)
 * @param filterUseCase When set, only compute badges for that use case
 */
export function findBestChoices(
  models: ScoringInput[],
  scoresMap: Record<string, BenchmarkScores>,
  totalRamGb: number,
  maxAgeMonths: number,
  filterUseCase: UseCase | null,
): Map<string, ModelBadge[]> {
  const useCases: UseCase[] = filterUseCase
    ? [filterUseCase]
    : (['chat', 'code', 'reasoning', 'vision'] as UseCase[])

  const badgeMap = new Map<string, ModelBadge[]>()

  for (const useCase of useCases) {
    let bestScore = BADGE_THRESHOLD
    let bestModel: ScoringInput | null = null

    for (const model of models) {
      const scores = scoresMap[model.id] ?? { source: 'none' as const }
      const s = scoreModel(model, scores, useCase, totalRamGb, maxAgeMonths)
      if (s > bestScore) {
        bestScore = s
        bestModel = model
      }
    }

    if (!bestModel) continue

    const cfg = BADGE_CONFIG[useCase]
    const scores = scoresMap[bestModel.id] ?? { source: 'none' as const }
    const badge: ModelBadge = {
      useCase,
      label: `${cfg.icon} ${cfg.label}`,
      reason: reasonString(bestModel, scores, useCase, totalRamGb),
      score: bestScore,
      color: cfg.color,
    }

    const existing = badgeMap.get(bestModel.id) ?? []
    badgeMap.set(bestModel.id, [...existing, badge])
  }

  return badgeMap
}
