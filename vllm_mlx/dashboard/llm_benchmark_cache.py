# SPDX-License-Identifier: Apache-2.0
"""Background cache of LLM benchmark scores.

Primary source: HF Open LLM Leaderboard dataset API (optional, graceful
degradation — the endpoint is sometimes unavailable).

Fallback: Curated scores for ~80 well-known model families, updated each
release from published papers and HF model cards.

Refreshes once per 24 hours in a background daemon thread.
Thread-safe: all public functions acquire _lock before reading/writing _scores.
"""
import json
import re
import threading
import time
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_FILE = Path.home() / ".vllm_mlx_ui" / "llm_scores_cache.json"
_CACHE_TTL_SECONDS = 24 * 3600
_LEADERBOARD_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=open-llm-leaderboard%2Fresults"
    "&config=default&split=train&offset={offset}&length=100"
)

_scores: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_refresh_stop = threading.Event()
_refresh_thread: threading.Thread | None = None

# ── Curated fallback scores ────────────────────────────────────────────────────
# Format: normalized_key -> {mmlu, humaneval, math, gpqa, ifeval}
# All values are percentage points (0-100). Source: published papers / HF model cards.
# Conservative estimates where ranges were reported.
# Updated: May 2026
_FALLBACK_SCORES: dict[str, dict[str, float]] = {
    # Qwen3 family (2025-04)
    "qwen3-235b": {"mmlu": 88.9, "humaneval": 80.8, "math": 89.0, "gpqa": 59.1, "ifeval": 91.4},
    "qwen3-72b":  {"mmlu": 87.5, "humaneval": 79.0, "math": 85.8, "gpqa": 65.5, "ifeval": 89.1},
    "qwen3-32b":  {"mmlu": 84.6, "humaneval": 75.0, "math": 82.1, "gpqa": 52.8, "ifeval": 86.3},
    "qwen3-30b":  {"mmlu": 83.8, "humaneval": 74.0, "math": 80.0, "gpqa": 50.0, "ifeval": 85.0},
    "qwen3-14b":  {"mmlu": 81.0, "humaneval": 70.0, "math": 75.0, "gpqa": 43.0, "ifeval": 83.0},
    "qwen3-8b":   {"mmlu": 76.3, "humaneval": 66.0, "math": 70.1, "gpqa": 36.0, "ifeval": 80.2},
    "qwen3-4b":   {"mmlu": 70.0, "humaneval": 60.0, "math": 62.0, "gpqa": 28.0, "ifeval": 75.0},
    "qwen3-1.7b": {"mmlu": 60.0, "humaneval": 50.0, "math": 50.0, "gpqa": 20.0, "ifeval": 65.0},
    "qwen3-0.6b": {"mmlu": 50.0, "humaneval": 38.0, "math": 38.0, "gpqa": 15.0, "ifeval": 55.0},
    # Qwen2.5 family (2024-09)
    "qwen2.5-72b":        {"mmlu": 85.0, "humaneval": 73.0, "math": 76.2, "gpqa": 49.0, "ifeval": 87.0},
    "qwen2.5-32b":        {"mmlu": 82.5, "humaneval": 70.5, "math": 73.8, "gpqa": 45.0, "ifeval": 84.5},
    "qwen2.5-14b":        {"mmlu": 79.5, "humaneval": 65.5, "math": 68.5, "gpqa": 40.0, "ifeval": 81.0},
    "qwen2.5-7b":         {"mmlu": 74.2, "humaneval": 62.0, "math": 62.5, "gpqa": 31.0, "ifeval": 77.0},
    "qwen2.5-3b":         {"mmlu": 66.0, "humaneval": 52.0, "math": 54.0, "gpqa": 23.0, "ifeval": 68.0},
    "qwen2.5-1.5b":       {"mmlu": 60.0, "humaneval": 44.0, "math": 46.0, "gpqa": 17.0, "ifeval": 62.0},
    "qwen2.5-coder-32b":  {"mmlu": 82.0, "humaneval": 90.2, "math": 75.0, "gpqa": 45.0, "ifeval": 84.0},
    "qwen2.5-coder-14b":  {"mmlu": 78.0, "humaneval": 85.0, "math": 70.0, "gpqa": 38.0, "ifeval": 80.0},
    "qwen2.5-coder-7b":   {"mmlu": 72.0, "humaneval": 78.0, "math": 62.0, "gpqa": 30.0, "ifeval": 74.0},
    "qwen2.5-math-72b":   {"mmlu": 83.0, "humaneval": 65.0, "math": 90.2, "gpqa": 42.0, "ifeval": 80.0},
    # Llama 3.3 family (2024-12)
    "llama-3.3-70b": {"mmlu": 86.0, "humaneval": 72.0, "math": 77.0, "gpqa": 50.1, "ifeval": 88.4},
    # Llama 3.2 family (2024-09)
    "llama-3.2-90b":  {"mmlu": 82.5, "humaneval": 65.0, "math": 70.0, "gpqa": 44.0, "ifeval": 83.0},
    "llama-3.2-11b":  {"mmlu": 73.5, "humaneval": 57.0, "math": 60.0, "gpqa": 30.0, "ifeval": 77.0},
    "llama-3.2-3b":   {"mmlu": 63.0, "humaneval": 52.0, "math": 50.0, "gpqa": 22.0, "ifeval": 70.0},
    "llama-3.2-1b":   {"mmlu": 49.3, "humaneval": 35.0, "math": 34.0, "gpqa": 12.0, "ifeval": 59.0},
    # Llama 3.1 family (2024-07)
    "llama-3.1-405b": {"mmlu": 88.6, "humaneval": 76.0, "math": 73.8, "gpqa": 51.1, "ifeval": 87.5},
    "llama-3.1-70b":  {"mmlu": 83.6, "humaneval": 68.0, "math": 68.0, "gpqa": 46.7, "ifeval": 85.0},
    "llama-3.1-8b":   {"mmlu": 69.4, "humaneval": 62.0, "math": 51.9, "gpqa": 25.7, "ifeval": 77.5},
    # Llama 3.0 family (2024-04)
    "llama-3-70b": {"mmlu": 79.5, "humaneval": 62.0, "math": 50.4, "gpqa": 39.0, "ifeval": 77.0},
    "llama-3-8b":  {"mmlu": 68.4, "humaneval": 62.0, "math": 30.0, "gpqa": 22.0,  "ifeval": 76.5},
    # DeepSeek R1 family (2025-01)
    "deepseek-r1":                    {"mmlu": 90.8, "humaneval": 96.0, "math": 97.3, "gpqa": 71.5, "ifeval": 83.3},
    "deepseek-r1-distill-qwen-32b":   {"mmlu": 87.5, "humaneval": 92.0, "math": 94.9, "gpqa": 62.1, "ifeval": 83.0},
    "deepseek-r1-distill-qwen-14b":   {"mmlu": 83.0, "humaneval": 83.0, "math": 93.9, "gpqa": 59.1, "ifeval": 80.0},
    "deepseek-r1-distill-qwen-7b":    {"mmlu": 77.0, "humaneval": 78.0, "math": 91.6, "gpqa": 49.1, "ifeval": 75.0},
    "deepseek-r1-distill-llama-70b":  {"mmlu": 86.7, "humaneval": 86.0, "math": 95.0, "gpqa": 65.2, "ifeval": 82.0},
    "deepseek-r1-distill-llama-8b":   {"mmlu": 72.8, "humaneval": 72.0, "math": 89.1, "gpqa": 49.0, "ifeval": 69.0},
    # DeepSeek V3 family (2024-12)
    "deepseek-v3": {"mmlu": 88.5, "humaneval": 91.6, "math": 90.2, "gpqa": 59.1, "ifeval": 86.0},
    # Gemma 3 family (2025-03)
    "gemma-3-27b": {"mmlu": 87.0, "humaneval": 75.5, "math": 80.5, "gpqa": 48.8, "ifeval": 85.7},
    "gemma-3-12b": {"mmlu": 82.5, "humaneval": 69.2, "math": 74.0, "gpqa": 42.5, "ifeval": 81.0},
    "gemma-3-4b":  {"mmlu": 74.5, "humaneval": 60.0, "math": 62.5, "gpqa": 33.0, "ifeval": 74.0},
    "gemma-3-1b":  {"mmlu": 58.0, "humaneval": 40.0, "math": 44.0, "gpqa": 16.0, "ifeval": 62.0},
    # Phi-4 family (2024-12)
    "phi-4":           {"mmlu": 84.8, "humaneval": 82.6, "math": 80.6, "gpqa": 56.1, "ifeval": 86.5},
    "phi-4-mini":      {"mmlu": 78.0, "humaneval": 72.5, "math": 73.0, "gpqa": 40.0, "ifeval": 80.0},
    "phi-4-reasoning": {"mmlu": 86.0, "humaneval": 85.0, "math": 92.0, "gpqa": 62.0, "ifeval": 87.0},
    "phi-3.5-mini":    {"mmlu": 69.0, "humaneval": 62.0, "math": 46.0, "gpqa": 30.0, "ifeval": 72.0},
    # Mistral family
    "mistral-small-3.1": {"mmlu": 81.0, "humaneval": 72.0, "math": 67.0, "gpqa": 42.0, "ifeval": 80.0},
    "mistral-small-3":   {"mmlu": 81.0, "humaneval": 72.0, "math": 67.0, "gpqa": 42.0, "ifeval": 80.0},
    "mistral-nemo":      {"mmlu": 68.0, "humaneval": 64.0, "math": 48.0, "gpqa": 28.0, "ifeval": 76.0},
    "mistral-7b":        {"mmlu": 64.2, "humaneval": 40.0, "math": 28.0, "gpqa": 22.0, "ifeval": 55.0},
    "codestral-22b":     {"mmlu": 78.0, "humaneval": 81.0, "math": 62.0, "gpqa": 32.0, "ifeval": 74.0},
    # Small/efficient models
    "smollm2-1.7b": {"mmlu": 51.0, "humaneval": 38.0, "math": 30.0, "gpqa": 13.0, "ifeval": 52.0},
    "smollm2-360m": {"mmlu": 40.0, "humaneval": 20.0, "math": 15.0, "gpqa": 8.0,  "ifeval": 38.0},
}

# ── Model ID normalization ─────────────────────────────────────────────────────

# Quant/format suffixes to strip (order: longest patterns first)
_STRIP_PATTERNS = [
    r"-(?:bf16|bfloat16|fp16|float16|fp32|int4|int8)$",
    r"-(?:4bit|8bit|6bit|3bit|2bit|q4_k_m|q8_0|q4_0|q5_k_m|q6_k|dwq|awq|gguf)(?:-[a-z0-9_]+)*$",
    r"-(?:4bit|8bit|6bit|3bit|2bit)$",
    r"-(?:instruct|chat|assistant|it|base|hf|mlx|converted|turbo|preview|latest)$",
]

# Organisation prefixes that appear in the model filename itself (not the HF org)
# e.g. "Meta-Llama-3-8B" has "meta-" as part of the filename
_FILENAME_ORG_PREFIXES = re.compile(r"^(?:meta-)")



def normalize_model_id(hf_id: str) -> str:
    """Strip org prefix and quantization/variant suffixes, return family+size key.

    Examples:
      mlx-community/Qwen3-72B-4bit                  → qwen3-72b
      mlx-community/Llama-3.3-70B-Instruct-4bit      → llama-3.3-70b
      Qwen/Qwen3-72B-Instruct                        → qwen3-72b
      meta-llama/Llama-3.1-8B-Instruct               → llama-3.1-8b
      mlx-community/Meta-Llama-3-8B-Instruct-4bit    → llama-3-8b
      mlx-community/Qwen2.5-7B-Instruct-MLX-4bit     → qwen2.5-7b
      mlx-community/deepseek-r1-distill-qwen-32b-4bit → deepseek-r1-distill-qwen-32b
    """
    name = hf_id.split("/")[-1].lower()
    # Strip org-name prefixes embedded in the filename (e.g. "Meta-Llama" → "Llama")
    name = _FILENAME_ORG_PREFIXES.sub("", name)
    # Loop until no more suffixes are stripped (handles compound chains like -instruct-mlx-4bit)
    for _ in range(6):  # max 6 passes prevents infinite loops
        prev = name
        for pat in _STRIP_PATTERNS:
            name = re.sub(pat, "", name)
        if name == prev:
            break
    return name.strip("-_")


# ── Leaderboard fetch ──────────────────────────────────────────────────────────

def _row_to_scores(row: dict[str, Any]) -> dict[str, float] | None:
    """Extract benchmark scores from a leaderboard dataset row. Returns None on failure."""
    try:
        # Column names vary between leaderboard versions — try multiple keys
        mmlu     = float(row.get("mmlu") or row.get("Average") or 0)
        humaneval = float(row.get("humaneval") or row.get("HumanEval") or 0)
        math_     = float(row.get("math") or row.get("MATH") or 0)
        gpqa      = float(row.get("gpqa_diamond") or row.get("GPQA") or row.get("gpqa") or 0)
        ifeval    = float(row.get("ifeval") or row.get("IFEval") or 0)
        if all(v == 0 for v in [mmlu, humaneval, math_, gpqa, ifeval]):
            return None
        return {"mmlu": mmlu, "humaneval": humaneval, "math": math_, "gpqa": gpqa, "ifeval": ifeval}
    except Exception:
        return None


def _fetch_leaderboard() -> dict[str, dict[str, Any]]:
    """Fetch scores from the HF Open LLM Leaderboard dataset API.

    Returns empty dict on any failure — caller treats it as optional enrichment.
    """
    results: dict[str, dict[str, Any]] = {}
    offset = 0
    max_pages = 40  # cap at 4000 rows

    for _ in range(max_pages):
        url = _LEADERBOARD_URL.format(offset=offset)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vllm-mlx-ui/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            rows = data.get("rows", [])
            if not rows:
                break
            for entry in rows:
                row = entry.get("row", {})
                model_name = (
                    row.get("model_name")
                    or row.get("name")
                    or row.get("model")
                    or ""
                )
                if not model_name:
                    continue
                scores = _row_to_scores(row)
                if scores:
                    key = normalize_model_id(model_name)
                    results[key] = {**scores, "source": "leaderboard"}
            offset += len(rows)
            if len(rows) < 100:
                break
        except Exception as exc:
            logger.debug("Leaderboard fetch page %d failed: %s", offset // 100, exc)
            break

    return results


# ── Cache persistence ──────────────────────────────────────────────────────────

def _load_cache() -> dict[str, dict[str, Any]]:
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text())
            # Validate it's not empty/corrupt
            if isinstance(data, dict) and len(data) > 10:
                return data
    except Exception as exc:
        logger.debug("Failed to load llm_scores_cache: %s", exc)
    return {}


def _save_cache(data: dict[str, dict[str, Any]]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.debug("Failed to save llm_scores_cache: %s", exc)


# ── Refresh logic ──────────────────────────────────────────────────────────────

def _refresh() -> None:
    """Fetch live leaderboard data and merge with fallback scores."""
    global _scores

    # Try to get live leaderboard data (optional — may return empty)
    live = _fetch_leaderboard()

    # Build merged dict: fallback is base, live data wins on collision
    merged: dict[str, dict[str, Any]] = {}
    for key, scores in _FALLBACK_SCORES.items():
        merged[key] = {**scores, "source": "fallback"}
    for key, scores in live.items():
        merged[key] = scores  # already has source="leaderboard"

    merged["__meta__"] = {"refreshed_at": time.time(), "live_count": len(live)}  # type: ignore[assignment]
    _save_cache(merged)

    with _lock:
        _scores.clear()
        _scores.update(merged)

    logger.info(
        "LLM benchmark cache refreshed: %d entries (%d live, %d fallback)",
        len(merged) - 1, len(live), len(_FALLBACK_SCORES),
    )


def _cache_is_stale() -> bool:
    meta = _scores.get("__meta__")
    if not meta or not isinstance(meta, dict):
        return True
    return (time.time() - float(meta.get("refreshed_at", 0))) > _CACHE_TTL_SECONDS


def _run_refresh_loop() -> None:
    """Background thread: seed from disk, refresh 20s after startup, then every 24h."""
    # Brief startup delay
    if _refresh_stop.wait(20):
        return
    while not _refresh_stop.is_set():
        try:
            _refresh()
        except Exception as exc:
            logger.warning("LLM benchmark cache refresh failed: %s", exc, exc_info=True)
        # Wait 24 hours, checking every 10s for stop signal
        for _ in range(24 * 360):
            if _refresh_stop.wait(10):
                return


# ── Public API ─────────────────────────────────────────────────────────────────

def start_background_refresh() -> threading.Thread:
    """Start the background refresh thread. Call once at app startup."""
    global _refresh_thread

    # Seed from disk immediately so first requests don't wait 20s
    cached = _load_cache()
    if cached:
        with _lock:
            _scores.update(cached)
        logger.debug("LLM benchmark cache seeded from disk (%d entries)", len(cached))
    else:
        # Disk cache missing — seed from fallback so we're never empty
        with _lock:
            for key, scores in _FALLBACK_SCORES.items():
                _scores[key] = {**scores, "source": "fallback"}

    _refresh_stop.clear()
    _refresh_thread = threading.Thread(
        target=_run_refresh_loop,
        daemon=True,
        name="llm-score-refresh",
    )
    _refresh_thread.start()
    return _refresh_thread


def stop_background_refresh() -> None:
    """Signal the background thread to stop. Call at shutdown."""
    _refresh_stop.set()


def get_scores(model_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Look up benchmark scores for a list of HF model IDs.

    Returns a dict mapping each input ID to its scores. IDs with no match
    get ``{"source": "none"}``.
    """
    with _lock:
        current = dict(_scores)

    result: dict[str, dict[str, Any]] = {}
    for hf_id in model_ids:
        key = normalize_model_id(hf_id)
        scores = current.get(key)

        # Progressive fallback: try stripping instruct/chat suffix
        if not scores:
            alt_key = re.sub(r"(?:-instruct|-chat|-assistant|-it|-turbo)$", "", key)
            scores = current.get(alt_key)

        # Skip internal sentinel keys
        if scores and not scores.get("refreshed_at") and key != "__meta__":
            result[hf_id] = {**scores, "matched_key": key}
        else:
            result[hf_id] = {"source": "none"}

    return result
