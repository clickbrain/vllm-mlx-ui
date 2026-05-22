# Best Choice Scoring — How It Works

The **Best Choice** system in the Model Finder evaluates every model in the current search results and awards a badge to the single highest-scoring eligible model in each use-case category: Chat, Code, Reasoning, and Vision.

A model must score above **0.35** to win. If no model clears the threshold, no badge is shown for that category.

---

## The Formula

```
score = (affinity × 0.35) + (benchmark × 0.30) + (recency × 0.25)
      + (utilization × 0.10) + (popularity × 0.10) − 0.10
```

All five signals are independently computed then combined. A single model can win multiple categories.

---

## Signal 1 — Name/Tag Affinity (35%)

Regex matching against the model ID and HuggingFace tags. Determines whether the model was designed for the target use case.

| Signal | Matched patterns |
|--------|-----------------|
| Vision | `vlm`, `-vl-`, `pixtral`, `llava`, `internvl`, `qwen.*vl`, `phi.*vis`, `moondream`, `paligemma` |
| Code | `coder`, `coding`, `-code`, `starcoder`, `codestral`, `deepseek-coder`, `qwen.*coder` |
| Reasoning | `thinking`, `r1`, `qwq`, `deepseek-r1`, `reasoning`, `skywork-o`, `phi.*reasoning` |
| Instruct/Chat | `instruct`, `chat`, `-it`, `assistant`, `-chat` |

**Disqualification:** Embedding and reranking models (`embed`, `bge-`, `e5-`, `nomic-embed`) are always excluded.

**Minimum thresholds:** A model must reach a minimum affinity to even compete in a category — Vision requires 0.80 (must explicitly be a vision model), Code requires 0.40, Reasoning 0.35, Chat 0.30. Models below the threshold score 0.

A plain instruct model without a code-specific name gets a chat affinity of 0.90 but a code affinity of only 0.45. It can still win Best for Code if no code-specialist is in the result set and it clears the 0.40 gate.

---

## Signal 2 — Benchmark Quality (30%)

Each use case uses a different blend of empirical benchmark scores:

| Use Case | Formula |
|----------|---------|
| **Chat** | avg(MMLU, IFEval) |
| **Code** | HumanEval × 1.5 + MMLU × 0.5, normalized |
| **Reasoning** | MATH × 1.0 + GPQA × 1.5 + MMLU × 0.5, normalized |
| **Vision** | MMLU proxy (no vision-specific benchmark cached) |

Benchmark data comes from a built-in database covering ~80 model families (Qwen3, Llama 3.x, Gemma 3, Mistral, DeepSeek R1/V3, Phi-4, and more). Background enrichment from the HuggingFace Open LLM Leaderboard runs 20 seconds after startup and refreshes every 24 hours.

**When no data exists:** the signal returns a neutral **0.5** — it doesn't hurt or help. A model with no benchmarks can still win if the other signals are strong.

---

## Signal 3 — Recency (25%)

Uses the model's **publish date** (`createdAt` from HuggingFace) — not the last-modified date, which changes whenever someone updates the README or patches a safety file.

| Age | Score |
|-----|-------|
| ≤ 6 months | 1.00 |
| 6–12 months | 0.90 |
| 12–18 months | 0.65 |
| 18–24 months | 0.40 |
| 24–36 months | 0.20 |
| > 36 months | 0.05 |
| > Max Age setting | **0** (hard excluded) |

The **Max Age** dropdown in the use-case bar (default: 18 months) applies a hard cutoff. Models older than this score zero and cannot win any badge. Set it to "No limit" to include all ages.

---

## Signal 4 — Hardware Utilization (10%)

Rewards models that make good use of your available memory — neither too small (wasted capability) nor too large (OOM risk).

| RAM fill | Score |
|---------|-------|
| < 10% | 0.10 (underutilizing) |
| 10–55% | 0.10 → 0.75 (linear ramp) |
| 55–72% | **1.00** (optimal band) |
| 72–88% | 1.00 → 0.70 (linear decline) |
| ≥ 88% | 0.20 (OOM risk) |
| ≥ 92% | **0** (hard excluded) |

A 7B model on a 192 GB M2 Ultra (~3.6% fill) scores 0.10 here even if it's excellent in every other way — the machine is dramatically underutilized. A 70B model at ~36 GB on 64 GB total (~56% fill) sits squarely in the optimal band.

---

## Signal 5 — Popularity (10%)

Log-scaled download count, floored at 0.15 so unknown or niche models are not zeroed out.

```
popularity = max(0.15, min(1.0, log₁₀(downloads + 10) / 6))
```

This signal is intentionally low-weighted (10%) to avoid older models winning simply because they've had more time to accumulate downloads.

---

## Hard Exclusions

A model is excluded from all badges (score = 0) if:

- It is an embedding or reranking model
- Its size exceeds 92% of your total RAM
- Its publish date exceeds the Max Age cutoff you've set
- It does not meet the minimum affinity threshold for the category

---

## Badge Reason String

Each badge shows a one-line reason beneath the label:

```
40.0 GB · 62% of your 64 GB · ~87% quality score · 4mo old
```

This gives you exactly why a model won so you can judge whether the reasoning makes sense for your situation.

---

## The "Best For" Sections

Winners are surfaced in a highlighted section **above** regular search results, deduplicated from the list below. Up to four winners can appear — one per category. A single model can hold multiple badges if it genuinely scores best across several use cases.

The category you're currently filtered on (via the use-case pill bar) determines which badges are computed. Click a pill to focus on one category; click again to deselect and see all four.
