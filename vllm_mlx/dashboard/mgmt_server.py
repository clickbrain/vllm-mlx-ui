# SPDX-License-Identifier: Apache-2.0
"""
Management API server for vllm-mlx dashboard.

Runs on a separate port (default 8502) alongside the Streamlit UI.
Remote dashboard clients call this API to control the inference server,
manage models, and access logs/metrics — the same operations the local
dashboard performs via subprocess calls.

Endpoints are intentionally simple: no ORM, no database, just thin
wrappers around the same server_manager / model_manager functions the
local dashboard uses.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import benchmark_runner as br
from . import model_manager as mm
from . import quality_runner as qr
from . import server_manager as sm

app = FastAPI(
    title="vllm-mlx Management API",
    description="Remote control API for the vllm-mlx dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # Allow all origins for the /v1/* proxy routes so that browser-based
    # OpenAI-compatible clients on the local network can use the proxy URL.
    # Management endpoints that mutate server state are protected by _check_auth
    # (mgmt_api_key), so a permissive CORS policy here is acceptable.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Remove X-Frame-Options so the management API can be embedded in iFrames
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _StarletteRequest


class _PermissiveHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _StarletteRequest, call_next):
        response = await call_next(request)
        # Allow framing from any origin.
        # CSP frame-ancestors is the correct modern mechanism; some legacy
        # clients still honour X-Frame-Options, so we remove it entirely
        # (any value other than ALLOWALL would block iframes).
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        return response


app.add_middleware(_PermissiveHeadersMiddleware)


# ── Auth ─────────────────────────────────────────────────────────────────────
# Cache the API key with a short TTL to avoid a disk read on every request.
# 30s TTL: short enough that disabling the key takes effect within half a
# minute; long enough to avoid stat() syscalls on every request (which runs
# in tight loops during streaming and fragment auto-refresh).
# The cache is invalidated automatically when the key changes (TTL ≤ 30 s).
_auth_key_cache: dict[str, Any] = {"key": None, "ts": 0.0}
_AUTH_KEY_TTL = 30.0  # seconds


def _get_auth_key() -> str:
    now = time.time()
    if now - _auth_key_cache["ts"] > _AUTH_KEY_TTL:
        try:
            _auth_key_cache["key"] = sm.load_config().get("mgmt_api_key", "").strip()
        except Exception:
            _auth_key_cache["key"] = ""
        _auth_key_cache["ts"] = now
    return _auth_key_cache["key"] or ""


def _check_auth(x_api_key: str | None = Header(default=None)) -> None:
    key = _get_auth_key()
    if key and x_api_key != key:
        raise HTTPException(status_code=401, detail="Invalid management API key")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    """Liveness probe — returns 200 OK with ``{"ok": true}`` when the server is up."""
    return {"ok": True}


# ── Server lifecycle ──────────────────────────────────────────────────────────

@app.get("/status")
def status(_: None = Depends(_check_auth)) -> dict:
    """Return the current inference server status (running, healthy, PID, etc.)."""
    return sm.get_server_status()


@app.post("/start")
def start(_: None = Depends(_check_auth)) -> dict:
    """Start the inference server using the currently saved configuration.

    Raises:
        HTTPException: 400 if no model is configured.
    """
    config = sm.load_config()
    if not config.get("model"):
        raise HTTPException(status_code=400, detail="No model selected. Set a model in config first.")
    ok, msg = sm.start_server(config)
    return {"ok": ok, "message": msg}


@app.post("/stop")
def stop(_: None = Depends(_check_auth)) -> dict:
    """Send SIGTERM to the inference server and return stop status."""
    ok, msg = sm.stop_server()
    return {"ok": ok, "message": msg}


@app.get("/logs")
def logs(lines: int = 200, _: None = Depends(_check_auth)) -> dict:
    """Return the tail of the inference server log as a list of strings.

    Args:
        lines: Maximum number of trailing lines to return (default 200).
    """
    raw = sm.get_logs(lines)
    return {"lines": raw.splitlines() if isinstance(raw, str) else list(raw)}


@app.get("/metrics")
def metrics(_: None = Depends(_check_auth)) -> dict:
    """Return real-time engine metrics from the inference server."""
    return sm.get_metrics() or {}


# ── Cache proxy ───────────────────────────────────────────────────────────────

@app.get("/cache/stats")
def cache_stats(_: None = Depends(_check_auth)) -> dict:
    """Proxy for /v1/cache/stats on the inference server."""
    result = sm.get_cache_stats()
    return result if result is not None else {"error": "unavailable"}


@app.delete("/cache/{cache_type}")
def clear_cache_proxy(cache_type: str, _: None = Depends(_check_auth)) -> dict:
    """Proxy for cache clear (cache_type: 'all' or 'prefix')."""
    ok, msg = sm.clear_cache(cache_type)
    return {"ok": ok, "status": msg}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/config")
def get_config(_: None = Depends(_check_auth)) -> dict:
    """Return the currently saved inference server configuration."""
    return sm.load_config()


@app.post("/config")
def set_config(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Persist a new server configuration, stripping local-only connectivity keys.

    Local-only keys (remote_mgmt_url, mgmt_api_key, etc.) are filtered out
    before saving to prevent the server from trying to proxy config reads back
    to itself (infinite loop).

    Args:
        data: Config dict submitted by the client.
    """
    # A misconfigured or stale client might submit the full config including
    # remote_mgmt_url. If the server saved that, it would try to proxy every
    # subsequent load_config() call back to itself — infinite loop.
    # server_manager._LOCAL_ONLY_KEYS defines the exact keys to strip.
    from .server_manager import _LOCAL_ONLY_KEYS
    filtered = {k: v for k, v in data.items() if k not in _LOCAL_ONLY_KEYS}
    sm.save_config(filtered)
    return {"ok": True}


# ── Models ────────────────────────────────────────────────────────────────────

@app.get("/models/cached")
def cached_models(_: None = Depends(_check_auth)) -> list:
    """Return all locally cached HuggingFace model repos that contain weight files."""
    return mm.get_cached_models()


@app.get("/models/cache_size")
def cache_size(_: None = Depends(_check_auth)) -> dict:
    """Return the total size of the HuggingFace model cache in GB."""
    try:
        size_gb = mm.get_cache_total_size()
    except Exception:
        size_gb = 0.0
    return {"size_gb": size_gb}


class DownloadRequest(BaseModel):
    model_id: str
    # NOTE: The HF token is transmitted as a plain HTTP JSON body field.
    # On a private wired/Thunderbolt network the risk is low, but users on
    # shared Wi-Fi should be aware. The token is never logged or persisted
    # beyond the download operation (cleaned up in model_manager's finally block).
    token: str = ""


_download_status: dict[str, Any] = {}
_download_lock = threading.Lock()


@app.post("/models/download")
def download_model(req: DownloadRequest, _: None = Depends(_check_auth)) -> dict:
    """Starts a background download and returns immediately."""
    model_id = req.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    with _download_lock:
        if _download_status.get(model_id, {}).get("status") == "downloading":
            return {"ok": True, "message": "Already downloading", "status": "downloading"}
        _download_status[model_id] = {"status": "downloading", "error": None, "bytes_downloaded": 0, "total_bytes": 0}

    def _do_download() -> None:
        try:
            total_bytes = 0
            try:
                size_gb = mm.get_hf_model_size_gb(model_id, req.token or None)
                if size_gb:
                    total_bytes = int(size_gb * 1024 ** 3)
                    with _download_lock:
                        _download_status[model_id]["total_bytes"] = total_bytes
            except Exception:
                pass

            def _monitor() -> None:
                import time as _t
                while True:
                    with _download_lock:
                        if _download_status.get(model_id, {}).get("status") != "downloading":
                            break
                    partial = mm.get_partial_download_bytes(model_id)
                    with _download_lock:
                        if model_id in _download_status:
                            _download_status[model_id]["bytes_downloaded"] = partial
                    _t.sleep(2)

            threading.Thread(target=_monitor, daemon=True).start()

            mm.download_model_local(model_id, req.token or None)
            with _download_lock:
                _download_status[model_id] = {
                    "status": "done",
                    "error": None,
                    "bytes_downloaded": mm.get_partial_download_bytes(model_id),
                    "total_bytes": total_bytes,
                }
        except Exception as exc:
            with _download_lock:
                _download_status[model_id] = {
                    "status": "error",
                    "error": str(exc),
                    "bytes_downloaded": 0,
                    "total_bytes": 0,
                }

    # Run download in a background thread so the HTTP response returns immediately.
    # The client polls GET /models/download_status/{model_id} for progress.
    # _download_lock prevents duplicate concurrent downloads of the same model.
    threading.Thread(target=_do_download, daemon=True).start()
    return {"ok": True, "message": f"Download started for {model_id}", "status": "downloading"}


@app.get("/models/download_status/{model_id:path}")
def download_status(model_id: str, _: None = Depends(_check_auth)) -> dict:
    """Return the current download progress for a model.

    Args:
        model_id: HuggingFace repo ID (e.g. ``mlx-community/Llama-3.2-1B-4bit``).

    Returns:
        Dict with keys: status (downloading/done/error/unknown), error, bytes_downloaded,
        total_bytes.
    """
    with _download_lock:
        return _download_status.get(model_id, {"status": "unknown", "error": None})


@app.delete("/models/{model_id:path}")
def delete_model(model_id: str, _: None = Depends(_check_auth)) -> dict:
    """Delete a cached model from the HuggingFace model cache.

    Args:
        model_id: HuggingFace repo ID to delete.

    Raises:
        HTTPException: 500 on unexpected deletion errors.
    """
    try:
        ok, msg = mm.delete_model(model_id)
        return {"ok": ok, "message": msg}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/models/search")
def search_models(
    q: str = "",
    tags: str = "",
    limit: int = 30,
    offset: int = 0,
    sort: str = "downloads",
    _: None = Depends(_check_auth),
) -> dict:
    """Search HuggingFace Hub for models. Pass tags=mlx for MLX-only results."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = mm.search_hf_models(query=q, tags=tag_list, limit=limit, offset=offset, sort=sort)
    return {
        "results": results,
        "offset": offset,
        "limit": limit,
        "has_more": len(results) == limit,
    }


class LoadModelRequest(BaseModel):
    model_id: str


def _compute_optimal_params(
    hint: str,
    task_mode: str,
    max_tokens: int,
) -> dict[str, Any]:
    """
    Compute optimal inference parameters for a model + task mode combination.

    ``hint`` is a lowercased string combining model_type_hint and architecture
    (used to identify the model family).  ``task_mode`` is one of:
      - "chat"      General conversation. Balanced temperature.
      - "code"      Code generation / completion. Low temperature, greedy-ish.
      - "creative"  Creative writing / brainstorming. High temperature.
      - "analysis"  Summarisation / reasoning / data analysis. Low-mid temperature.
      - "precise"   Factual Q&A / retrieval. Near-zero temperature.

    Returns a dict of sampling parameters suitable for the chat completion API.
    """
    # --- Per-model-family base settings ---
    if any(x in hint for x in ("qwen3", "qwen2")):
        base = {"temperature": 0.6, "top_p": 0.9,  "top_k": 20, "min_p": 0.0, "repetition_penalty": 1.0}
    elif "deepseek" in hint:
        base = {"temperature": 0.6, "top_p": 0.95, "top_k": 0,  "min_p": 0.0, "repetition_penalty": 1.0}
    elif "llama" in hint or "mistral" in hint:
        base = {"temperature": 0.6, "top_p": 0.9,  "top_k": 0,  "min_p": 0.0, "repetition_penalty": 1.0}
    elif "gemma" in hint:
        base = {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "min_p": 0.0, "repetition_penalty": 1.0}
    elif "phi" in hint:
        base = {"temperature": 0.0, "top_p": 1.0,  "top_k": 0,  "min_p": 0.0, "repetition_penalty": 1.0}
    else:
        base = {"temperature": 0.7, "top_p": 0.9,  "top_k": 0,  "min_p": 0.0, "repetition_penalty": 1.0}

    # --- Task-mode overrides applied on top of model-family base ---
    # These deltas shift the base toward what works best for each task type.
    mode = task_mode.lower()
    if mode == "code":
        # Low temperature for determinism; greedy sampling; penalise repetition slightly
        base.update({"temperature": min(base["temperature"], 0.2), "top_p": 1.0, "top_k": 0, "repetition_penalty": 1.05})
        tokens = min(max_tokens, 4096)
    elif mode == "creative":
        # High temperature for diversity; nucleus sampling wide open
        base.update({"temperature": max(base["temperature"], 1.0), "top_p": 0.97, "top_k": 0, "repetition_penalty": 1.0})
        tokens = max_tokens
    elif mode == "analysis":
        # Moderate temperature; prefer likely tokens; longer context for summaries
        base.update({"temperature": max(min(base["temperature"], 0.5), 0.3), "top_p": 0.9, "top_k": 0, "repetition_penalty": 1.0})
        tokens = max_tokens
    elif mode == "precise":
        # Near-zero temperature for factual / retrieval tasks
        base.update({"temperature": 0.0, "top_p": 1.0, "top_k": 1, "repetition_penalty": 1.0})
        tokens = min(max_tokens, 1024)
    else:
        # "chat" — use model-family base unchanged
        tokens = max_tokens

    base["max_tokens"] = tokens
    return base


@app.get("/models/presets")
def model_presets(
    model_id: str,
    task_mode: str = "chat",
    _: None = Depends(_check_auth),
) -> dict:
    """
    Return recommended inference settings for a model and task mode.

    ``task_mode`` controls the sampling strategy:
    - ``chat``     — balanced general conversation
    - ``code``     — low-temperature deterministic code generation
    - ``creative`` — high-temperature creative writing / brainstorming
    - ``analysis`` — moderate temperature for reasoning and summarisation
    - ``precise``  — near-zero temperature for factual Q&A / retrieval

    The response includes ``recommended`` (sampling params) and
    ``task_mode`` (echoed back) alongside the raw model presets.
    """
    if not model_id.strip():
        raise HTTPException(status_code=400, detail="model_id is required")
    valid_modes = {"chat", "code", "creative", "analysis", "precise"}
    if task_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"task_mode must be one of {sorted(valid_modes)}")
    try:
        presets = mm.get_model_presets(model_id.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    model_type = presets.get("model_type_hint", "").lower()
    arch = presets.get("architecture", "").lower()
    hint = model_type + " " + arch
    max_tokens = presets.get("max_tokens", 2048)

    recommended = _compute_optimal_params(hint, task_mode, max_tokens)

    return {**presets, "recommended": recommended, "task_mode": task_mode}


@app.post("/server/load")
def load_model(req: LoadModelRequest, _: None = Depends(_check_auth)) -> dict:
    """Update the configured model; restart the server if it is currently running."""
    model_id = req.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    cfg = sm.load_config()
    was_running = sm.get_server_status().get("running", False)

    try:
        presets = mm.get_model_presets(model_id)
        if presets.get("max_tokens"):
            cfg["max_tokens"] = presets["max_tokens"]
            cfg["max_request_tokens"] = presets["max_tokens"]
    except Exception:
        pass

    cfg["model"] = model_id
    sm.save_config(cfg)

    if was_running:
        sm.stop_server()
        time.sleep(1)
        sm.start_server(cfg)

    return {"ok": True, "model": model_id, "restarted": was_running}


# ── Memory ────────────────────────────────────────────────────────────────────

@app.get("/memory/stats")
def memory_stats(_: None = Depends(_check_auth)) -> dict:
    """Return unified memory stats for this machine."""
    return sm.get_memory_stats()


@app.post("/memory/release")
def memory_release(_: None = Depends(_check_auth)) -> dict:
    """Release memory on this machine (stops server, GC, MLX cache clear)."""
    return sm.force_release_memory()


# ── Benchmarks ────────────────────────────────────────────────────────────────

@app.get("/benchmarks")
def list_benchmarks(_: None = Depends(_check_auth)) -> list:
    """Return all persisted benchmark result dicts."""
    return br.load_results()


@app.delete("/benchmarks/{result_id}")
def delete_benchmark(result_id: int, _: None = Depends(_check_auth)) -> dict:
    """Delete a single benchmark result by its list index.

    Args:
        result_id: Zero-based index of the result to delete.

    Raises:
        HTTPException: 404 if result_id is out of range.
    """
    results = br.load_results()
    if not (0 <= result_id < len(results)):
        raise HTTPException(status_code=404, detail=f"Benchmark result {result_id} not found")
    br.delete_result(result_id)
    return {"ok": True}


_benchmark_running = False
_benchmark_lock = threading.Lock()


@app.post("/benchmark/run")
def run_benchmark_endpoint(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start a benchmark run for one or more models in the background.
    Poll GET /benchmark/status to check progress, GET /benchmarks for results.
    """
    global _benchmark_running
    with _benchmark_lock:
        if _benchmark_running:
            return {"ok": False, "message": "A benchmark is already running"}
        _benchmark_running = True

    model_ids: list[str] = req.get("model_ids", [])
    config: dict[str, Any] = req.get("config", {})
    runs = int(config.get("runs", 3))
    max_tokens = int(config.get("max_tokens", 256))
    label = req.get("label", "") or config.get("label", "")

    if not model_ids:
        with _benchmark_lock:
            _benchmark_running = False
        raise HTTPException(status_code=400, detail="model_ids is required")

    def _run() -> None:
        global _benchmark_running
        try:
            running_model = sm.load_config().get("model", "")
            server_running = sm.get_server_status().get("running", False)
            server_url = sm.get_server_url()
            for model_id in model_ids:
                if server_running and running_model and running_model == model_id:
                    br.run_live_benchmark(
                        model_id,
                        server_url=server_url,
                        prompts=runs,
                        max_tokens=max_tokens,
                        label=label,
                    )
                else:
                    br.run_benchmark(model_id, prompts=runs, max_tokens=max_tokens)
        finally:
            with _benchmark_lock:
                _benchmark_running = False

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": f"Benchmark started for {len(model_ids)} model(s)"}


@app.post("/benchmark/stop")
def stop_benchmark_endpoint(_: None = Depends(_check_auth)) -> dict:
    """Signal the running speed benchmark to stop (sets running flag to False)."""
    global _benchmark_running
    with _benchmark_lock:
        _benchmark_running = False
    return {"ok": True}



    """Return whether a benchmark run is currently in progress."""
    return {"running": _benchmark_running}


# ── Cost analysis ─────────────────────────────────────────────────────────────

_COST_RATES = {
    "small":  {"input_per_1m": 0.15,  "output_per_1m": 0.60},   # GPT-4o-mini equiv
    "medium": {"input_per_1m": 0.30,  "output_per_1m": 1.20},   # Claude Haiku equiv
    "large":  {"input_per_1m": 2.50,  "output_per_1m": 10.00},  # GPT-4o equiv
}

_SIZE_PATTERNS: list[tuple[str, str]] = [
    # Patterns ordered largest→smallest so the first match wins.
    ("72b", "large"), ("70b", "large"), ("32b", "large"), ("30b", "large"),
    ("14b", "medium"), ("13b", "medium"), ("8b", "medium"), ("7b", "medium"),
    ("3b", "small"), ("1b", "small"), ("0.6b", "small"),
]


def _detect_tier(model_id: str) -> str:
    name = model_id.lower()
    for pattern, tier in _SIZE_PATTERNS:
        if pattern in name:
            return tier
    return "medium"


@app.get("/stats/cost")
def cost_stats(_: None = Depends(_check_auth)) -> dict:
    """Return token usage and estimated cloud cost equivalents from benchmark history."""
    results = br.load_results()

    total_input = 0
    total_output = 0
    per_model: dict[str, dict] = {}

    for r in results:
        if not isinstance(r, dict):
            continue
        model_id: str = str(r.get("model") or r.get("model_id") or "unknown")
        prompts = int(r.get("prompts") or r.get("num_runs") or r.get("runs") or 1)
        max_tokens = int(r.get("max_tokens") or 256)
        success = r.get("success", True)
        if not success:
            continue

        # Estimate token counts from benchmark parameters.
        # Input: each test prompt is ~50 tokens on average (conservative).
        # Output: prompts * max_tokens (upper bound; actual may be less).
        input_tokens = prompts * 50
        output_tokens = prompts * max_tokens

        total_input += input_tokens
        total_output += output_tokens

        if model_id not in per_model:
            per_model[model_id] = {"input": 0, "output": 0}
        per_model[model_id]["input"] += input_tokens
        per_model[model_id]["output"] += output_tokens

    def _calc_cost(inp: int, out: int, tier: str) -> float:
        rates = _COST_RATES[tier]
        return inp / 1_000_000 * rates["input_per_1m"] + out / 1_000_000 * rates["output_per_1m"]

    total_cost = 0.0
    by_model = []
    for model_id, counts in per_model.items():
        tier = _detect_tier(model_id)
        cost = _calc_cost(counts["input"], counts["output"], tier)
        total_cost += cost
        by_model.append({
            "model_id": model_id,
            "tier": tier,
            "tokens_generated": counts["output"],
            "estimated_cost_usd": round(cost, 4),
        })

    by_model.sort(key=lambda x: x["estimated_cost_usd"], reverse=True)

    # Estimate monthly savings assuming current usage repeats monthly.
    # We treat the benchmark history as a proxy for production usage volume.
    # Monthly savings = what you'd pay a cloud API for the same tokens.
    estimated_monthly_savings = round(total_cost * 30, 2)

    return {
        "benchmarks_analyzed": len([r for r in results if r.get("success", True)]),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "estimated_cloud_cost_usd": round(total_cost, 4),
        "estimated_monthly_savings_usd": estimated_monthly_savings,
        "by_model": by_model,
        "rates_used": _COST_RATES,
    }


# ── Auto model-switch proxy ───────────────────────────────────────────────────
# When a chat client (e.g. OpenAI-compatible app) sends a request with a model
# name that differs from the currently loaded model, this proxy endpoint
# automatically stops the server, reloads with the new model and optimal
# settings, waits for it to be healthy, then forwards the request.

# Guards _hot_swap_if_needed() against concurrent swap attempts.
# Without the lock, two simultaneous requests for a different model would
# both detect the mismatch and both call stop_server() + start_server(),
# causing a race that leaves the server in an undefined state.
# Threads that lose the lock re-verify inside (step 5 above) — if the
# winning thread already swapped to the right model, losers skip.
_swap_lock = threading.Lock()


_HF_REPO_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?/[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$')


def _hot_swap_if_needed(requested_model: str) -> None:
    """Auto-swap the loaded model when an OpenAI client requests a different one.

    Called by the /v1/chat/completions and /v1/completions proxy endpoints to
    support clients that specify a model ID in their request.

    Security: only swaps to models already cached locally. Uncached model IDs
    are silently ignored (no download is triggered).

    Steps:
      1. Normalise the requested model ID.
      2. No-op if requested model is already loaded.
      3. No-op if requested model is not in the local cache.
      4. Acquire _swap_lock (prevents concurrent swap attempts).
      5. Re-verify under lock (another thread may have swapped already).
      6. Fetch model presets (context length, max_tokens) for the new model.
      7. Stop current server, start new server, wait up to 120s for health.

    The 120s / 2s-poll timeout covers large models that take 60-90s to load.
    """
    # Basic format validation — must look like org/repo
    if not _HF_REPO_RE.match(requested_model):
        return

    cfg = sm.load_config()
    current = cfg.get("model", "").strip()
    if current == requested_model:
        return

    # Only allow switching to a model that's already downloaded
    cached_ids = {m["id"] for m in mm.get_cached_models()}
    if requested_model not in cached_ids:
        return  # Refuse — not cached; do not trigger a download

    with _swap_lock:
        # Re-check inside lock in case another thread already swapped
        cfg = sm.load_config()
        if cfg.get("model", "").strip() == requested_model:
            return

        # Try to load presets for the new model
        try:
            presets = mm.get_model_presets(requested_model)
            if presets.get("max_tokens"):
                cfg["max_tokens"] = presets["max_tokens"]
                cfg["max_request_tokens"] = presets["max_tokens"]
        except Exception:
            pass

        cfg["model"] = requested_model
        sm.stop_server()
        time.sleep(2)
        sm.start_server(cfg)

        # Wait up to 120 s for the server to become healthy
        for _ in range(60):
            time.sleep(2)
            status = sm.get_server_status()
            if status.get("healthy"):
                break


def _needs_hot_swap(requested_model: str) -> bool:
    """Return True if requested_model differs from the currently loaded model
    and is available in the local cache.  Does NOT acquire _swap_lock."""
    if not _HF_REPO_RE.match(requested_model):
        return False
    cfg = sm.load_config()
    if cfg.get("model", "").strip() == requested_model:
        return False
    cached_ids = {m["id"] for m in mm.get_cached_models()}
    return requested_model in cached_ids


def _sse_delta(content: str) -> str:
    """Format a single assistant content delta as an SSE data line."""
    import json as _j
    payload = {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
    }
    return f"data: {_j.dumps(payload)}\n\n"


@app.post("/v1/chat/completions")
async def proxy_chat(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """
    Proxy for /v1/chat/completions.

    Auto model-switch behaviour (when auto_model_switch is enabled):
      • stream:true  — immediately opens SSE, sends a "switching model" notification
                       then streams the real reply. Client gets live feedback.
      • stream:false — waits for the swap to complete (up to 120 s), then returns
                       a plain JSON response. No notification is possible since the
                       client is waiting for a single response body.

    For requests that do NOT require a model switch the proxy passes through
    verbatim, respecting the client's stream preference.
    """
    import asyncio
    import httpx

    requested_model = request.get("model", "").strip()
    cfg_check = sm.load_config()
    auto_switch = cfg_check.get("auto_model_switch", False)
    needs_switch = bool(requested_model and auto_switch and _needs_hot_swap(requested_model))
    client_wants_stream = bool(request.get("stream"))

    cfg = sm.load_config()
    target = sm.get_server_url(cfg)
    req_headers: dict[str, str] = {"Content-Type": "application/json"}
    key = cfg.get("api_key", "").strip()
    if key:
        req_headers["Authorization"] = f"Bearer {key}"

    if needs_switch:
        if client_wants_stream:
            # ── Streaming model-switch path ──────────────────────────────────
            # Push notification immediately, then stream the real reply.
            from fastapi.responses import StreamingResponse

            async def _switch_and_stream():
                notice = (
                    f"⏳ Switching model to **{requested_model}** — "
                    "please wait while it loads…"
                )
                yield _sse_delta(notice)

                swap_done = asyncio.Event()
                swap_error: list[str] = []

                async def _do_swap() -> None:
                    try:
                        await asyncio.to_thread(_hot_swap_if_needed, requested_model)
                    except Exception as exc:
                        swap_error.append(str(exc))
                    finally:
                        swap_done.set()

                asyncio.create_task(_do_swap())

                while not swap_done.is_set():
                    try:
                        await asyncio.wait_for(swap_done.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"

                if swap_error:
                    yield _sse_delta(f"\n\n❌ Model switch failed: {swap_error[0]}")
                    yield "data: [DONE]\n\n"
                    return

                yield _sse_delta("\n\n")

                cfg2 = sm.load_config()
                target2 = sm.get_server_url(cfg2)
                req2 = {**request, "stream": True}

                try:
                    async with httpx.AsyncClient(timeout=300) as _client:
                        async with _client.stream(
                            "POST", f"{target2}/v1/chat/completions",
                            json=req2, headers=req_headers,
                        ) as resp:
                            async for chunk in resp.aiter_bytes():
                                yield chunk
                except Exception as exc:
                    yield _sse_delta(f"\n\n❌ Request failed after model switch: {exc}")
                    yield "data: [DONE]\n\n"

            return StreamingResponse(_switch_and_stream(), media_type="text/event-stream")

        else:
            # ── Non-streaming model-switch path ──────────────────────────────
            # Block until the swap completes, then return a regular JSON response.
            # The client times out only if the model takes > 120 s to load.
            try:
                await asyncio.to_thread(_hot_swap_if_needed, requested_model)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"Model switch failed: {exc}")

            cfg2 = sm.load_config()
            target2 = sm.get_server_url(cfg2)
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    resp = await client.post(
                        f"{target2}/v1/chat/completions",
                        json=request, headers=req_headers,
                    )
                    return resp.json()
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc))

    # ── Normal path (no model switch needed) ────────────────────────────────
    # If the inference server is currently starting up (model loading from a
    # dashboard-initiated switch), wait for it to become healthy before forwarding.
    status = sm.get_server_status()
    if status.get("running") and not status.get("healthy"):
        # Server process is alive but not yet ready — wait up to 120 s
        for _ in range(60):
            await asyncio.sleep(2)
            status = sm.get_server_status()
            if status.get("healthy"):
                break
        if not status.get("healthy"):
            raise HTTPException(status_code=503, detail="Model is still loading — try again shortly")
        # Refresh target URL after potential config change
        cfg = sm.load_config()
        target = sm.get_server_url(cfg)

    try:
        if client_wants_stream:
            from fastapi.responses import StreamingResponse

            async def _stream():
                async with httpx.AsyncClient(timeout=300) as _client:
                    async with _client.stream(
                        "POST", f"{target}/v1/chat/completions",
                        json=request, headers=req_headers,
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk

            return StreamingResponse(_stream(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{target}/v1/chat/completions",
                    json=request, headers=req_headers,
                )
                return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/v1/completions")
async def proxy_completions(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """Proxy for /v1/completions with the same auto model-switch behaviour as /v1/chat/completions."""
    import asyncio
    import httpx

    requested_model = request.get("model", "").strip()
    cfg_check = sm.load_config()
    auto_switch = cfg_check.get("auto_model_switch", False)
    needs_switch = bool(requested_model and auto_switch and _needs_hot_swap(requested_model))

    cfg = sm.load_config()
    target = sm.get_server_url(cfg)
    req_headers: dict[str, str] = {"Content-Type": "application/json"}
    key = cfg.get("api_key", "").strip()
    if key:
        req_headers["Authorization"] = f"Bearer {key}"

    if needs_switch:
        try:
            await asyncio.to_thread(_hot_swap_if_needed, requested_model)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Model switch failed: {exc}")
        cfg = sm.load_config()
        target = sm.get_server_url(cfg)

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{target}/v1/completions",
                json=request, headers=req_headers,
            )
            return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/auto_switch_enabled")
def auto_switch_status(_: None = Depends(_check_auth)) -> dict:
    """Return whether the auto model-switch feature is currently enabled."""
    cfg = sm.load_config()
    return {"enabled": cfg.get("auto_model_switch", False)}


@app.post("/auto_switch_enabled")
def set_auto_switch(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Enable or disable the auto model-switch feature.

    Args:
        data: Dict with key ``enabled`` (bool).
    """
    cfg = sm.load_config()
    cfg["auto_model_switch"] = bool(data.get("enabled", True))
    sm.save_config(cfg)
    return {"ok": True, "enabled": cfg["auto_model_switch"]}


# ── OpenAI-compatible pass-through proxy ─────────────────────────────────────
# All /v1/* paths that are not handled by more specific routes above (i.e.
# everything except POST /v1/chat/completions which has auto-switch logic) are
# proxied verbatim to the inference server.  This makes the dashboard proxy URL
# a drop-in replacement for the raw inference server URL — clients can call
# /v1/models, /v1/completions, /v1/embeddings, etc. without reconfiguration.
#
# No management-level authentication is required here; the inference server
# handles its own API key checking.  The inference server's api_key (if set)
# is forwarded automatically in the Authorization header.

from fastapi import Request
from fastapi.responses import Response as _FRsp


@app.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    include_in_schema=False,
)
async def proxy_v1_passthrough(path: str, request: Request) -> _FRsp:
    """Pass-through proxy for all /v1/* requests not handled by a specific route.

    Makes the dashboard proxy base URL fully OpenAI-compatible:
    clients can point at http://<host>:8502/v1 and use any standard endpoint.
    """
    import httpx

    cfg = sm.load_config()
    target = sm.get_server_url(cfg)

    # Forward the inference server API key if configured
    headers: dict[str, str] = {"Content-Type": request.headers.get("content-type", "application/json")}
    key = cfg.get("api_key", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.request(
                method=request.method,
                url=f"{target}/v1/{path}",
                headers=headers,
                content=body if body else None,
                params=dict(request.query_params),
            )
        # Filter out hop-by-hop headers that must not be forwarded
        excluded = {"transfer-encoding", "connection", "keep-alive", "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailers"}
        fwd_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}
        return _FRsp(
            content=resp.content,
            status_code=resp.status_code,
            headers=fwd_headers,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Inference server unreachable: {exc}")


# ── Quality benchmarks ────────────────────────────────────────────────────────

_quality_runs: dict[str, dict[str, Any]] = {}
_quality_lock = threading.Lock()


@app.post("/quality-benchmark/run")
def run_quality_benchmark_endpoint(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start a quality benchmark run. Returns run_id to poll for output/results."""
    import uuid
    suites = req.get("suites", ["gsm8k"])
    num_questions = int(req.get("num_questions", 20))
    label = req.get("label", "")
    server_url = sm.get_server_url()

    run_id = str(uuid.uuid4())[:8]
    stop_event = threading.Event()
    _quality_runs[run_id] = {"running": True, "lines": [], "results": None, "error": None, "stop_event": stop_event, "label": label}

    def _run() -> None:
        def _cb(line: str) -> None:
            _quality_runs[run_id]["lines"].append(line)

        try:
            results = qr.run_quality_benchmark(
                suites=suites,
                server_url=server_url,
                num_questions=num_questions,
                output_callback=_cb,
                stop_event=stop_event,
            )
            _quality_runs[run_id]["results"] = results
            # Persist to shared benchmark history so it appears in /benchmarks
            br.save_result({
                "model": results.get("model", ""),
                "model_id": results.get("model", ""),
                "timestamp": results.get("timestamp", ""),
                "benchmark_type": "quality",
                "suites": results.get("suites", {}),
                "overall_score": results.get("overall_score", 0.0),
                "success": True,
                "label": label,
            })
        except Exception as exc:
            _quality_runs[run_id]["error"] = str(exc)
            _cb(f"Error: {exc}\n")
        finally:
            _quality_runs[run_id]["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "run_id": run_id}


@app.get("/quality-benchmark/output/{run_id}")
def quality_benchmark_output(run_id: str, since: int = 0, _: None = Depends(_check_auth)) -> dict:
    """Return output lines since `since` index, plus running status and results when done."""
    if run_id not in _quality_runs:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    run = _quality_runs[run_id]
    lines = run["lines"][since:]
    return {
        "running": run["running"],
        "lines": lines,
        "results": run.get("results"),
        "error": run.get("error"),
        "total_lines": len(run["lines"]),
    }


@app.post("/quality-benchmark/stop/{run_id}")
def stop_quality_benchmark(run_id: str, _: None = Depends(_check_auth)) -> dict:
    """Set the stop flag on a running quality benchmark."""
    if run_id not in _quality_runs:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    stop_event = _quality_runs[run_id].get("stop_event")
    if stop_event:
        stop_event.set()
    _quality_runs[run_id]["running"] = False
    return {"ok": True}


import os as _os_mod
import signal as _signal_mod


@app.post("/shutdown")
def shutdown(_: None = Depends(_check_auth)) -> dict:
    """Terminate the vllm-mlx-ui process entirely."""
    import threading as _thr

    def _do_shutdown():
        import time as _t
        _t.sleep(0.3)
        try:
            from vllm_mlx.dashboard.server_manager import UI_PID_FILE
            pid = int(UI_PID_FILE.read_text().strip())
            _os_mod.kill(pid, _signal_mod.SIGTERM)
        except Exception:
            _os_mod.kill(_os_mod.getpid(), _signal_mod.SIGTERM)
    _thr.Thread(target=_do_shutdown, daemon=True).start()
    return {"ok": True}


@app.post("/restart")
def restart_app(_: None = Depends(_check_auth)) -> dict:
    """Restart the vllm-mlx-ui process (re-reads config, picks up code changes)."""
    import sys as _sys
    import threading as _thr
    import subprocess as _sp

    def _do_restart():
        import time as _t
        _t.sleep(0.5)
        try:
            log_path = _os_mod.environ.get("VMUI_LOG", str(sm.STATE_DIR / "mgmt.log"))
            # Must use -m flag to avoid relative import errors when re-spawning
            restart_cmd = [_sys.executable, "-m", "vllm_mlx.dashboard.mgmt_server"] + _sys.argv[1:]
            with open(_os_mod.devnull, "r") as devnull_in, open(log_path, "a") as log_out:
                _sp.Popen(
                    restart_cmd,
                    stdin=devnull_in,
                    stdout=log_out,
                    stderr=_sp.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
        except Exception:
            pass
        _os_mod.kill(_os_mod.getpid(), _signal_mod.SIGTERM)

    _thr.Thread(target=_do_restart, daemon=True).start()
    return {"ok": True}


@app.get("/updates")
def check_for_updates(force: bool = False, _: None = Depends(_check_auth)) -> dict:
    """Check for available updates to vllm-mlx-ui and key dependencies."""
    from vllm_mlx.dashboard import update_checker as _uc
    packages = _uc.check_updates(force=force)
    return {
        "packages": [
            {
                "name": p.name,
                "installed": p.installed,
                "latest": p.latest,
                "update_available": p.update_available,
                "url": p.url,
            }
            for p in packages
        ],
        "any_update": any(p.update_available for p in packages),
        "install_method": _uc._detect_install_method(),
    }


@app.post("/updates/install")
def install_updates_endpoint(_: None = Depends(_check_auth)) -> dict:
    """Start an upgrade and self-restart after it completes."""
    import sys as _sys
    import threading as _thr
    import subprocess as _sp
    from vllm_mlx.dashboard import update_checker as _uc
    cmd = _uc.upgrade_command()

    def _do_upgrade():
        import time as _t
        _uc.upgrade_status = "upgrading"
        try:
            _sp.run(cmd, timeout=300, check=False)
        except Exception:
            _uc.upgrade_status = "error:upgrade command failed"
            return
        # Bust cache so the next /updates check reflects newly installed versions
        _uc.bust_cache()
        _uc.upgrade_status = "restarting"
        _t.sleep(2)
        try:
            log_path = _os_mod.environ.get("VMUI_LOG", str(sm.STATE_DIR / "mgmt.log"))
            restart_cmd = [_sys.executable, "-m", "vllm_mlx.dashboard.mgmt_server"] + _sys.argv[1:]
            with open(_os_mod.devnull, "r") as devnull_in, open(log_path, "a") as log_out:
                _sp.Popen(
                    restart_cmd,
                    stdin=devnull_in,
                    stdout=log_out,
                    stderr=_sp.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
        except Exception:
            pass
        _os_mod.kill(_os_mod.getpid(), _signal_mod.SIGTERM)

    _thr.Thread(target=_do_upgrade, daemon=True).start()
    return {"ok": True, "message": "Upgrade started. The server will restart in ~30s."}


@app.get("/updates/install-status")
def install_status(_: None = Depends(_check_auth)) -> dict:
    """Return the current upgrade phase for frontend progress polling."""
    from vllm_mlx.dashboard import update_checker as _uc
    return {"status": _uc.upgrade_status}


@app.get("/network/interfaces")
def network_interfaces(_: None = Depends(_check_auth)) -> list:
    """Return all local network interfaces with friendly labels from networksetup."""
    import socket as _socket
    import subprocess as _sp

    _SKIP_PREFIXES = ("lo", "utun", "llw", "awdl", "anpi")

    # Build device → Hardware Port label map using networksetup
    device_label: dict[str, str] = {}
    try:
        ns_out = _sp.check_output(
            ["networksetup", "-listallhardwareports"],
            text=True, stderr=_sp.DEVNULL,
        )
        port_name = ""
        for line in ns_out.splitlines():
            line = line.strip()
            if line.startswith("Hardware Port:"):
                port_name = line.split(":", 1)[1].strip()
            elif line.startswith("Device:") and port_name:
                device = line.split(":", 1)[1].strip()
                device_label[device] = port_name
                port_name = ""
    except Exception:
        pass

    addrs: list[dict] = []
    seen: set[str] = set()

    for device, label in device_label.items():
        if any(device.startswith(p) for p in _SKIP_PREFIXES):
            continue
        try:
            ip = _sp.check_output(
                ["ipconfig", "getifaddr", device],
                text=True, stderr=_sp.DEVNULL,
            ).strip()
        except Exception:
            ip = ""
        if not ip or ip in seen:
            continue
        seen.add(ip)
        addrs.append({"ip": ip, "label": label})

    try:
        local_name = _socket.gethostname()
        if not local_name.endswith(".local"):
            local_name = local_name.split(".")[0] + ".local"
        addrs.append({"ip": local_name, "label": "mDNS (.local — works on same network)"})
    except Exception:
        pass

    return addrs


@app.get("/network/scan")
def network_scan(_: None = Depends(_check_auth)) -> list:
    """Scan the local subnet for other vllm-mlx-ui instances (port 8502).

    Returns a list of hosts that respond to /health within 0.5 s.
    The scan is limited to the first /24 of each active non-loopback IPv4
    interface so it completes in a few seconds even on large subnets.
    """
    import socket
    from concurrent.futures import ThreadPoolExecutor, as_completed

    MGMT_PORT = 8502
    TIMEOUT   = 0.5

    # Collect candidate /24 subnets from local interfaces
    subnets: set[str] = set()
    try:
        import subprocess as _sp
        out = _sp.check_output(["ifconfig"], text=True, stderr=_sp.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127." not in line:
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    try:
                        base = ".".join(ip.split(".")[:3])
                        subnets.add(base)
                    except Exception:
                        pass
    except Exception:
        pass

    if not subnets:
        return []

    # Build full candidate list (skip .0 and .255)
    candidates: list[str] = []
    own_ips: set[str] = set()
    try:
        own_ips = {r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None)}
    except Exception:
        pass

    for base in subnets:
        for i in range(1, 255):
            ip = f"{base}.{i}"
            if ip not in own_ips:
                candidates.append(ip)

    def _probe(ip: str) -> dict | None:
        try:
            with socket.create_connection((ip, MGMT_PORT), timeout=TIMEOUT) as sock:
                sock.sendall(b"GET /health HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
                data = sock.recv(256).decode(errors="ignore")
                if "200" in data:
                    name = ip
                    try:
                        name = socket.gethostbyaddr(ip)[0].split(".")[0]
                    except Exception:
                        pass
                    return {"ip": ip, "port": MGMT_PORT, "name": name}
        except Exception:
            pass
        return None

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = {pool.submit(_probe, ip): ip for ip in candidates}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                found.append(result)

    return found


# ── Vue UI static serving ─────────────────────────────────────────────────────
# Serve the built Vue UI from ui/dist/ at the root path.
# API routes (/status, /memory, etc.) take priority because they are registered
# first. The catch-all "/" route returns index.html for SPA client-side routing.

import os as _os
from fastapi.responses import PlainTextResponse

# Prefer the bundled ui_dist/ (pip-installed / Homebrew), fall back to dev repo ui/dist/
_UI_DIST_BUNDLED = _os.path.join(_os.path.dirname(__file__), "ui_dist")
_UI_DIST_DEV     = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "ui", "dist")
_UI_DIST = _UI_DIST_BUNDLED if _os.path.isdir(_UI_DIST_BUNDLED) else _UI_DIST_DEV

# Docs directory: bundled docs_dist/ or dev repo docs/
_DOCS_BUNDLED = _os.path.join(_os.path.dirname(__file__), "docs_dist")
_DOCS_DEV     = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "docs")
_DOCS_ROOT    = _DOCS_BUNDLED if _os.path.isdir(_DOCS_BUNDLED) else _DOCS_DEV


@app.get("/browse-directory")
def browse_directory(_: None = Depends(_check_auth)) -> dict:
    """Open a native macOS folder picker and return the selected path."""
    import subprocess as _sp
    script = 'POSIX path of (choose folder with prompt "Select directory")'
    try:
        result = _sp.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            path = result.stdout.strip().rstrip("/")
            return {"path": path}
        raise HTTPException(status_code=204, detail="No directory selected")
    except _sp.TimeoutExpired:
        raise HTTPException(status_code=408, detail="Folder dialog timed out")


@app.get("/api/docs/{doc_path:path}", include_in_schema=False)
async def _serve_doc(doc_path: str) -> PlainTextResponse:
    """Serve raw markdown files from the docs directory for the in-app docs viewer."""
    if not doc_path:
        doc_path = "index.md"
    # Security: prevent path traversal
    safe = _os.path.normpath(doc_path).lstrip("/")
    if ".." in safe:
        raise HTTPException(status_code=400, detail="Invalid path")
    full = _os.path.join(_DOCS_ROOT, safe)
    if not full.startswith(_os.path.realpath(_DOCS_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not _os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Doc not found")
    with open(full, encoding="utf-8") as fh:
        content = fh.read()
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


@app.get("/api/docs", include_in_schema=False)
async def _list_docs() -> dict:
    """Return a structured table of contents for the docs directory."""
    toc: dict[str, list[dict]] = {}
    if not _os.path.isdir(_DOCS_ROOT):
        return {"sections": []}
    for root, dirs, files in _os.walk(_DOCS_ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        rel_root = _os.path.relpath(root, _DOCS_ROOT)
        section = "." if rel_root == "." else rel_root
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            rel = _os.path.join("" if rel_root == "." else rel_root, fname)
            if section not in toc:
                toc[section] = []
            title = fname[:-3].replace("-", " ").replace("_", " ").title()
            if fname in ("index.md", "README.md"):
                title = "Overview"
            toc[section].append({"path": rel.replace("\\", "/"), "title": title})
    sections = [{"section": k, "items": v} for k, v in sorted(toc.items())]
    return {"sections": sections}


if _os.path.isdir(_UI_DIST):
    app.mount("/assets", StaticFiles(directory=_os.path.join(_UI_DIST, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_spa(full_path: str = "") -> FileResponse:
        # Don't intercept API paths — they're matched before this catch-all
        index = _os.path.join(_UI_DIST, "index.html")
        return FileResponse(index)


# ── Server startup ────────────────────────────────────────────────────────────

def start_mgmt_server(host: str = "0.0.0.0", port: int = 8502) -> None:
    """Start the management API server (blocking). Call from a daemon thread."""
    cfg = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    uvicorn.Server(cfg).run()


def start_mgmt_server_thread(host: str = "0.0.0.0", port: int = 8502) -> threading.Thread:
    """Start the management API server in a background daemon thread."""
    t = threading.Thread(target=start_mgmt_server, args=(host, port), daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="vllm-mlx management server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8502)
    args = parser.parse_args()
    start_mgmt_server(host=args.host, port=args.port)
