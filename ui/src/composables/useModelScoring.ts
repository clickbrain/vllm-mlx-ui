import type { BenchmarkScores, FamilyData } from '@/stores/models'

export type UseCase = 'chat' | 'code' | 'reasoning' | 'vision'

export interface ModelBadge {
  useCase: UseCase
  label: string       // e.g. "Best for Chat"
  reason: string      // e.g. "40 GB fits your 64 GB well · MMLU ~87%"
  score: number       // 0–1, useful for debugging
  color: string       // CSS custom property reference, e.g. "var(--badge-chat)"
}

const BADGE_CONFIG: Record<UseCase, { label: string; color: string; icon: string }> = {
  chat:      { label: 'Best for Chat',      color: 'var(--badge-chat)',      icon: '💬' },
  code:      { label: 'Best for Code',      color: 'var(--badge-code)',      icon: '💻' },
  reasoning: { label: 'Best for Reasoning', color: 'var(--badge-reasoning)', icon: '🧠' },
  vision:    { label: 'Best for Vision',    color: 'var(--badge-vision)',    icon: '🖼️' },
}

interface AffinityVector {
  chat: number
  code: number
  reasoning: number
  vision: number
  disqualified: boolean
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
    return { chat: 0.5, code: 0, reasoning: 0, vision: 1.0, disqualified: false }
  }

  const isInstruct = INSTRUCT_RE.test(combined)
  const isCode     = CODE_RE.test(combined)
  const isReasoning = REASONING_RE.test(combined)

  let chat = isInstruct ? 0.90 : 0.40
  let code = isCode ? 0.95 : (isInstruct ? 0.45 : 0.20)
  let reasoning = isReasoning ? 0.95 : (isInstruct ? 0.40 : 0.15)

  if (isCode && !isReasoning)      { chat = Math.min(chat, 0.60); reasoning = 0.30 }
  if (isReasoning && !isCode)      { chat = chat * 0.75 }
  if (isCode && isReasoning)       { chat = chat * 0.65 }

  return { chat, code, reasoning, vision: 0.10, disqualified: false }
}

export function computeBenchmarkQuality(scores: BenchmarkScores, useCase: UseCase): number {
  if (scores.source === 'none') return 0.5

  const hasMmlu      = scores.mmlu      != null
  const hasHuman     = scores.humaneval != null
  const hasMath      = scores.math      != null
  const hasGpqa      = scores.gpqa      != null
  const hasIfeval    = scores.ifeval    != null

  const n  = (v: number | undefined) => (v ?? 0) / 100
  const has = (v: number | undefined): v is number => v != null

  switch (useCase) {
    case 'chat': {
      const vals: number[] = []
      if (hasMmlu)   vals.push(n(scores.mmlu))
      if (hasIfeval)  vals.push(n(scores.ifeval))
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0.5
    }
    case 'code': {
      const parts: [number, number][] = []
      if (hasHuman)  parts.push([n(scores.humaneval), 1.5])
      if (hasMmlu)   parts.push([n(scores.mmlu),      0.5])
      if (!parts.length) return 0.5
      const wsum = parts.reduce((a, [v, w]) => a + v * w, 0)
      const wden = parts.reduce((a, [, w]) => a + w, 0)
      return wsum / wden
    }
    case 'reasoning': {
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
      return hasMmlu ? n(scores.mmlu) : 0.5
    }
  }
}

export function computeUtilizationScore(sizeGb: number | undefined, totalRamGb: number): number {
  if (!sizeGb || !totalRamGb || totalRamGb <= 0) return 0.50
  const r = sizeGb / totalRamGb
  if (r < 0.10) return 0.10
  if (r < 0.30) return 0.10 + (r - 0.10) / 0.20 * 0.30
  if (r < 0.55) return 0.40 + (r - 0.30) / 0.25 * 0.35
  if (r < 0.72) return 1.00
  if (r < 0.88) return 1.00 - (r - 0.72) / 0.16 * 0.30
  return 0.20
}

export function computeRecencyScore(lastModified: string | undefined, maxAgeMonths: number): number {
  if (!lastModified) return 0.5

  const ageMs = Date.now() - new Date(lastModified).getTime()
  if (isNaN(ageMs)) return 0.5
  const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44)

  if (maxAgeMonths > 0 && ageMonths > maxAgeMonths) return 0

  if (ageMonths <=  6) return 1.00
  if (ageMonths <= 12) return 0.90
  if (ageMonths <= 18) return 0.65
  if (ageMonths <= 24) return 0.40
  if (ageMonths <= 36) return 0.20
  return 0.05
}

interface ScoringInput {
  id: string
  downloads: number
  tags: string[]
  last_modified?: string
  created_at?: string
  size_gb?: number
  family_data?: FamilyData | null
}

const MIN_AFFINITY: Record<UseCase, number> = {
  vision:    0.80,
  code:      0.40,
  reasoning: 0.35,
  chat:      0.30,
}

function effectiveDate(model: ScoringInput): string | undefined {
  if (model.family_data?.release_date) {
    return model.family_data.release_date
  }
  return model.created_at || model.last_modified
}

function mergeBenchmarkScores(
  familyData: FamilyData | undefined | null,
  scores: BenchmarkScores,
): BenchmarkScores {
  if (!familyData?.scores) return scores

  const fs = familyData.scores
  const merged: BenchmarkScores = {
    mmlu:      fs.mmlu      ?? scores.mmlu,
    humaneval: fs.humaneval ?? scores.humaneval,
    math:      fs.math      ?? scores.math,
    gpqa:      fs.gpqa      ?? scores.gpqa,
    ifeval:    fs.ifeval    ?? scores.ifeval,
    source:    (fs.mmlu != null || fs.humaneval != null) ? 'fallback' : scores.source,
  }

  const hasAny = merged.mmlu != null || merged.humaneval != null || merged.math != null
    || merged.gpqa != null || merged.ifeval != null
  if (!hasAny) merged.source = 'none'

  return merged
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
  if (af < MIN_AFFINITY[useCase]) return 0

  if (model.size_gb && totalRamGb > 0 && model.size_gb / totalRamGb >= 0.92) return 0

  const merged = mergeBenchmarkScores(model.family_data, scores)
  const bq = computeBenchmarkQuality(merged, useCase)
  const dateForRecency = effectiveDate(model)
  const rc = computeRecencyScore(dateForRecency, maxAgeMonths)
  const ut = computeUtilizationScore(model.size_gb, totalRamGb)

  if (rc === 0) return 0

  return af * 0.35 + bq * 0.35 + ut * 0.10 + rc * 0.20
}

function reasonString(
  model: ScoringInput,
  scores: BenchmarkScores,
  useCase: UseCase,
  totalRamGb: number,
): string {
  const parts: string[] = []

  if (model.size_gb && totalRamGb > 0) {
    const pct = Math.round((model.size_gb / totalRamGb) * 100)
    parts.push(`${model.size_gb.toFixed(1)} GB · ${pct}% of your ${totalRamGb} GB`)
  }

  const merged = mergeBenchmarkScores(model.family_data, scores)
  if (merged.source !== 'none') {
    const bq = computeBenchmarkQuality(merged, useCase)
    const prefix = merged.source === 'fallback' ? '~' : ''
    parts.push(`${prefix}${Math.round(bq * 100)}% quality score`)
  }

  const dateForAge = effectiveDate(model)
  if (dateForAge) {
    const ageMs = Date.now() - new Date(dateForAge).getTime()
    const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44)
    if (!isNaN(ageMonths)) {
      if (ageMonths < 1)       parts.push('< 1mo old')
      else if (ageMonths < 12) parts.push(`${Math.round(ageMonths)}mo old`)
      else                     parts.push(`${(ageMonths / 12).toFixed(1)}yr old`)
    }
  }

  return parts.join(' · ')
}

const BADGE_THRESHOLD = 0.35

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
