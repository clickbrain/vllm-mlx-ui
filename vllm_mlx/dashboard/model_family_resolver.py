# SPDX-License-Identifier: Apache-2.0
"""
Model Family Resolver — map any HF model ID to its canonical model family.

Resolution pipeline (tiered):
  Tier 1 (exact):  The model ID has its own entry in the curated table
                   OR has a direct leaderboard score match.
  Tier 2 (family): The model is derived from a curated family (fine-tune,
                   quant, re-upload). Inherits family release date + scores.
  Tier 3 (arch):   No family found. Guesses from architecture type + param
                   count. Uses own createdAt for recency, neutral 0.5 for
                   benchmarks.

Usage:
    resolver = ModelFamilyResolver()
    result = resolver.resolve("Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit")
    # {
    #   "family_key": "qwen-coder-2.5-32b",
    #   "family_name": "Qwen2.5-Coder 32B",
    #   "release_date": "2024-09-19",
    #   "arch_type": "qwen2",
    #   "param_count_b": 32,
    #   "tier": 2,
    #   "scores": {"mmlu": 82, "humaneval": 90.2, ...},
    #   "confidence": "inherited from Qwen2.5-Coder 32B family"
    # }
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
_FAMILIES_FILE = _DATA_DIR / "model_families.json"


# Suffixes to strip when normalizing a model ID (longest first so partial
# matches don't short-circuit longer suffixes).
_STRIP_SUFFIXES = [
    r"-mlx",
    r"-gguf",
    r"-safetensors",
    r"-hf",
    r"-converted",
    r"-converted-gguf",
    r"-converted-mlx",
]
_STRIP_QUANT = r"-(?:4bit|8bit|6bit|3bit|2bit|fp16|bf16|fp32|int4|int8|q4_k_m|q8_0|q4_0|q5_k_m|q6_k|dwq|awq)(?:-[a-z0-9_]+)*$"
_STRIP_VARIANT = r"-(?:instruct|chat|base|it|preview|latest|turbo|demo|alpha|beta)$"


def _load_families() -> dict[str, dict[str, Any]]:
    """Load the curated family table from disk.

    Returns a dict of family_key -> entry. Each entry is augmented at load
    time with a set of *normalized* alias strings for fast matching.
    """
    if not _FAMILIES_FILE.is_file():
        logger.warning("Model families file not found: %s", _FAMILIES_FILE)
        return {}
    try:
        with open(_FAMILIES_FILE, encoding="utf-8") as f:
            raw: dict[str, dict[str, Any]] = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load model families: %s", exc, exc_info=True)
        return {}

    # Augment each entry with a normalized alias set for matching
    for key, entry in raw.items():
        aliases = entry.get("aliases", [])
        entry["_norm_aliases"] = {
            _normalize_model_name(a) for a in aliases if a
        }
        # Add the family key itself as an alias
        entry["_norm_aliases"].add(key)
        # Also normalize any aliases that include an org prefix
        entry["_norm_aliases"].add(_normalize_model_name(key))

    logger.debug("Loaded %d model families", len(raw))
    return raw


def _normalize_model_name(model_id: str) -> str:
    """Reduce a model ID to a canonical lookup key.

    Strips org prefix, quant tags, variant tags, and known suffixes.
    Designed to make e.g.:
      "Outlier-Ai/Qwen2.5-Coder-32B-Instruct-MLX-4bit"
      → "qwen2.5-coder-32b"
    """
    name = model_id.lower().strip()

    # Strip org prefix (everything before /)
    if "/" in name:
        name = name.split("/", 1)[1]

    # Strip quantization bits FIRST (they're at the very end)
    name = re.sub(_STRIP_QUANT, "", name)

    # Strip known format/engine suffixes
    for suffix in _STRIP_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]

    # Strip variant suffixes
    name = re.sub(_STRIP_VARIANT, "", name)

    return name.strip("-")


def _mk_tier_3(
    model_id: str, hf_config: dict[str, Any] | None
) -> dict[str, Any]:
    """Build a Tier-3 family result — heuristic fallback when no curated entry
    or base_model relationship exists."""
    arch_type = "unknown"
    param_count_b: float = 0.0
    if hf_config:
        arch_type = hf_config.get("model_type", "") or arch_type
        hf_archs = hf_config.get("architectures", [])
        if hf_archs:
            import re as _re2
            m = _re2.search(r"(\d+)[bB]", "".join(hf_archs))
            if m:
                param_count_b = float(m.group(1))

    return {
        "family_key": _normalize_model_name(model_id),
        "family_name": "",
        "release_date": "",
        "arch_type": arch_type,
        "param_count_b": param_count_b,
        "tier": 3,
        "scores": {"mmlu": None, "humaneval": None, "math": None, "gpqa": None, "ifeval": None},
        "confidence": "architecture-only — no benchmark data available",
    }


class ModelFamilyResolver:
    """Resolve HF model IDs to canonical model families."""

    def __init__(self) -> None:
        self._families: dict[str, dict[str, Any]] = _load_families()
        # Index: normalized alias → family key
        self._alias_index: dict[str, str] = {}
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._alias_index = {}
        for key, entry in self._families.items():
            for alias in entry.get("_norm_aliases", set()):
                self._alias_index[alias] = key

    def resolve(
        self,
        model_id: str,
        hf_base_model: str | None = None,
        hf_tags: list[str] | None = None,
        hf_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve a model ID to its canonical family.

        Tries:
          1. Direct alias match in curated table (Tier 1 or 2 depending on
             whether the exact model ID matches).
          2. Follow *base_model* tag chain (Tier 2 derivative).
          3. Guess from architecture config (Tier 3 fallback).

        Args:
            model_id: Full HF model ID (e.g. ``mlx-community/Qwen3-8B-4bit``).
            hf_base_model: The ``cardData.base_model`` field, if available.
            hf_tags: The HuggingFace tags list (contains ``base_model:``
                     entries).
            hf_config: The HuggingFace model ``config`` dict (contains
                       ``model_type``, ``architectures``).

        Returns:
            dict with family_key, release_date, arch_type, param_count_b,
            tier, scores, confidence.
        """
        normalized = _normalize_model_name(model_id)

        # ── Tier 1/2: Check curated table directly ──────────────────────
        direct_match = self._alias_index.get(normalized)
        if direct_match:
            return self._entry_to_result(
                direct_match, model_id, tier=1,
                confidence="exact family match",
            )

        # ── Tier 2: Follow base_model tag chain ─────────────────────────
        base_model_id = hf_base_model
        # cardData.base_model can be a list (e.g. ['Qwen/Qwen2.5-7B']) — take first
        if isinstance(base_model_id, list):
            base_model_id = base_model_id[0] if base_model_id else None
        # Also check tags for base_model:* entries
        if not base_model_id and hf_tags:
            for tag in hf_tags:
                if tag.startswith("base_model:"):
                    # Handle tags like "base_model:Qwen/Qwen2.5-Coder-32B"
                    # or "base_model:finetune:Qwen/Qwen2.5-Coder-32B"
                    parts = tag.split(":", 2)
                    if len(parts) == 3 and parts[1] in ("finetune", "quantized"):
                        base_model_id = parts[2]
                    elif len(parts) == 2:
                        base_model_id = parts[1]
                    break

        if base_model_id:
            base_normalized = _normalize_model_name(base_model_id)
            base_match = self._alias_index.get(base_normalized)
            if base_match:
                return self._entry_to_result(
                    base_match, model_id, tier=2,
                    confidence=f"inherited from {self._families[base_match].get('family_name', base_match)}",
                )

        # ── Tier 2.5: Family-key prefix heuristic ─────────────────────────
        # After base_model chain fails, check if the normalized name shares
        # a significant prefix with any known family key. This catches
        # unlisted variants like Qwen3-Coder-Next → qwen3-coder-*.
        prefix_match = self._best_prefix_match(normalized)
        if prefix_match:
            return self._entry_to_result(
                prefix_match, model_id, tier=2,
                confidence=f"family prefix heuristic — matched {prefix_match}",
            )

        # ── Tier 3: Architecture fallback ───────────────────────────────
        return _mk_tier_3(model_id, hf_config)

    def resolve_batch(
        self,
        models: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Resolve a list of HF search result dicts in batch.

        Each input dict should have ``id``, and optionally ``tags``,
        ``cardData.base_model``, and ``config`` fields.

        Returns a dict mapping model ID → family result.
        """
        results: dict[str, dict[str, Any]] = {}
        for model in models:
            mid = model.get("id", "")
            if not mid:
                continue
            card_data = model.get("cardData") or {}
            tags = model.get("tags") or []
            config = model.get("config")
            results[mid] = self.resolve(
                model_id=mid,
                hf_base_model=card_data.get("base_model"),
                hf_tags=tags,
                hf_config=config,
            )
        return results

    def _best_prefix_match(self, normalized: str) -> str | None:
        """Find the family key with the longest common prefix to *normalized*.

        Returns the best-matching family key if the LCP covers >= 60% of
        the shorter string, indicating a family relationship.
        """
        best_lcp = 0
        best_key: str | None = None
        for key in self._families:
            i = 0
            while i < len(key) and i < len(normalized) and key[i] == normalized[i]:
                i += 1
            if i > best_lcp:
                best_lcp = i
                best_key = key
        if best_key and best_lcp > 0:
            shorter = min(len(best_key), len(normalized))
            if best_lcp / shorter >= 0.60:
                return best_key
        return None

    def _entry_to_result(
        self,
        family_key: str,
        original_id: str,
        tier: int,
        confidence: str,
    ) -> dict[str, Any]:
        entry = self._families[family_key]
        return {
            "family_key": family_key,
            "family_name": entry.get("family_name", ""),
            "release_date": entry.get("release_date", ""),
            "arch_type": entry.get("arch_type", ""),
            "param_count_b": entry.get("param_count_b", 0),
            "tier": tier,
            "scores": dict(entry.get("scores", {})),
            "confidence": confidence,
        }

    def reload(self) -> None:
        """Reload the curated table from disk. Called when the table is
        updated at runtime."""
        self._families = _load_families()
        self._rebuild_index()
