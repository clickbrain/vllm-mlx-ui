# SPDX-License-Identifier: Apache-2.0
"""
Model management for the vllm-mlx dashboard.

Provides HuggingFace Hub integration: search models in mlx-community,
list locally cached models, download, and delete.

When remote_mgmt_url is configured in server_manager, model operations
(cached list, download, delete) are routed to the remote machine via the
management API, so models are stored on the server, not on this machine.
"""

import contextlib
import logging
import os
import re
import threading
import time as _time
from pathlib import Path
from typing import Any, Callable

import requests as _requests

logger = logging.getLogger(__name__)

_HF_TOKEN_LOCK = threading.Lock()


@contextlib.contextmanager
def _hf_token_env(token: str | None):
    """Set HUGGING_FACE_HUB_TOKEN for the duration of the block (thread-safe)."""
    if not token:
        yield
        return
    with _HF_TOKEN_LOCK:
        os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    try:
        yield
    finally:
        with _HF_TOKEN_LOCK:
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)


# ── Fit-level constants (llmfit-inspired) ─────────────────────────────────────
FIT_PERFECT = "perfect"  # model uses < 50 % of unified memory
FIT_GOOD = "good"  # 50–70 %
FIT_MARGINAL = "marginal"  # 70–85 %
FIT_TOO_TIGHT = "too_tight"  # > 85 %

_FIT_EMOJI = {
    FIT_PERFECT: "🟢",
    FIT_GOOD: "🟡",
    FIT_MARGINAL: "🟠",
    FIT_TOO_TIGHT: "🔴",
}
_FIT_LABEL = {
    FIT_PERFECT: "Perfect fit",
    FIT_GOOD: "Good fit",
    FIT_MARGINAL: "Marginal — memory will be tight",
    FIT_TOO_TIGHT: "Won't fit — likely OOM crash",
}

# Bytes per parameter for common quantizations
_BITS_PER_QUANT: dict[str, float] = {
    "2bit": 0.25,
    "2-bit": 0.25,
    "q2": 0.25,
    "3bit": 0.375,
    "3-bit": 0.375,
    "q3": 0.375,
    "4bit": 0.50,
    "4-bit": 0.50,
    "q4": 0.50,
    "6bit": 0.75,
    "6-bit": 0.75,
    "q6": 0.75,
    "8bit": 1.00,
    "8-bit": 1.00,
    "q8": 1.00,
    "fp16": 2.00,
    "bf16": 2.00,
    "fp32": 4.00,
}


# Delegates to server_manager to avoid code duplication and to get IPv4 URL
# caching for .local mDNS hostnames.  The lazy import breaks the circular
# dependency (model_manager ← server_manager would otherwise be circular).
def _mgmt_base() -> str | None:
    """Return the management API base URL if remote mode is active."""
    from . import server_manager as sm
    return sm._mgmt_base()


def _mgmt_headers() -> dict[str, str]:
    from . import server_manager as sm
    return sm._mgmt_headers()


def search_mlx_models(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Search models in the mlx-community org on HuggingFace Hub."""
    from huggingface_hub import HfApi

    api = HfApi()
    try:
        kwargs: dict[str, Any] = dict(
            author="mlx-community",
            search=query if query.strip() else None,
            limit=limit,
            sort="downloads",
        )
        import inspect

        sig = inspect.signature(api.list_models)
        if "direction" in sig.parameters:
            kwargs["direction"] = -1
        if "fetch_config" in sig.parameters:
            kwargs["fetch_config"] = False
        models = list(api.list_models(**kwargs))
        # Sort by downloads descending (fallback if direction unsupported)
        models.sort(key=lambda m: getattr(m, "downloads", 0) or 0, reverse=True)
    except Exception as e:
        return [{"error": str(e)}]

    results = []
    for m in models:
        tags = list(getattr(m, "tags", []) or [])
        results.append(
            {
                "id": m.id,
                "downloads": getattr(m, "downloads", 0) or 0,
                "likes": getattr(m, "likes", 0) or 0,
                "tags": tags,
                "last_modified": str(getattr(m, "lastModified", "") or ""),
            }
        )
    return results


def get_cached_models() -> list[dict[str, Any]]:
    """Return all HuggingFace model repos cached on the server (local or remote).

    Only returns repos that contain actual model weight files (safetensors, npz,
    bin, gguf, etc.) — metadata-only stubs created by config.json prefetches are
    excluded.  Also filters out repos smaller than 50 MB.
    """
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(
                f"{mgmt}/models/cached", headers=_mgmt_headers(), timeout=10
            )
            return r.json() if r.status_code == 200 else []
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return []
    try:
        from huggingface_hub import scan_cache_dir

        # Extensions that indicate real model weights are present
        WEIGHT_SUFFIXES = {
            ".safetensors",
            ".bin",
            ".pt",
            ".pth",
            ".gguf",
            ".npz",
            ".ggml",
            ".q4_0",
            ".q4_1",
            ".q8_0",
        }
        MIN_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB — metadata stubs are always tiny

        cache_info = scan_cache_dir(cache_dir=get_hf_cache_dir())
        models = []
        for repo in cache_info.repos:
            if repo.repo_type != "model":
                continue
            if repo.size_on_disk < MIN_SIZE_BYTES:
                continue  # metadata-only stub — skip

            # Check that at least one weight file exists in any revision
            has_weights = False
            for rev in repo.revisions:
                for f in rev.files:
                    if Path(f.file_path).suffix.lower() in WEIGHT_SUFFIXES:
                        has_weights = True
                        break
                if has_weights:
                    break
            if not has_weights:
                continue

            models.append(
                {
                    "id": repo.repo_id,
                    "size_gb": round(repo.size_on_disk / (1024**3), 2),
                    "size_bytes": repo.size_on_disk,
                    "revisions": len(list(repo.revisions)),
                    "path": str(repo.repo_path),
                }
            )
        return sorted(models, key=lambda m: m["size_bytes"], reverse=True)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return []


def download_model(
    model_id: str,
    hf_token: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Download a model to the server (local or remote) from HuggingFace Hub."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            payload: dict[str, Any] = {"model_id": model_id, "token": hf_token or ""}
            r = _requests.post(
                f"{mgmt}/models/download",
                json=payload,
                headers=_mgmt_headers(),
                timeout=15,
            )
            d = r.json()
            return d.get("ok", False), d.get("message", str(r.status_code))
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    with _hf_token_env(hf_token):
        try:
            from huggingface_hub import snapshot_download

            local_dir = snapshot_download(
                repo_id=model_id,
                local_files_only=False,
                cache_dir=get_hf_cache_dir(),
            )
            return True, f"Downloaded to {local_dir}"
        except Exception as e:
            return False, str(e)


def download_model_local(
    model_id: str, hf_token: str | None = None
) -> tuple[bool, str]:
    """Download directly to local HF cache (no remote routing). Used by DownloadManager."""
    with _hf_token_env(hf_token):
        try:
            from huggingface_hub import snapshot_download

            local_dir = snapshot_download(repo_id=model_id, local_files_only=False, cache_dir=get_hf_cache_dir())
            return True, f"Downloaded to {local_dir}"
        except Exception as e:
            return False, str(e)


_partial_bytes_cache: dict[str, tuple[int, float]] = {}
_PARTIAL_CACHE_TTL = 2.0  # seconds


def get_partial_download_bytes(model_id: str) -> int:
    """Return bytes currently present in HF cache for a model (partial or complete).

    Results are cached for ``_PARTIAL_CACHE_TTL`` seconds to avoid repetitive
    ``rglob`` I/O from the polling monitor thread.
    """
    now = _time.monotonic()
    cached = _partial_bytes_cache.get(model_id)
    if cached is not None and (now - cached[1]) < _PARTIAL_CACHE_TTL:
        return cached[0]

    try:
        cache_dir = Path(get_hf_cache_dir())
        folder_name = "models--" + model_id.replace("/", "--")
        model_dir = Path(cache_dir) / folder_name
        if not model_dir.exists():
            _partial_bytes_cache[model_id] = (0, now)
            return 0
        total = 0
        for f in model_dir.rglob("*"):
            if f.is_file() and not f.is_symlink():
                with contextlib.suppress(OSError):
                    total += f.stat().st_size
        _partial_bytes_cache[model_id] = (total, now)
        return total
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return 0


class DownloadManager:
    """Thread-safe local download queue. Module-level singleton; persists across Streamlit reruns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[dict] = []
        self._worker: threading.Thread | None = None
        self._monitor_threads: dict[str, threading.Thread] = {}  # model_id → monitor thread

    def enqueue(self, model_id: str, hf_token: str | None = None) -> bool:
        """Add to queue. Returns False if already queued or downloading."""
        with self._lock:
            for item in self._queue:
                if item["model_id"] == model_id and item["status"] in (
                    "queued",
                    "downloading",
                ):
                    return False
            self._queue.append(
                {
                    "model_id": model_id,
                    "hf_token": hf_token,
                    "status": "queued",
                    "pct": 0.0,
                    "bytes_dl": 0,
                    "total_bytes": 0,
                    "error": None,
                }
            )
        self._ensure_worker()
        return True

    def get_queue(self) -> list[dict]:
        """Return a snapshot copy of the current download queue.

        Returns:
            List of item dicts with keys: model_id, status, pct, bytes_dl,
            total_bytes, error.  Each dict is a copy — mutations do not affect
            the internal queue.
        """
        with self._lock:
            return [dict(i) for i in self._queue]

    def clear_finished(self) -> None:
        """Remove all completed (done/error) entries from the queue."""
        with self._lock:
            self._queue = [
                i for i in self._queue if i["status"] not in ("done", "error")
            ]

    def has_active(self) -> bool:
        """Return True if any download is currently queued or in-progress."""
        with self._lock:
            return any(i["status"] in ("queued", "downloading") for i in self._queue)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                item = next((i for i in self._queue if i["status"] == "queued"), None)
                if item is None:
                    break
                item["status"] = "downloading"

            model_id = item["model_id"]
            hf_token = item["hf_token"]

            # Get expected size for progress %
            try:
                size_gb = get_hf_model_size_gb(model_id, hf_token)
                if size_gb:
                    with self._lock:
                        item["total_bytes"] = int(size_gb * 1024**3)
            except Exception:
                logger.warning("Operation failed", exc_info=True)

            # Monitor bytes-in-cache while downloading
            def _monitor(it: dict) -> None:
                while True:
                    with self._lock:
                        if it["status"] != "downloading":
                            break
                    partial = get_partial_download_bytes(it["model_id"])
                    with self._lock:
                        it["bytes_dl"] = partial
                        if it["total_bytes"] > 0 and partial > 0:
                            it["pct"] = min(partial / it["total_bytes"], 0.99)
                    _time.sleep(2)

                # Self-unregister when done
                with self._lock:
                    self._monitor_threads.pop(it["model_id"], None)

            monitor = threading.Thread(target=_monitor, args=(item,), daemon=True, name=f"download-monitor-{model_id}")
            with self._lock:
                self._monitor_threads[model_id] = monitor
            monitor.start()

            try:
                ok, msg = download_model_local(model_id, hf_token)
                with self._lock:
                    item["status"] = "done" if ok else "error"
                    item["pct"] = 1.0 if ok else item["pct"]
                    item["error"] = None if ok else msg
                    item["bytes_dl"] = get_partial_download_bytes(model_id)
            except Exception as exc:
                with self._lock:
                    item["status"] = "error"
                    item["error"] = str(exc)

            # Signal monitor to stop and wait for cleanup
            monitor.join(timeout=5)
            with self._lock:
                self._monitor_threads.pop(model_id, None)


download_manager = DownloadManager()


def get_download_status(model_id: str) -> dict[str, Any]:
    """Poll remote download status (no-op in local mode).

    In local mode, download_model() runs synchronously (blocks until done), so
    there is no ongoing status to poll — return "local" to signal N/A.
    In remote mode, downloads run in a background thread on the remote machine;
    this polls the mgmt API /models/download_status/{model_id} endpoint for progress.
    """
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(
                f"{mgmt}/models/download_status/{model_id}",
                headers=_mgmt_headers(),
                timeout=5,
            )
            return r.json() if r.status_code == 200 else {"status": "unknown"}
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return {"status": "error"}
    return {"status": "local"}


def delete_model(model_id: str) -> tuple[bool, str]:
    """Delete a cached model from the server (local or remote)."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.delete(
                f"{mgmt}/models/{model_id}", headers=_mgmt_headers(), timeout=15
            )
            if r.status_code == 200:
                return True, f"Deleted {model_id}"
            return False, f"API error {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir(cache_dir=get_hf_cache_dir())
        for repo in cache_info.repos:
            if repo.repo_id == model_id:
                commit_hashes = [rev.commit_hash for rev in repo.revisions]
                strategy = cache_info.delete_revisions(*commit_hashes)
                strategy.execute()
                freed = round(strategy.expected_freed_size / (1024**3), 2)
                return True, f"Deleted {model_id} (freed {freed} GB)"
        return False, f"Model '{model_id}' not found in cache."
    except Exception as e:
        return False, str(e)


def get_cache_total_size() -> float:
    """Return total HuggingFace cache size in GB (on the server)."""
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(
                f"{mgmt}/models/cache_size", headers=_mgmt_headers(), timeout=5
            )
            return float(r.json().get("size_gb", 0.0))
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return 0.0
    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir(cache_dir=get_hf_cache_dir())
        return round(cache_info.size_on_disk / (1024**3), 2)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return 0.0


_MODEL_PRESETS_CACHE: dict[str, dict[str, Any]] = {}
"""Per-session cache for get_model_presets(). Cleared when the mgmt server restarts."""


def get_model_presets(model_id: str, hf_token: str | None = None) -> dict[str, Any]:
    """
    Fetch model config.json from HuggingFace and extract recommended settings.

    Returns a dict with any of: max_tokens, context_length, architecture,
    model_type_hint, is_vision, bits, rope_scaling.
    Empty dict if the card cannot be read.

    Results are cached per model_id for the session lifetime to avoid redundant
    HF API calls from the UI thread.
    """
    cached = _MODEL_PRESETS_CACHE.get(model_id)
    if cached is not None:
        return cached

    import json as _json

    from huggingface_hub import hf_hub_download

    presets: dict[str, Any] = {}
    with _hf_token_env(hf_token):
        try:
            config_path = hf_hub_download(
                repo_id=model_id,
                filename="config.json",
                local_files_only=False,
            )
            with open(config_path) as f:
                cfg = _json.load(f)

            # HF models store context length under different field names depending on
            # architecture. Priority order: max_position_embeddings (standard) →
            # n_ctx (GPT-style) → seq_length → max_sequence_length (fallback).
            # Cap at 131072 even if the model claims higher — that is the practical
            # vllm-mlx limit and avoids requesting more KV cache than the engine supports.
            ctx = (
                cfg.get("max_position_embeddings")
                or cfg.get("n_ctx")
                or cfg.get("seq_length")
                or cfg.get("max_sequence_length")
            )
            if ctx and isinstance(ctx, int):
                presets["context_length"] = ctx
                presets["max_tokens"] = min(ctx, 131072)

            # Architecture
            archs = cfg.get("architectures") or []
            if archs:
                presets["architecture"] = archs[0]

            # Model type
            model_type = cfg.get("model_type", "")
            if model_type:
                presets["model_type_hint"] = model_type

            # Rope scaling info
            rope = cfg.get("rope_scaling")
            if rope:
                presets["rope_scaling"] = rope

            # Vision capability is detected from three independent sources because
            # different model cards use different conventions:
            # 1. model_type / architecture keywords (llava, qwen2_vl, paligemma, etc.)
            # 2. architecture field from HF config.json
            # 3. Model ID string keywords (last-resort heuristic)
            vision_types = {
                "llava",
                "idefics",
                "pali",
                "qwen2_vl",
                "pixtral",
                "gemma3",
                "gemma4",
                "internvl",
                "cogvlm",
                "phi3_v",
                "mipha",
            }
            arch_lower = (archs[0] if archs else "").lower()
            if (
                any(x in model_type.lower() for x in vision_types)
                or any(x in arch_lower for x in {"vision", "llava", "vl", "pixtral"})
                or any(
                    x in model_id.lower()
                    for x in {"-vl-", "-vision", "llava", "idefics", "pixtral"}
                )
            ):
                presets["is_vision"] = True

            # Quantization is inferred from the model ID (e.g., "llama2-7b-4bit")
            # rather than config.json because model_type rarely encodes quantization.
            # This is a UI prefill heuristic; it does not affect server startup or loading.
            name_lower = model_id.lower()
            for bits, patterns in {
                4: ["4bit", "4-bit", "q4"],
                8: ["8bit", "8-bit", "q8"],
                3: ["3bit", "3-bit"],
                6: ["6bit", "6-bit"],
            }.items():
                if any(p in name_lower for p in patterns):
                    presets["bits"] = bits
                    break

            # Default temperature hint (some model cards embed this in generation_config.json)
            try:
                gen_path = hf_hub_download(
                    repo_id=model_id,
                    filename="generation_config.json",
                    local_files_only=False,
                )
                with open(gen_path) as f:
                    gen = _json.load(f)
                temp = gen.get("temperature")
                if temp and isinstance(temp, (int, float)) and 0 < temp <= 2:
                    presets["recommended_temperature"] = float(temp)
            except Exception:
                logger.warning("Operation failed", exc_info=True)

        except Exception:
            logger.warning("Operation failed", exc_info=True)

    # Cache for the session lifetime
    _MODEL_PRESETS_CACHE[model_id] = presets
    return presets


def get_hf_cache_dir() -> str:
    """Return the HuggingFace hub cache directory path.

    Priority (highest first):
    1. ``model_cache_dir`` saved in dashboard config (set via Settings → Models Directory)
    2. ``HF_HUB_CACHE`` environment variable
    3. ``HF_HOME`` environment variable (appends ``/hub``)
    4. Default: ``~/.cache/huggingface/hub``

    When a custom ``model_cache_dir`` is configured it is used directly as the
    hub cache root (i.e. MLX models land in ``<models_dir>/models--{org}--{name}/``
    and GGUF files can coexist as flat files alongside them).
    """
    try:
        from . import server_manager as sm
        cfg = sm._load_local_config()
        custom = cfg.get("model_cache_dir", "").strip()
        if custom:
            return str(Path(custom).expanduser().resolve())
    except Exception as e:
        logger.warning("Could not read model_cache_dir from config: %s", e)

    if "HF_HUB_CACHE" in os.environ:
        return os.environ["HF_HUB_CACHE"]

    hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    return os.path.join(hf_home, "hub")


# ── Memory fit helpers ─────────────────────────────────────────────────────────


def get_total_ram_gb() -> float:
    """Return total system RAM in GB.

    In remote mode, returns the remote machine's unified memory so that
    fit-check results reflect the machine that will actually run the model.
    """
    mgmt = _mgmt_base()
    if mgmt:
        try:
            r = _requests.get(
                f"{mgmt}/memory/stats", headers=_mgmt_headers(), timeout=5
            )
            if r.status_code == 200:
                return float(r.json().get("total_gb", 0.0))
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    try:
        import psutil

        return psutil.virtual_memory().total / (1024**3)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return 0.0


def estimate_size_from_name(model_id: str) -> float | None:
    """Estimate model VRAM requirement from the model ID string.

    Used before download to show memory-fit warnings without requiring an API call
    or downloading metadata. Accuracy is ~70-80% for common quantizations.
    Heuristic only — never used to block a download, just to inform the user.

    Parses parameter count (e.g. 7B, 13B, 72B) and quantization (4bit, 8bit…)
    from the model ID to produce a rough byte estimate.  Returns None when the
    name doesn't contain enough information.
    """
    name = model_id.lower()

    # Known model sizes by name fragment (lookup table for models whose names
    # don't follow the standard NB convention — e.g. "mini", "nano", "small").
    _KNOWN_SIZES: list[tuple[str, float]] = [
        # Phi family (no explicit B count in name)
        ("phi-4-mini",       3.8),
        ("phi-3-mini",       3.8),
        ("phi-3.5-mini",     3.8),
        ("phi-3-small",      7.0),
        ("phi-3-medium",    14.0),
        ("phi-4",           14.0),
        # Gemma (numbers are versions, not param counts)
        ("gemma-2b",         2.0),
        ("gemma-7b",         7.0),
        ("gemma-2-2b",       2.6),
        ("gemma-2-9b",       9.2),
        ("gemma-2-27b",     27.0),
        ("gemma-3-1b",       1.0),
        ("gemma-3-4b",       4.0),
        ("gemma-3-12b",     12.0),
        ("gemma-3-27b",     27.0),
        ("gemma-3n-e2b",     2.0),
        ("gemma-3n-e4b",     4.0),
        # SmolLM (sizes in fragment name are in millions, not B)
        ("smollm2-135m",     0.14),
        ("smollm2-360m",     0.36),
        ("smollm2-1.7b",     1.7),
        ("smollm-135m",      0.14),
        ("smollm-360m",      0.36),
        ("smollm-1.7b",      1.7),
        # Qwen3 (no B count in base name variants)
        ("qwen3-0.6b",       0.6),
        ("qwen3-1.7b",       1.7),
        ("qwen3-4b",         4.0),
        ("qwen3-8b",         8.0),
        ("qwen3-14b",       14.0),
        ("qwen3-30b",       30.0),
        ("qwen3-32b",       32.0),
        # Mistral (marketing names without explicit B count)
        ("mistral-nemo",    12.0),
        # Codestral — more specific variant BEFORE the general entry
        ("codestral-mamba",  7.3),
        ("codestral",       22.0),
        # DeepSeek V3 — 671B MoE; all V3 variants are this size; shows "Too large" correctly
        ("deepseek-v3",    671.0),
    ]
    for fragment, param_b_lookup in _KNOWN_SIZES:
        if fragment in name:
            param_b = param_b_lookup
            bpp: float = 0.50
            for pat, b in _BITS_PER_QUANT.items():
                if pat in name:
                    bpp = b
                    break
            return param_b * bpp * 1.10

    # Mixture-of-Experts pattern FIRST — must run before the generic NB regex
    # so that "8x7B" is parsed as 8 experts × 7B = 56B, not 7B.
    moe = re.search(r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*b(?:[^a-z]|$)", name)
    if moe:
        num_experts = int(moe.group(1))
        expert_b = float(moe.group(2))
        # Active params ≈ 2 experts per token; use full param count for memory estimate
        param_b = num_experts * expert_b
    else:
        # Standard NB pattern (e.g. 7B, 13B, 72B, 0.5B)
        param_b = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*b(?:[^a-z]|$)", name)
        if m:
            param_b = float(m.group(1))
        else:
            # Smaller models listed in millions
            m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:[^a-z]|$)", name)
            if m:
                param_b = float(m.group(1)) / 1000.0

        if param_b is None:
            return None

    # Bytes per parameter from quantization
    bpp = 0.50  # default to 4-bit if unknown
    for pat, b in _BITS_PER_QUANT.items():
        if pat in name:
            bpp = b
            break

    # weights + ~10% overhead (embeddings, norms, KV cache at typical context)
    return param_b * bpp * 1.10


_KV_CACHE_OVERHEAD_FACTOR = 1.25
"""Multiplier applied to weight-only model size to account for KV cache and
runtime overhead (~25% for typical contexts).  This is a conservative estimate
— actual overhead varies by context length, batch size, and model architecture."""


def get_hf_model_size_gb(model_id: str, hf_token: str | None = None) -> float | None:
    """
    Query the HuggingFace Hub API for the total weight file size of a model
    *before* downloading it.  Returns size in GB or None on failure.

    Only sums files that are actual model weights (.safetensors, .npz, .bin,
    .pt, .gguf) — excludes tokenizer files, config JSON, etc.

    The returned value includes a 25 % overhead factor for KV cache and runtime
    buffers so that ``check_model_fit()`` provides more realistic guidance.
    """
    with _hf_token_env(hf_token):
        try:
            from huggingface_hub import HfApi

            api = HfApi()
            info = api.model_info(model_id, files_metadata=True)
            weight_exts = {".safetensors", ".npz", ".bin", ".pt", ".pth", ".gguf"}
            total = 0
            for f in info.siblings or []:
                if Path(f.rfilename).suffix.lower() in weight_exts:
                    total += getattr(f, "size", 0) or 0
            if total <= 0:
                return None
            weight_gb = total / (1024**3)
            return round(weight_gb * _KV_CACHE_OVERHEAD_FACTOR, 1)
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return None


def _score_fit(model_gb: float, total_gb: float) -> str:
    """Return a FIT_* constant based on model_gb vs available total_gb."""
    if total_gb <= 0:
        return FIT_MARGINAL
    ratio = model_gb / total_gb
    if ratio < 0.50:
        return FIT_PERFECT
    if ratio < 0.70:
        return FIT_GOOD
    if ratio < 0.85:
        return FIT_MARGINAL
    return FIT_TOO_TIGHT


def check_model_fit(
    model_id: str,
    hf_token: str | None = None,
    use_api: bool = False,
    total_gb: float | None = None,
) -> dict[str, Any]:
    """
    Check whether a model will fit in unified memory before downloading.

    Returns:
      fit_level   : FIT_PERFECT / FIT_GOOD / FIT_MARGINAL / FIT_TOO_TIGHT
      emoji       : 🟢 / 🟡 / 🟠 / 🔴
      label       : human-readable fit verdict
      model_gb    : estimated weight size in GB (or None)
      total_ram_gb: total system RAM in GB
      source      : "api" | "name" | "unknown"
      tip         : actionable advice string
    """
    total_gb_val = total_gb if total_gb is not None else get_total_ram_gb()
    model_gb: float | None = None
    source = "unknown"

    if use_api:
        model_gb = get_hf_model_size_gb(model_id, hf_token)
        if model_gb is not None:
            source = "api"

    if model_gb is None:
        model_gb = estimate_size_from_name(model_id)
        if model_gb is not None:
            source = "name"

    if model_gb is None or total_gb_val == 0:
        return {
            "fit_level": None,
            "emoji": "❓",
            "label": "Unknown — couldn't estimate model size",
            "model_gb": None,
            "total_ram_gb": total_gb_val,
            "source": "unknown",
            "tip": "Paste the full model ID in the Download by ID tab for an accurate check.",
        }

    fit = _score_fit(model_gb, total_gb_val)
    tips = {
        FIT_PERFECT: f"This model uses ~{model_gb:.1f} GB of your {total_gb_val:.0f} GB — plenty of headroom.",
        FIT_GOOD: f"This model uses ~{model_gb:.1f} GB of your {total_gb_val:.0f} GB — will run well.",
        FIT_MARGINAL: (
            f"This model needs ~{model_gb:.1f} GB of your {total_gb_val:.0f} GB. "
            "Close other apps before loading. Consider a more-quantized variant."
        ),
        FIT_TOO_TIGHT: (
            f"This model needs ~{model_gb:.1f} GB but you only have {total_gb_val:.0f} GB total. "
            "It will likely crash with a Metal out-of-memory error. "
            "Choose a smaller model or a lower-bit quantization."
        ),
    }
    return {
        "fit_level": fit,
        "emoji": _FIT_EMOJI[fit],
        "label": _FIT_LABEL[fit],
        "model_gb": round(model_gb, 1),
        "total_ram_gb": round(total_gb_val, 0),
        "source": source,
        "tip": tips[fit],
    }


def _size_gb_from_params(total_params: int, model_name: str) -> float:
    """Convert a BF16 parameter count to an estimated GB size.

    Applies the quantization factor found in *model_name* (e.g. "4bit" → 0.5
    bytes/param).  Defaults to BF16 (2 bytes/param) if no quant pattern is
    detected — this is correct for models that expose safetensors in BF16.
    """
    bpp = 2.0  # default BF16
    name = model_name.lower()
    for pat, b in _BITS_PER_QUANT.items():
        if pat in name:
            bpp = b
            break
    return (total_params * bpp / (1024 ** 3)) * 1.10


def search_hf_models(
    query: str = "",
    tags: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "downloads",
    direction: str = "desc",
) -> list[dict]:
    """Search all of HuggingFace Hub (not just mlx-community) via REST API."""
    import urllib.parse

    # Map sort value to HF API sort parameter
    hf_sort_map = {
        "downloads": "downloads",
        "likes": "likes",
        "last_modified": "lastModified",
    }
    hf_sort = hf_sort_map.get(sort, "downloads")

    # Normalize direction: accept "asc"/"desc" or "1"/"-1"
    hf_direction = "1" if direction in ("asc", "1") else "-1"

    # Overfetch by 1 to reliably detect whether more results exist beyond this page.
    # Cap at 500 to stay within HF API limits while allowing deep pagination.
    fetch_limit = max(offset + limit + 1, 50)
    fetch_limit = min(fetch_limit, 500)

    params: dict[str, Any] = {
        "sort": hf_sort,
        "direction": hf_direction,
        "limit": str(fetch_limit),
        # Note: full=true and config=true are intentionally omitted — using
        # indexed expand[] params below, which replace those and give explicit
        # control over which fields are returned.
    }
    if query.strip():
        params["search"] = query.strip()
    if tags:
        # Search ALL publishers for models matching the requested tags
        # (not just mlx-community) — catches MLX models from any org.
        if "mlx" in tags:
            non_mlx_tags = [t for t in tags if t != "mlx"]
            if non_mlx_tags:
                params["filter"] = "mlx," + ",".join(non_mlx_tags)
            else:
                params["filter"] = "mlx"
        else:
            params["filter"] = ",".join(tags)
    # Append indexed expand[] params — the HF API requires expand[0]=, expand[1]=
    # syntax (not expand[]=) and does NOT accept them in urlencode's dict form.
    # IMPORTANT: using expand[] replaces full=true/config=true — ALL needed fields
    # must be explicitly listed or they will be absent from the response.
    base_url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(params)
    url = (
        base_url
        + "&expand%5B0%5D=safetensors"   # for size estimation
        + "&expand%5B1%5D=cardData"       # for base_model / family resolver
        + "&expand%5B2%5D=tags"           # for is_mlx detection (REQUIRED)
        + "&expand%5B3%5D=likes"          # for likes sort / display
        + "&expand%5B4%5D=lastModified"   # for recency sort / display
        + "&expand%5B5%5D=createdAt"      # for recency display
        + "&expand%5B6%5D=config"         # for family resolver hf_config
        + "&expand%5B7%5D=downloads"      # NOT a guaranteed base field — must expand explicitly
    )

    # Get total RAM for fit calculation
    try:
        import psutil
        total_gb = psutil.virtual_memory().total / (1024**3)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        total_gb = 0.0

    # Retry up to 3 attempts with exponential back-off — HF API is occasionally slow.
    _last_exc: Exception | None = None
    resp = None
    for _attempt in range(3):
        try:
            resp = _requests.get(url, timeout=30)
            resp.raise_for_status()
            break
        except (_requests.exceptions.Timeout, _requests.exceptions.ConnectionError) as exc:
            _last_exc = exc
            if _attempt < 2:
                _time.sleep(2 ** _attempt)  # 1 s, 2 s
    if resp is None:
        return [{"error": f"HuggingFace search timed out — check your connection and try again. ({_last_exc})"}]

    try:
        results = []
        raw_models = resp.json()
        # Lazy-import the family resolver — it loads the curated table on init
        try:
            from vllm_mlx.dashboard.model_family_resolver import ModelFamilyResolver
            resolver = ModelFamilyResolver()
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            resolver = None
        for m in raw_models:
            model_id = m.get("modelId") or m.get("id", "")
            if not model_id:
                continue
            model_tags = list(m.get("tags") or [])
            card_data = m.get("cardData") or {}

            # --- 3-tier size resolution (no extra API calls) ---
            # Tier 1: name-based heuristic (fast, works for standard NB naming)
            size_gb = estimate_size_from_name(model_id)

            # Tier 2: safetensors.total from expand — exact BF16 param count
            # returned by the HF API for most non-quantized models.
            if size_gb is None:
                st = m.get("safetensors") or {}
                total_params = st.get("total") if isinstance(st, dict) else None
                if total_params:
                    size_gb = _size_gb_from_params(int(total_params), model_id)

            # Tier 3: base_model card field — e.g. quantized MLX models link to
            # their BF16 parent whose name usually contains the param count.
            if size_gb is None:
                base_model = card_data.get("base_model")
                if isinstance(base_model, list):
                    base_model = base_model[0] if base_model else None
                if base_model and isinstance(base_model, str):
                    base_size = estimate_size_from_name(base_model)
                    if base_size is not None:
                        # Re-apply quant factor from the CURRENT model's name
                        # (base_size was computed with its own quant, so extract
                        # raw param_b estimate and reweight for this model).
                        raw_b = base_size / 1.10  # strip overhead
                        # Determine current model's bpp
                        cur_bpp = 0.50  # default 4-bit for quantized MLX models
                        cur_name = model_id.lower()
                        for pat, bval in _BITS_PER_QUANT.items():
                            if pat in cur_name:
                                cur_bpp = bval
                                break
                        # base_size was computed as param_b * base_bpp * 1.10
                        # Recover param_b = base_size / (base_bpp * 1.10)
                        base_name = base_model.lower()
                        base_bpp = 2.0  # BF16 default for base models
                        for pat, bval in _BITS_PER_QUANT.items():
                            if pat in base_name:
                                base_bpp = bval
                                break
                        param_b = base_size / (base_bpp * 1.10)
                        size_gb = param_b * cur_bpp * 1.10
            # --- end size resolution ---

            fit_level = None
            if size_gb is not None and total_gb > 0:
                fit_level = _score_fit(size_gb, total_gb)
            # Resolve family data
            family_data = None
            if resolver is not None:
                try:
                    config = m.get("config")
                    family_data = resolver.resolve(
                        model_id=model_id,
                        hf_base_model=card_data.get("base_model"),
                        hf_tags=model_tags,
                        hf_config=config,
                    )
                except Exception as e:
                    logger.warning("Family resolution failed for %s: %s", model_id, e, exc_info=True)
            results.append(
                {
                    "id": model_id,
                    "downloads": m.get("downloads", 0) or 0,
                    "likes": m.get("likes", 0) or 0,
                    "tags": model_tags,
                    "last_modified": str(m.get("lastModified") or ""),
                    "created_at": str(m.get("createdAt") or ""),
                    "is_mlx": "mlx" in [t.lower() for t in model_tags],
                    "size_gb": size_gb,
                    "fit_level": fit_level,
                    "trending_score": round(float(m.get("trendingScore") or 0.0), 2),
                    "family_data": family_data,
                }
            )
        # Return ALL fetched results (the store will handle pagination)
        return results
    except Exception as e:
        return [{"error": str(e)}]


def scan_gguf_files(base_dir: str | None = None) -> list[dict[str, Any]]:
    """Scan *base_dir* (or the configured models directory) for GGUF model files.

    Searches one level deep: ``base_dir/*.gguf`` and ``base_dir/**/*.gguf``
    (recurses one subdirectory level so users can organise GGUFs into folders).

    Returns a list of dicts with keys ``path`` (str), ``name`` (str), and
    ``size_gb`` (float).  Results are sorted by name.
    """
    search_root = Path(base_dir).expanduser().resolve() if base_dir else Path(get_hf_cache_dir())
    if not search_root.exists():
        return []

    results: list[dict[str, Any]] = []
    seen: set[Path] = set()
    # Flat files in root + one level of subdirectories
    for pattern in ("*.gguf", "*/*.gguf"):
        for p in sorted(search_root.glob(pattern)):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            try:
                size_gb = round(p.stat().st_size / (1024 ** 3), 2)
            except OSError:
                size_gb = 0.0
            results.append({
                "path": str(p),
                "name": p.name,
                "size_gb": size_gb,
            })

    return sorted(results, key=lambda r: r["name"].lower())
