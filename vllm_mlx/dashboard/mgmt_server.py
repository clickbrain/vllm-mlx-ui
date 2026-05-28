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

import asyncio
import json as _json
import logging
import re
import threading
import time
from typing import Any

import httpx as _httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import benchmark_runner as br
from . import chat_store as cs
from . import llm_benchmark_cache as lbc
from . import model_manager as mm
from . import quality_runner as qr
from . import server_manager as sm
from . import __version__ as _dashboard_version

logger = logging.getLogger(__name__)

# ── Request metrics tracker ──────────────────────────────────────────────

_RECENT_REQUESTS: list[dict[str, Any]] = []
_RECENT_REQUESTS_LOCK = threading.Lock()
_MAX_RECENT = 200


def _record_request(
    start: float,
    ttft: float | None,
    duration: float,
    completion_tokens: int,
    model: str,
) -> None:
    with _RECENT_REQUESTS_LOCK:
        _RECENT_REQUESTS.append({
            "start": start,
            "ttft_ms": round(ttft * 1000, 1) if ttft is not None else None,
            "duration_ms": round(duration * 1000, 1),
            "completion_tokens": completion_tokens,
            "model": model,
            "ts": time.time(),
        })
        if len(_RECENT_REQUESTS) > _MAX_RECENT:
            _RECENT_REQUESTS[:] = _RECENT_REQUESTS[-_MAX_RECENT:]


def _get_live_metrics() -> dict[str, Any]:
    """Return rolling average TTFT / TPS from recent requests."""
    with _RECENT_REQUESTS_LOCK:
        recent = list(_RECENT_REQUESTS)
    cutoff = time.time() - 300
    window = [r for r in recent if r["ts"] > cutoff]

    ttfts = [r["ttft_ms"] for r in window if r["ttft_ms"] is not None]
    ttfts_sorted = sorted(ttfts)

    tps_vals: list[float] = []
    for r in window:
        d = r["duration_ms"] / 1000
        c = r["completion_tokens"]
        if d > 0 and c > 0:
            tps_vals.append(c / d)
    tps_sorted = sorted(tps_vals)

    return {
        "ttft_ms_avg": round(sum(ttfts_sorted) / len(ttfts_sorted), 1) if ttfts_sorted else None,
        "ttft_ms_p50": round(ttfts_sorted[len(ttfts_sorted) // 2], 1) if ttfts_sorted else None,
        "tps_avg": round(sum(tps_sorted) / len(tps_sorted), 2) if tps_sorted else None,
        "tps_p50": round(tps_sorted[len(tps_sorted) // 2], 2) if tps_sorted else None,
        "requests_window": len(window),
        "requests_total": len(recent),
        "ttft_ms_p95": (
            round(ttfts_sorted[int(len(ttfts_sorted) * 0.95)], 1) if len(ttfts_sorted) >= 20 else None
        ),
    }


_httpx_client: _httpx.AsyncClient | None = None
_warmup_http_client: _httpx.Client | None = None


def _get_httpx_client() -> _httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = _httpx.AsyncClient(
            limits=_httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=_httpx.Timeout(300.0, connect=10.0),
        )
    return _httpx_client


def _get_warmup_client() -> _httpx.Client:
    """Return a long-lived sync httpx.Client for warm-up requests."""
    global _warmup_http_client
    if _warmup_http_client is None:
        _warmup_http_client = _httpx.Client(timeout=30.0)
    return _warmup_http_client

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


# ── Background update scheduler ───────────────────────────────────────────────
# Warms the update cache once ~15 s after startup, then repeats hourly.
# This ensures /poll can return cached update state without ever blocking.
_update_scheduler_stop = threading.Event()
_update_scheduler_thread: threading.Thread | None = None


def _run_update_scheduler() -> None:
    """Thread target: check for updates after startup delay, then every hour."""
    # Brief startup delay so the server is fully ready before hitting the network.
    if _update_scheduler_stop.wait(15):
        return  # stop requested during startup delay
    while not _update_scheduler_stop.is_set():
        try:
            from vllm_mlx.dashboard.update_checker import check_updates
            check_updates(force=True)
        except Exception as exc:
            logger.warning("Background update check failed: %s", exc, exc_info=True)
        # Wait 1 hour (checking every 10 s so we can respond to stop quickly)
        for _ in range(360):
            if _update_scheduler_stop.wait(10):
                return


@app.on_event("startup")
def _start_background_scheduler() -> None:
    global _update_scheduler_thread
    _update_scheduler_stop.clear()
    t = threading.Thread(
        target=_run_update_scheduler,
        daemon=True,
        name="update-scheduler",
    )
    t.start()
    _update_scheduler_thread = t
    # Initialize chat history DB
    try:
        cs.init_db()
    except Exception as exc:
        logger.warning("chat_store.init_db failed: %s", exc, exc_info=True)
    # Start benchmark score cache
    try:
        lbc.start_background_refresh()
    except Exception as exc:
        logger.warning("llm_benchmark_cache start failed: %s", exc, exc_info=True)


@app.on_event("shutdown")
def _stop_background_tasks() -> None:
    # Stop the update scheduler
    _update_scheduler_stop.set()
    if _update_scheduler_thread is not None:
        _update_scheduler_thread.join(timeout=2)
    # Stop benchmark score cache refresh
    try:
        lbc.stop_background_refresh()
    except Exception as exc:
        logger.warning("llm_benchmark_cache stop failed: %s", exc, exc_info=True)
    # Signal running benchmarks to stop
    with _benchmark_lock:
        if _benchmark_stop_event is not None:
            _benchmark_stop_event.set()
    with _compare_lock:
        if _compare_stop_event is not None:
            _compare_stop_event.set()
    # Join tracked background threads so they can clean up
    for t in (_benchmark_thread, _compare_thread):
        if t is not None and t.is_alive():
            t.join(timeout=3)


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
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
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

    For the external API engine, this marks the server as healthy immediately
    without launching a local process.  All other engines start a subprocess.

    Raises:
        HTTPException: 400 if no model is configured.
        HTTPException: 409 if a lifecycle operation is already in progress.
    """
    if not _lifecycle_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A lifecycle operation is already in progress. Please wait.")
    try:
        config = sm.load_config()
        if not config.get("model") and not _is_external_api_engine():
            raise HTTPException(status_code=400, detail="No model selected. Set a model in config first.")
        if _is_external_api_engine():
            sm.set_server_healthy()
            return {"ok": True, "message": "External API is ready — remote endpoint will be used for inference"}
        ok, msg = sm.start_server(config)
        return {"ok": ok, "message": msg}
    finally:
        _lifecycle_lock.release()


@app.post("/stop")
def stop(_: None = Depends(_check_auth)) -> dict:
    """Send SIGTERM to the inference server and return stop status.

    For the external API engine this is a no-op — there is no local process.
    """
    if not _lifecycle_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A lifecycle operation is already in progress. Please wait.")
    try:
        if _is_external_api_engine():
            sm.set_server_stopped()
            return {"ok": True, "message": "External API disconnected"}
        ok, msg = sm.stop_server()
        return {"ok": ok, "message": msg}
    finally:
        _lifecycle_lock.release()


@app.get("/logs")
def logs(lines: int = 200, _: None = Depends(_check_auth)) -> dict:
    """Return the tail of the inference server log as a list of strings.

    Args:
        lines: Maximum number of trailing lines to return (default 200).
    """
    raw = sm.get_logs(lines)
    return {"lines": raw}


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

    Merges incoming data with the existing config so that partial updates
    (e.g. ``{"engine_id": "rapid-mlx"}``) don't overwrite other saved settings.

    Args:
        data: Config dict submitted by the client (may be partial).
    """
    from .server_manager import _LOCAL_ONLY_KEYS, load_config
    filtered = {k: v for k, v in data.items() if k not in _LOCAL_ONLY_KEYS}
    existing = load_config()
    merged = {**existing, **filtered}
    sm.save_config(merged)
    # Invalidate the engine cache if engine_id changed.
    if "engine_id" in filtered:
        _invalidate_external_engine_cache()
    return {"ok": True}


@app.get("/config/mgmt-key")
def get_mgmt_key(_: None = Depends(_check_auth)) -> dict:
    """Return the management API key (masked) so the UI can display it.

    Returns the first 8 characters followed by asterisks so the user can
    verify which key is active without exposing the full secret.
    """
    key = sm.load_config().get("mgmt_api_key", "").strip()
    if not key:
        return {"key_set": False, "masked": ""}
    visible = key[:8]
    masked = visible + "*" * max(0, len(key) - 8)
    return {"key_set": True, "masked": masked, "length": len(key)}


@app.post("/config/mgmt-key")
def set_mgmt_key(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Update the management API key."""
    new_key = str(data.get("key", "")).strip()
    cfg = sm.load_config()
    cfg["mgmt_api_key"] = new_key
    sm.save_config(cfg)
    # Invalidate auth key cache so next request picks up the new key
    _auth_key_cache["key"] = new_key
    return {"ok": True}


@app.post("/config/model-settings")
def set_model_settings(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Set per-model settings for a specific model.

    Expects: ``{"model_id": "...", "settings": {"trust_remote_code": true}}``
    Merges with any existing per-model settings for that model.
    """
    model_id = str(data.get("model_id", "")).strip()
    settings = data.get("settings", {})
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")
    cfg = sm.load_config()
    model_settings = dict(cfg.get("model_settings", {}))
    existing = dict(model_settings.get(model_id, {}))
    existing.update(settings)
    model_settings[model_id] = existing
    cfg["model_settings"] = model_settings
    sm.save_config(cfg)
    return {"ok": True}


@app.get("/config/model-settings/{model_id:path}")
def get_model_settings(model_id: str, _: None = Depends(_check_auth)) -> dict:
    """Return per-model settings for the given model (or empty dict)."""
    cfg = sm.load_config()
    return cfg.get("model_settings", {}).get(model_id, {})


# ── Models ────────────────────────────────────────────────────────────────────

@app.get("/models/cached")
def cached_models(_: None = Depends(_check_auth)) -> list:
    """Return all locally cached model repos, including engine-discovered models.

    Engine-discovered models (e.g. ds4-m5's auto-downloaded GGUF) are appended
    with ``source="engine"`` so the frontend can distinguish them from HF models.
    """
    models = mm.get_cached_models()
    try:
        from vllm_mlx.dashboard.engines.registry import ENGINES
        for engine in list(ENGINES.values()):
            try:
                discovered = engine.get_discovered_models()
                for m in discovered:
                    models.append({
                        "id": m["id"],
                        "name": m.get("display", m.get("name", m["id"])),
                        "size_gb": m.get("size_gb", 0),
                        "engine": engine.id,
                        "source": "engine",
                    })
            except Exception:
                logger.warning("Failed to discover models for engine %s", engine.id, exc_info=True)
    except Exception:
        logger.warning("Failed to query engine registry for models", exc_info=True)
    return models


@app.get("/models/gguf-files")
def gguf_files(_: None = Depends(_check_auth)) -> list:
    """Return all GGUF files found in the configured models directory.

    Scans the models directory (Settings → Models Directory) one level deep for
    ``*.gguf`` files.  Used by the llama.cpp engine settings panel to populate
    the model picker dropdown.
    """
    try:
        return mm.scan_gguf_files()
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return []


@app.get("/models/cache_size")
def cache_size(_: None = Depends(_check_auth)) -> dict:
    """Return the total size of the HuggingFace model cache in GB."""
    try:
        size_gb = mm.get_cache_total_size()
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
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
                logger.warning("Operation failed", exc_info=True)

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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/models/search")
def search_models(
    q: str = "",
    tags: str = "",
    limit: int = 30,
    offset: int = 0,
    sort: str = "downloads",
    direction: str = "desc",
    _: None = Depends(_check_auth),
) -> dict:
    """Search HuggingFace Hub for models. Pass tags=mlx for MLX-only results.

    direction: "asc" or "desc" (default "desc"). Controls sort order for
    server-side sort columns (downloads, likes, last_modified).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = mm.search_hf_models(
        query=q, tags=tag_list, limit=limit, offset=offset, sort=sort, direction=direction
    )
    # Slice the correctly-offset window from the overfetched results
    sliced = results[offset:offset + limit]
    return {
        "results": sliced,
        "offset": offset,
        "limit": limit,
        # has_more: true if the backend fetched more than offset+limit items
        "has_more": len(results) > offset + limit,
    }


class LoadModelRequest(BaseModel):
    model_id: str


def _model_family_from_id(model_id: str) -> str:
    """
    Infer model family keyword from the model_id string.
    Used as a fallback when HuggingFace metadata is unavailable (local GGUF,
    Ollama, ds4, or private models).  Strips engine prefixes (``ds4:``,
    ``ollama:``, etc.) before matching.
    """
    mid = model_id.lower()
    # Strip engine prefixes such as "ds4:deepseek-v4-flash" or "ollama:llama3.2"
    if ":" in mid:
        mid = mid.split(":", 1)[1]
    if "deepseek" in mid or mid.startswith("ds4"):
        return "deepseek"
    if "qwen3" in mid:
        return "qwen3"
    if "qwen" in mid:
        return "qwen2"
    if "llama" in mid:
        return "llama"
    if "mistral" in mid or "mixtral" in mid:
        return "mistral"
    if "gemma" in mid:
        return "gemma"
    if "phi" in mid:
        return "phi"
    if "claude" in mid:
        return "claude"
    return ""


def _is_reasoning_model(hint: str) -> bool:
    """Return True for models that generate extended chain-of-thought / thinking tokens."""
    return any(x in hint for x in ("deepseek", "r1", "thinking", "reasoner", "qwen3"))


def _compute_optimal_params(
    hint: str,
    task_mode: str,
    context_length: int,
    server_max_tokens: int,
    ram_gb: float,
) -> dict[str, Any]:
    """
    Compute optimal inference parameters for a model + task mode + hardware.

    ``hint``              lowercased string with model family keywords
    ``task_mode``         one of: chat / code / creative / analysis / precise
    ``context_length``    model's context window (from HF or 8192 fallback)
    ``server_max_tokens`` server's configured max_tokens ceiling
    ``ram_gb``            machine's total unified memory in GB

    Returns a dict of sampling parameters for the chat completion API.
    """
    reasoning = _is_reasoning_model(hint)

    # --- Per-model-family base sampling settings ---
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

    # --- Task-specific max output tokens (not the context window) ---
    # Reasoning models need more headroom for thinking tokens.
    if reasoning:
        task_caps = {"chat": 16384, "code": 16384, "creative": 16384, "analysis": 32768, "precise": 8192}
    else:
        task_caps = {"chat": 8192,  "code": 8192,  "creative": 8192,  "analysis": 16384, "precise": 1024}

    # On machines with < 16 GB RAM the model is likely smaller; cap output tokens
    # to avoid context pressure that would degrade generation quality.
    if ram_gb < 16:
        task_caps = {k: min(v, 4096) for k, v in task_caps.items()}
    elif ram_gb < 32:
        task_caps = {k: min(v, 8192) for k, v in task_caps.items()}

    mode = task_mode.lower()
    raw_cap = task_caps.get(mode, task_caps["chat"])
    # Honour the server's configured ceiling (never recommend more than the server allows)
    tokens = min(raw_cap, server_max_tokens, context_length)
    tokens = max(tokens, 512)  # always at least 512

    # --- Task-mode sampling overrides ---
    if mode == "code":
        base.update({"temperature": min(base["temperature"], 0.2), "top_p": 1.0, "top_k": 0, "repetition_penalty": 1.05})
    elif mode == "creative":
        base.update({"temperature": max(base["temperature"], 1.0), "top_p": 0.97, "top_k": 0, "repetition_penalty": 1.0})
    elif mode == "analysis":
        base.update({"temperature": max(min(base["temperature"], 0.5), 0.3), "top_p": 0.9, "top_k": 0, "repetition_penalty": 1.0})
    elif mode == "precise":
        base.update({"temperature": 0.0, "top_p": 1.0, "top_k": 1, "repetition_penalty": 1.0})
    # "chat" — model-family base used unchanged

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
    Recommendations account for: model family, task mode, machine RAM,
    engine type, and the server's configured max_tokens ceiling.
    """
    if not model_id.strip():
        raise HTTPException(status_code=400, detail="model_id is required")
    valid_modes = {"chat", "code", "creative", "analysis", "precise"}
    if task_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"task_mode must be one of {sorted(valid_modes)}")
    try:
        presets = mm.get_model_presets(model_id.strip())
    except Exception as exc:
        logger.warning("get_model_presets failed for %r: %s", model_id, exc)
        presets = {}

    # Build hint: prefer HF metadata, fall back to parsing the model_id string.
    # Including the model_id in hint means ds4:deepseek-v4-flash → "deepseek" family
    # even when HuggingFace lookup fails (GGUF, Ollama, offline, etc.).
    model_type = presets.get("model_type_hint", "").lower()
    arch = presets.get("architecture", "").lower()
    id_family = _model_family_from_id(model_id.strip())
    hint = (model_type + " " + arch + " " + id_family).strip()

    # Use the model's actual context window; fall back to a sensible default.
    context_length = presets.get("context_length") or presets.get("max_tokens") or 8192

    # Server's configured ceiling — never recommend more output tokens than this.
    try:
        cfg = sm.load_config()
        server_max_tokens = int(cfg.get("max_tokens") or cfg.get("max_request_tokens") or 32768)
    except Exception:
        server_max_tokens = 32768

    # Machine RAM for hardware-aware token caps.
    try:
        mem = sm.get_memory_stats()
        ram_gb = float(mem.get("total_gb", 16))
    except Exception:
        ram_gb = 16.0

    recommended = _compute_optimal_params(hint, task_mode, context_length, server_max_tokens, ram_gb)

    return {**presets, "recommended": recommended, "task_mode": task_mode,
            "model_family": id_family or hint.split()[0] if hint.strip() else "unknown",
            "ram_gb": round(ram_gb, 1)}


class _ModelScoresRequest(BaseModel):
    ids: list[str]


@app.post("/models/scores")
def model_scores(req: _ModelScoresRequest, _: None = Depends(_check_auth)) -> dict:
    """Return cached benchmark scores for a list of HF model IDs.

    Request body: ``{"ids": ["mlx-community/Qwen3-72B-4bit", ...]}``

    Each key in the response maps to either a benchmark scores dict or
    ``{"source": "none"}`` when no data is available.
    """
    if not req.ids:
        return {}
    try:
        return lbc.get_scores(req.ids)
    except Exception as exc:
        logger.warning("model_scores lookup failed: %s", exc, exc_info=True)
        return {hf_id: {"source": "none"} for hf_id in req.ids}



@app.post("/server/load")
def load_model(req: LoadModelRequest, _: None = Depends(_check_auth)) -> dict:
    """Update the configured model and start (or restart) the server.

    For the external API engine this just saves the model ID to config
    and marks the server as healthy — no local process is launched.
    """
    model_id = req.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    cfg = sm.load_config()

    if _is_external_api_engine():
        cfg["model"] = model_id
        sm.save_config(cfg)
        sm.set_server_healthy()
        return {"ok": True, "model": model_id, "restarted": False}

    was_running = sm.get_server_status().get("running", False)

    try:
        presets = mm.get_model_presets(model_id)
        if presets.get("max_tokens"):
            cfg["max_tokens"] = presets["max_tokens"]
            cfg["max_request_tokens"] = presets["max_tokens"]
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    cfg["model"] = model_id
    sm.save_config(cfg)

    if was_running:
        sm.stop_server()
        time.sleep(1)

    ok, msg = sm.start_server(cfg)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    # Schedule warmup in a background thread — start_server() is non-blocking
    # so the server is not healthy yet.  The thread polls until healthy, then
    # fires the warm-up request.
    import threading as _threading

    def _deferred_warmup() -> None:
        deadline = time.time() + 120
        while time.time() < deadline:
            if sm.get_server_status().get("healthy"):
                _fire_warmup()
                return
            time.sleep(2)
        logger.debug("Deferred warmup: server did not become healthy within 120 s")

    _threading.Thread(target=_deferred_warmup, daemon=True, name="deferred-warmup").start()

    return {"ok": True, "model": model_id, "restarted": True}


# ── Memory ────────────────────────────────────────────────────────────────────

@app.get("/memory/stats")
def memory_stats(_: None = Depends(_check_auth)) -> dict:
    """Return unified memory stats for this machine."""
    return sm.get_memory_stats()


@app.get("/live/metrics")
def live_metrics(_: None = Depends(_check_auth)) -> dict:
    """Rolling TTFT and TPS from recent proxy requests (last 5 min window)."""
    return _get_live_metrics()


@app.get("/poll")
def poll(_: None = Depends(_check_auth)) -> dict:
    """Batch endpoint: returns status, metrics, memory, config, and engine state in one call.

    Reduces 4 sequential API calls (every 3 s) into a single round-trip,
    cutting network overhead and CPU polling cost by ~75%.

    Also includes cached update state (``updates`` key) when the update cache
    is warm.  Returns ``null`` for ``updates`` when the cache is cold so the
    client knows no data is available yet — it should NOT make a blocking
    network call here; the background scheduler will warm the cache shortly.
    """
    server_state = sm._read_server_state() or {}

    # Include cached update state without any network calls.
    updates_payload = None
    try:
        from vllm_mlx.dashboard.update_checker import get_cached_updates
        cached = get_cached_updates()
        if cached is not None:
            updates_payload = [
                {
                    "name": r.name,
                    "installed": r.installed,
                    "latest": r.latest,
                    "update_available": r.update_available,
                    "url": r.url,
                    "release_url": r.release_url,
                }
                for r in cached
            ]
    except Exception as exc:
        logger.warning("Failed to read cached updates in /poll: %s", exc)

    return {
        "status": sm.get_server_status(),
        "metrics": sm.get_metrics() or {},
        "memory": sm.get_memory_stats(),
        "config": sm.load_config(),
        "runtime": {
            "engine_id": server_state.get("engine_id", "vllm-mlx"),
            "model": server_state.get("model", ""),
            "started_at": server_state.get("started_at"),
        },
        "live_metrics": _get_live_metrics(),
        "updates": updates_payload,
        "dashboard_version": _dashboard_version,
    }


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


@app.delete("/benchmarks")
def clear_all_benchmarks(_: None = Depends(_check_auth)) -> dict:
    """Delete all persisted benchmark results."""
    br.clear_all_results()
    return {"ok": True}


_benchmark_running = False
_benchmark_lock = threading.Lock()
_benchmark_stop_event: threading.Event | None = None
_benchmark_thread: threading.Thread | None = None

# Global lifecycle lock shared by start/stop, hot-swap, and engine compare.
# Prevents concurrent engine restarts from racing with each other.
_lifecycle_lock = threading.Lock()


@app.post("/benchmark/run")
def run_benchmark_endpoint(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start a benchmark run for one or more models in the background.
    Poll GET /benchmark/status to check progress, GET /benchmarks for results.
    """
    global _benchmark_running, _benchmark_stop_event, _benchmark_thread
    with _benchmark_lock:
        if _benchmark_running:
            return {"ok": False, "message": "A benchmark is already running"}
        _benchmark_running = True
        _benchmark_stop_event = threading.Event()

    model_ids: list[str] = req.get("model_ids", [])
    config: dict[str, Any] = req.get("config", {})
    runs = int(config.get("runs", 10))
    max_tokens = int(config.get("max_tokens", 256))
    label = req.get("label", "") or config.get("label", "")

    if not model_ids:
        with _benchmark_lock:
            _benchmark_running = False
        raise HTTPException(status_code=400, detail="model_ids is required")

    _SETTINGS_KEYS = (
        "kv_cache_quantization", "kv_cache_quantization_bits",
        "use_paged_cache", "continuous_batching",
        "gpu_memory_utilization", "enable_prefix_cache",
        "ssd_cache_dir", "ssd_cache_max_gb",
    )
    base_cfg = sm.load_config()
    server_settings_snapshot = {k: base_cfg.get(k) for k in _SETTINGS_KEYS if base_cfg.get(k) is not None}
    server_settings_snapshot["engine_id"] = base_cfg.get("engine_id", "vllm-mlx")

    _stop = _benchmark_stop_event

    def _run() -> None:
        global _benchmark_running
        try:
            running_model = sm.load_config().get("model", "")
            server_running = sm.get_server_status().get("running", False)
            server_url = sm.get_server_url()
            for model_id in model_ids:
                if _stop.is_set():
                    break
                if server_running and running_model and running_model == model_id:
                    br.run_live_benchmark(
                        model_id,
                        server_url=server_url,
                        prompts=runs,
                        max_tokens=max_tokens,
                        label=label,
                        stop_event=_stop,
                        server_settings=server_settings_snapshot,
                    )
                else:
                    br.run_benchmark(model_id, prompts=runs, max_tokens=max_tokens)
        finally:
            with _benchmark_lock:
                _benchmark_running = False

    _t = threading.Thread(target=_run, daemon=True, name="benchmark")
    with _benchmark_lock:
        _benchmark_thread = _t
    _t.start()
    return {"ok": True, "message": f"Benchmark started for {len(model_ids)} model(s)"}


@app.post("/benchmark/stop")
def stop_benchmark_endpoint(_: None = Depends(_check_auth)) -> dict:
    """Signal the running speed benchmark to stop (sets running flag to False)."""
    global _benchmark_running, _benchmark_stop_event
    with _benchmark_lock:
        _benchmark_running = False
        if _benchmark_stop_event:
            _benchmark_stop_event.set()
    return {"ok": True}


@app.get("/benchmark/status")
def benchmark_status(_: None = Depends(_check_auth)) -> dict:
    """Return whether a benchmark run is currently in progress."""
    return {"running": _benchmark_running}


# ── Engine comparison benchmark ───────────────────────────────────────────────

_compare_running = False
_compare_lock = threading.Lock()
_compare_results: list[dict] = []
_compare_stop_event: threading.Event | None = None
_compare_thread: threading.Thread | None = None


@app.post("/benchmark/compare")
def run_engine_compare(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start an engine comparison benchmark (background job).

    Sequentially tests the same model on multiple engines, each time:
    1. Stop the current server (lifecycle-locked)
    2. Update engine_id + apply engine-specific settings
    3. Start the server
    4. Run the benchmark
    5. Collect results

    Request body::

        {
          "model_id": "mlx-community/Qwen3-8B-4bit",
          "engine_ids": ["vllm-mlx", "rapid-mlx"],
          "runs": 10,
          "max_tokens": 256
        }

    Raises:
        409: if a lifecycle operation or compare is already running
        409: if active proxied requests are in-flight (would be disrupted)
    """
    global _compare_running, _compare_stop_event, _compare_results, _compare_thread
    if not _lifecycle_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A lifecycle operation is already in progress.")
    _lifecycle_lock.release()  # released immediately — compare manages its own sub-lifecycle

    with _compare_lock:
        if _compare_running:
            raise HTTPException(status_code=409, detail="An engine comparison is already running.")
        _compare_running = True
        _compare_results = []
        _compare_stop_event = threading.Event()

    model_id: str = req.get("model_id", "")
    engine_ids: list[str] = req.get("engine_ids", [])
    runs = int(req.get("runs", 10))
    max_tokens = int(req.get("max_tokens", 256))

    if not model_id:
        with _compare_lock:
            _compare_running = False
        raise HTTPException(status_code=400, detail="model_id is required")
    if len(engine_ids) < 2:
        with _compare_lock:
            _compare_running = False
        raise HTTPException(status_code=400, detail="At least 2 engine_ids required for comparison")

    _stop = _compare_stop_event

    def _run_compare() -> None:
        global _compare_running
        try:
            for eid in engine_ids:
                if _stop.is_set():
                    break
                with _lifecycle_lock:
                    # Stop running server if any
                    status = sm.get_server_status()
                    if status.get("running"):
                        sm.stop_server()

                    # Switch engine and start
                    cfg = sm.load_config()
                    cfg["engine_id"] = eid
                    cfg["model"] = model_id
                    sm.save_config(cfg)
                    ok, msg = sm.start_server(cfg)
                    if not ok:
                        logger.warning("Compare: could not start engine %s: %s", eid, msg)
                        _compare_results.append({
                            "engine_id": eid, "model_id": model_id,
                            "error": msg, "runs": 0,
                        })
                        continue

                    # Wait for server to become healthy (up to 120 s)
                    import urllib.request as _ur
                    server_url = sm.get_server_url(cfg)
                    for _ in range(120):
                        if _stop.is_set():
                            break
                        try:
                            _ur.urlopen(f"{server_url}/health", timeout=1).read()
                            break
                        except Exception:
                            time.sleep(1)
                    else:
                        logger.warning("Compare: engine %s did not become healthy", eid)
                        _compare_results.append({
                            "engine_id": eid, "model_id": model_id,
                            "error": "Engine did not become healthy within 120 s", "runs": 0,
                        })
                        continue

                # Lifecycle lock released — run benchmark outside lock to allow stop
                if not _stop.is_set():
                    result = br.run_live_benchmark(
                        model_id,
                        server_url=sm.get_server_url(cfg),
                        prompts=runs,
                        max_tokens=max_tokens,
                        label=f"compare:{eid}",
                        stop_event=_stop,
                        server_settings={"engine_id": eid},
                    )
                    if result:
                        result["engine_id"] = eid
                        _compare_results.append(result)
        except Exception as e:
            logger.warning("Engine compare failed: %s", e, exc_info=True)
        finally:
            with _compare_lock:
                _compare_running = False

    _ct = threading.Thread(target=_run_compare, daemon=True, name="compare-benchmark")
    with _compare_lock:
        _compare_thread = _ct
    _ct.start()
    return {"ok": True, "message": f"Engine comparison started for {len(engine_ids)} engines"}


@app.post("/benchmark/compare/stop")
def stop_compare_endpoint(_: None = Depends(_check_auth)) -> dict:
    """Stop the running engine comparison."""
    global _compare_stop_event
    with _compare_lock:
        if _compare_stop_event:
            _compare_stop_event.set()
    return {"ok": True}


@app.get("/benchmark/compare/status")
def compare_status(_: None = Depends(_check_auth)) -> dict:
    """Return engine comparison progress and partial results."""
    return {
        "running": _compare_running,
        "results": list(_compare_results),
    }


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

    # Estimate monthly savings assuming current benchmark usage is representative
    # of a typical daily workload. This is an approximation — the raw cloud cost
    # is the more reliable figure for per-benchmark comparisons.
    benchmarks_analyzed = len([r for r in results if r.get("success", True)])
    if benchmarks_analyzed > 0:
        avg_cost_per_run = total_cost / benchmarks_analyzed
        estimated_monthly_savings = round(avg_cost_per_run * 30, 2)
    else:
        estimated_monthly_savings = 0.0

    return {
        "benchmarks_analyzed": benchmarks_analyzed,
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
            logger.warning("Operation failed", exc_info=True)

        cfg["model"] = requested_model
        # Acquire lifecycle lock so manual start/stop/compare don't race the swap
        _lifecycle_lock.acquire(blocking=True)
        try:
            sm.stop_server()
            time.sleep(2)
            sm.start_server(cfg)
        finally:
            _lifecycle_lock.release()

        # Wait up to 120 s for the server to become healthy
        for _ in range(60):
            time.sleep(2)
            status = sm.get_server_status()
            if status.get("healthy"):
                break

        _fire_warmup()


def _fire_warmup() -> None:
    """Send a minimal warm-up request to the inference server (fire-and-forget).

    After a model is swapped in or loaded, this primes the KV cache / GPU
    pipeline so the first real user request sees normal latency instead of
    cold-start jitter.  Runs synchronously in the caller's thread.

    Skipped for the external API engine — there is no local server to warm.
    """
    if _is_external_api_engine():
        return
    try:
        cfg = sm.load_config()
        port = cfg.get("port", 8080)
        host = cfg.get("host", "127.0.0.1")
        if not sm.get_server_status().get("healthy"):
            return
        _get_warmup_client().post(
            f"http://{host}:{port}/v1/chat/completions",
            json={
                "model": cfg.get("model", ""),
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "stream": False,
            },
        )
    except Exception:
        logger.debug("Warm-up request failed (non-critical)", exc_info=True)


import time as _time_mod

# Cache for _is_external_api_engine(): avoid reading config.json on every
# proxy request (which is the hot path for /v1/chat/completions).
_external_engine_cache: tuple[float, bool] | None = None
_EXTERNAL_ENGINE_CACHE_TTL = 2.0  # seconds


def _is_external_api_engine() -> bool:
    """Return True when the current engine is the remote API proxy engine.

    Result is cached for 2 seconds to avoid config file reads on every proxy
    request — the engine_id rarely changes between requests.
    """
    global _external_engine_cache
    import time as _t
    now = _t.monotonic()
    if _external_engine_cache is not None:
        ts, result = _external_engine_cache
        if now - ts < _EXTERNAL_ENGINE_CACHE_TTL:
            return result
    cfg = sm.load_config()
    result = cfg.get("engine_id", "").strip() == "openai-compatible"
    _external_engine_cache = (now, result)
    return result


def _invalidate_external_engine_cache() -> None:
    """Invalidate the engine cache — call after engine_id changes in config."""
    global _external_engine_cache
    _external_engine_cache = None


def _get_external_target(cfg: dict[str, Any]) -> str | None:
    """Return the remote API base URL from engine_settings, or None."""
    es = cfg.get("engine_settings", {}).get("openai-compatible", {})
    return (es.get("base_url") or "").strip() or None


def _get_external_api_key(cfg: dict[str, Any]) -> str:
    """Return the API key for the external engine."""
    es = cfg.get("engine_settings", {}).get("openai-compatible", {})
    return (es.get("api_key") or "").strip()


def _get_external_models(cfg: dict[str, Any]) -> list[str]:
    """Return enabled model IDs for the external API engine."""
    es = cfg.get("engine_settings", {}).get("openai-compatible", {})
    raw = (es.get("models") or "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] if raw else []


def _needs_hot_swap(requested_model: str, cfg: dict[str, Any] | None = None) -> bool:
    """Return True if requested_model differs from the currently loaded model
    and is available in the local cache or (for external API) in the enabled
    models list.  Does NOT acquire _swap_lock.

    Args:
        requested_model: The model ID requested by the client.
        cfg: Optional pre-loaded config dict. If None, loaded from disk.
    """
    if not requested_model:
        return False
    if cfg is None:
        cfg = sm.load_config()
    if cfg.get("model", "").strip() == requested_model:
        return False
    # External API: check against enabled models list
    if _is_external_api_engine():
        return requested_model in _get_external_models(cfg)
    # Local engine: check HF cache
    if not _HF_REPO_RE.match(requested_model):
        return False
    cached_ids = {m["id"] for m in mm.get_cached_models()}
    return requested_model in cached_ids


def _sse_delta(content: str) -> str:
    """Format a single assistant content delta as an SSE data line."""
    payload = {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
    }
    return f"data: {_json.dumps(payload)}\n\n"


@app.post("/v1/chat/completions")
async def proxy_chat(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """
    Proxy for /v1/chat/completions.

    Auto model-switch behaviour (when auto_model_switch is enabled):
      • stream:true  — immediately opens SSE with heartbeats during the swap,
                       then streams the real reply.
      • stream:false — waits for the swap to complete (up to 120 s), then returns
                       a plain JSON response.

    For requests that do NOT require a model switch the proxy passes through
    verbatim, respecting the client's stream preference.
    """
    requested_model = request.get("model", "").strip()
    cfg = sm.load_config()
    auto_switch = cfg.get("auto_model_switch", False)
    needs_switch = bool(requested_model and auto_switch and _needs_hot_swap(requested_model, cfg))
    client_wants_stream = bool(request.get("stream"))

    # External API engine: route to configured remote URL
    if _is_external_api_engine():
        base = _get_external_target(cfg)
        if not base:
            raise HTTPException(status_code=400, detail="External API engine is enabled but no base URL configured")
        target = base.rstrip("/")
        ext_key = _get_external_api_key(cfg)
        req_headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if ext_key:
            req_headers["Authorization"] = f"Bearer {ext_key}"
    else:
        target = sm.get_server_url(cfg)
        req_headers: dict[str, str] = {"Content-Type": "application/json"}
        key = cfg.get("api_key", "").strip()
        if key:
            req_headers["Authorization"] = f"Bearer {key}"

    # ds4-server counts thinking tokens against max_tokens, so the default
    # ChatView value of 2048 is far too small — the thinking section alone
    # often exceeds 2048 tokens, leaving nothing for the answer.  Boost
    # max_tokens to match the engine's configured limit unless the client
    # has already set a sufficiently large value.
    if cfg.get("engine_id") == "ds4-m5":
        max_out = int(cfg.get("engine_settings", {}).get("ds4-m5", {}).get("max_output_tokens", 65536))
        if int(request.get("max_tokens", 0) or 0) < max_out:
            request = {**request, "max_tokens": max_out}

    if needs_switch:
        if _is_external_api_engine():
            # External API: no local process to swap — just update config model
            cfg["model"] = requested_model
            sm.save_config(cfg)
        elif client_wants_stream:
            # ── Streaming model-switch path ──────────────────────────────────
            # Push notification immediately, then stream the real reply.
            from fastapi.responses import StreamingResponse

            async def _switch_and_stream():
                # Send a keep-alive SSE comment immediately so the connection
                # doesn't stall while the model loads.  Using a comment (": ...")
                # keeps the stream open without injecting text into the chat reply.
                yield f": switching-to {requested_model}\n\n"

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
                    yield _sse_delta(f"❌ Model switch failed: {swap_error[0]}")
                    yield "data: [DONE]\n\n"
                    return

                cfg2 = sm.load_config()
                target2 = sm.get_server_url(cfg2)
                req2 = {**request, "stream": True}

                try:
                    start = time.time()
                    first_byte = None
                    completion_tokens = 0
                    model = requested_model or cfg2.get("model", "")
                    async with _get_httpx_client().stream(
                        "POST", f"{target2}/v1/chat/completions",
                        timeout=300, json=req2, headers=req_headers,
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            if first_byte is None:
                                first_byte = time.time()
                            decoded = chunk.decode("utf-8", errors="replace")
                            if '"usage"' in decoded and '"completion_tokens"' in decoded:
                                for line in decoded.split("\n"):
                                    if line.startswith("data: ") and line != "data: [DONE]":
                                        try:
                                            payload = _json.loads(line[6:])
                                            usage = payload.get("usage") or {}
                                            completion_tokens = usage.get("completion_tokens", 0)
                                            model = payload.get("model", model)
                                        except _json.JSONDecodeError:
                                            pass
                            yield chunk
                    duration = time.time() - start
                    ttft = (first_byte - start) if first_byte else None
                    _record_request(start, ttft, duration, completion_tokens, model)
                except Exception as exc:
                    yield _sse_delta(f"❌ Request failed after model switch: {exc}")
                    yield "data: [DONE]\n\n"

            return StreamingResponse(_switch_and_stream(), media_type="text/event-stream")

        else:
            # ── Non-streaming model-switch path ──────────────────────────────
            # Block until the swap completes, then return a regular JSON response.
            # The client times out only if the model takes > 120 s to load.
            try:
                await asyncio.to_thread(_hot_swap_if_needed, requested_model)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"Model switch failed: {exc}") from exc

            cfg2 = sm.load_config()
            target2 = sm.get_server_url(cfg2)
            try:
                resp = await _get_httpx_client().post(
                    f"{target2}/v1/chat/completions",
                    timeout=300, json=request, headers=req_headers,
                )
                return resp.json()
            except Exception as exc:
                logger.warning("Non-streaming request to inference server failed: %s", exc, exc_info=True)
                raise HTTPException(status_code=502, detail="Inference server request failed") from exc

    # ── Normal path (no model switch needed) ────────────────────────────────
    # If the inference server is currently starting up (model loading from a
    # dashboard-initiated switch), wait for it to become healthy before forwarding.
    # Skip this for external API — there is no local server.
    if not _is_external_api_engine():
        status = sm.get_server_status()
        if status.get("running") and not status.get("healthy"):
            for _ in range(60):
                await asyncio.sleep(2)
                status = sm.get_server_status()
                if status.get("healthy"):
                    break
            if not status.get("healthy"):
                raise HTTPException(status_code=503, detail="Model is still loading — try again shortly")
            cfg = sm.load_config()
            target = sm.get_server_url(cfg)

    try:
        if client_wants_stream:
            from fastapi.responses import StreamingResponse

            async def _stream():
                start = time.time()
                first_byte = None
                completion_tokens = 0
                model = requested_model or cfg.get("model", "")

                client = _get_httpx_client()
                async with client.stream(
                    "POST", f"{target}/v1/chat/completions",
                    timeout=300, json=request, headers=req_headers,
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        if first_byte is None:
                            first_byte = time.time()
                        # Parse usage from the final data chunk
                        decoded = chunk.decode("utf-8", errors="replace")
                        if '"usage"' in decoded and '"completion_tokens"' in decoded:
                            for line in decoded.split("\n"):
                                if line.startswith("data: ") and line != "data: [DONE]":
                                    try:
                                        payload = _json.loads(line[6:])
                                        usage = payload.get("usage") or {}
                                        completion_tokens = usage.get("completion_tokens", 0)
                                        model = payload.get("model", model)
                                    except _json.JSONDecodeError:
                                        pass
                        yield chunk

                duration = time.time() - start
                ttft = (first_byte - start) if first_byte else None
                _record_request(start, ttft, duration, completion_tokens, model)

            return StreamingResponse(_stream(), media_type="text/event-stream")
        else:
            start = time.time()
            resp = await _get_httpx_client().post(
                f"{target}/v1/chat/completions",
                timeout=300, json=request, headers=req_headers,
            )
            data = resp.json()
            dur = time.time() - start
            ct = (data.get("usage") or {}).get("completion_tokens", 0)
            m = data.get("model", requested_model or cfg.get("model", ""))
            _record_request(start, None, dur, ct, m)
            return data
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/completions")
async def proxy_completions(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """Proxy for /v1/completions with the same auto model-switch behaviour as /v1/chat/completions."""
    requested_model = request.get("model", "").strip()
    cfg = sm.load_config()
    auto_switch = cfg.get("auto_model_switch", False)
    needs_switch = bool(requested_model and auto_switch and _needs_hot_swap(requested_model, cfg))

    if _is_external_api_engine():
        base = _get_external_target(cfg)
        if not base:
            raise HTTPException(status_code=400, detail="External API engine is enabled but no base URL configured")
        target = base.rstrip("/")
        ext_key = _get_external_api_key(cfg)
        req_headers: dict[str, str] = {"Content-Type": "application/json"}
        if ext_key:
            req_headers["Authorization"] = f"Bearer {ext_key}"
    else:
        target = sm.get_server_url(cfg)
        req_headers: dict[str, str] = {"Content-Type": "application/json"}
        key = cfg.get("api_key", "").strip()
        if key:
            req_headers["Authorization"] = f"Bearer {key}"

    if needs_switch:
        if _is_external_api_engine():
            cfg["model"] = requested_model
            sm.save_config(cfg)
        else:
            try:
                await asyncio.to_thread(_hot_swap_if_needed, requested_model)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"Model switch failed: {exc}") from exc
            cfg = sm.load_config()
            target = sm.get_server_url(cfg)

    try:
        resp = await _get_httpx_client().post(
            f"{target}/v1/completions",
            timeout=300, json=request, headers=req_headers,
        )
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
    if "enabled" in data:
        cfg["auto_model_switch"] = bool(data["enabled"])
    sm.save_config(cfg)
    return {"ok": True, "enabled": cfg.get("auto_model_switch", False)}


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
    cfg = sm.load_config()

    if _is_external_api_engine():
        base = _get_external_target(cfg)
        if not base:
            raise HTTPException(status_code=400, detail="External API engine is enabled but no base URL configured")
        target = base.rstrip("/")
        headers: dict[str, str] = {"Content-Type": request.headers.get("content-type", "application/json")}
        ext_key = _get_external_api_key(cfg)
        if ext_key:
            headers["Authorization"] = f"Bearer {ext_key}"
    else:
        target = sm.get_server_url(cfg)
        headers: dict[str, str] = {"Content-Type": request.headers.get("content-type", "application/json")}
        key = cfg.get("api_key", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"

    body = await request.body()

    try:
        resp = await _get_httpx_client().request(
            request.method, f"{target}/v1/{path}",
            timeout=120, headers=headers,
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
        raise HTTPException(status_code=502, detail=f"Inference server unreachable: {exc}") from exc


# ── Quality benchmarks ────────────────────────────────────────────────────────

_quality_runs: dict[str, dict[str, Any]] = {}
_quality_lock = threading.Lock()


def _prune_quality_runs() -> None:
    """Remove completed quality benchmark runs older than 30 minutes to prevent unbounded dict growth."""
    cutoff = time.time() - 1800
    stale = [k for k, v in _quality_runs.items() if not v.get("running") and v.get("ts", 0) < cutoff]
    for k in stale:
        _quality_runs.pop(k, None)


@app.post("/quality-benchmark/run")
def run_quality_benchmark_endpoint(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start a quality benchmark run. Returns run_id to poll for output/results.

    Accepts optional ``model_ids`` list. When multiple models are requested the
    server switches models sequentially, restoring the original model when done.
    """
    import uuid
    suites = req.get("suites", ["gsm8k"])
    num_questions = int(req.get("num_questions", 20))
    label = req.get("label", "")
    model_ids: list[str] = req.get("model_ids", [])
    server_url = sm.get_server_url()

    run_id = str(uuid.uuid4())[:8]
    stop_event = threading.Event()
    _prune_quality_runs()
    _quality_runs[run_id] = {
        "running": True, "lines": [], "results": None,
        "all_results": [], "error": None, "stop_event": stop_event, "label": label,
        "ts": time.time(),
    }

    def _run() -> None:
        import time as _t

        def _cb(line: str) -> None:
            _quality_runs[run_id]["lines"].append(line)

        original_model = sm.load_config().get("model", "")
        targets = model_ids if model_ids else ([original_model] if original_model else [])
        all_results: list[dict] = []
        switched = False

        try:
            for target_model in targets:
                if stop_event.is_set():
                    break

                current_model = sm.load_config().get("model", "")
                if target_model and target_model != current_model:
                    _cb(f"\n── Switching to {target_model} ──\n")
                    cfg = sm.load_config()
                    cfg["model"] = target_model
                    sm.save_config(cfg)
                    stop_ok, stop_msg = sm.stop_server()
                    if not stop_ok:
                        _cb(f"[⚠ stop_server: {stop_msg}]\n")
                    ok, msg = sm.start_server(cfg)
                    if not ok:
                        _cb(f"[✗ Could not start {target_model}: {msg}]\n")
                        continue
                    switched = True
                    # Wait up to 120 s for the inference port to accept requests.
                    # sm.get_server_status() only checks if the process is alive —
                    # the model may still be loading. Poll /v1/models instead.
                    ready = False
                    port = int(sm.load_config().get("port", 8000))
                    host_addr = sm.load_config().get("host", "127.0.0.1")
                    if host_addr == "0.0.0.0":
                        host_addr = "127.0.0.1"
                    health_url = f"http://{host_addr}:{port}/v1/models"
                    import requests as _req_mod
                    for _ in range(240):
                        if stop_event.is_set():
                            break
                        _t.sleep(0.5)
                        try:
                            r = _req_mod.get(health_url, timeout=2)
                            if r.status_code == 200:
                                ready = True
                                break
                        except Exception:
                            logger.debug("Waiting for model server at %s (not ready yet)", health_url)
                        _cb(f"[✗ Timeout waiting for {target_model} to start]\n")
                        continue
                    _cb(f"[✓ {target_model} ready]\n")

                if len(targets) > 1:
                    _cb(f"\n{'─' * 40}\nModel: {target_model or 'current model'}\n{'─' * 40}\n")

                results = qr.run_quality_benchmark(
                    suites=suites,
                    server_url=server_url,
                    num_questions=num_questions,
                    output_callback=_cb,
                    stop_event=stop_event,
                )
                all_results.append(results)
                overall_speed = results.get("overall_speed", {})
                br.save_result({
                    "model": results.get("model", target_model),
                    "model_id": results.get("model", target_model),
                    "timestamp": results.get("timestamp", ""),
                    "benchmark_type": "quality",
                    "suites": results.get("suites", {}),
                    "overall_score": results.get("overall_score", 0.0),
                    "overall_speed": overall_speed,
                    "avg_tps": overall_speed.get("avg_tokens_per_sec"),
                    "avg_ttft_ms": overall_speed.get("avg_ttft_ms"),
                    "success": True,
                    "label": label,
                })

        except Exception as exc:
            _quality_runs[run_id]["error"] = str(exc)
            _cb(f"Error: {exc}\n")
        finally:
            # Always restore original model if we switched away
            if switched and original_model and sm.load_config().get("model", "") != original_model:
                _cb(f"\n── Restoring {original_model} ──\n")
                cfg = sm.load_config()
                cfg["model"] = original_model
                sm.save_config(cfg)
                sm.stop_server()
                sm.start_server(cfg)
            _quality_runs[run_id]["results"] = all_results[-1] if all_results else None
            _quality_runs[run_id]["all_results"] = all_results
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


# ── Custom benchmarks ─────────────────────────────────────────────────────────

_custom_runs: dict[str, dict[str, Any]] = {}
_custom_lock = threading.Lock()


def _prune_custom_runs() -> None:
    """Remove completed custom benchmark runs older than 30 minutes to prevent unbounded dict growth."""
    cutoff = time.time() - 1800
    stale = [k for k, v in _custom_runs.items() if not v.get("running") and v.get("ts", 0) < cutoff]
    for k in stale:
        _custom_runs.pop(k, None)


@app.post("/custom-benchmark/run")
def run_custom_benchmark_endpoint(req: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    """Start a custom-prompt benchmark run. Returns run_id to poll for output/results."""
    import uuid
    prompts: list[str] = req.get("prompts", [])
    if not prompts:
        raise HTTPException(status_code=400, detail="No prompts provided")
    label = req.get("label", "")
    max_tokens = int(req.get("max_tokens", 512))
    model_ids: list[str] = req.get("model_ids", [])

    model_id = sm.load_config().get("model", "") if not model_ids else model_ids[0]
    run_id = str(uuid.uuid4())
    enable_thinking: bool = bool(req.get("enable_thinking", False))

    stop_event = threading.Event()
    _prune_custom_runs()
    run_state: dict[str, Any] = {
        "running": True,
        "lines": [],
        "results": None,
        "all_results": [],
        "error": None,
        "stop_event": stop_event,
        "ts": time.time(),
    }
    with _custom_lock:
        _custom_runs[run_id] = run_state

    def _cb(text: str) -> None:
        with _custom_lock:
            _custom_runs[run_id]["lines"].append(text)

    def _run() -> None:
        from vllm_mlx.dashboard import __version__ as _dash_ver
        from vllm_mlx.dashboard import benchmark_runner as br
        all_results: list[dict[str, Any]] = []
        models_to_run = model_ids if model_ids else [model_id]
        original_model = sm.load_config().get("model", "")
        switched = False

        # Snapshot server settings at the time the benchmark starts so each
        # saved result carries the exact config used (KV cache, batching, etc.)
        _SETTINGS_KEYS = (
            "kv_cache_quantization", "kv_cache_quantization_bits",
            "use_paged_cache", "continuous_batching",
            "gpu_memory_utilization", "enable_prefix_cache",
            "ssd_cache_dir", "ssd_cache_max_gb",
        )
        base_cfg = sm.load_config()
        server_settings_snapshot = {k: base_cfg.get(k) for k in _SETTINGS_KEYS if base_cfg.get(k) is not None}
        server_settings_snapshot["engine_id"] = base_cfg.get("engine_id", "vllm-mlx")

        try:
            for mid in models_to_run:
                if stop_event.is_set():
                    break
                current_model = sm.load_config().get("model", "")
                if current_model != mid:
                    _cb(f"\n── Loading {mid} ──\n")
                    cfg = sm.load_config()
                    cfg["model"] = mid
                    sm.save_config(cfg)
                    sm.stop_server()
                    sm.start_server(cfg)
                    switched = True
                    import time as _t
                    server_url_inner = f"http://127.0.0.1:{cfg.get('port', 8000)}"
                    for _ in range(120):
                        if stop_event.is_set():
                            break
                        try:
                            import requests as _req
                            r = _req.get(f"{server_url_inner}/v1/models", timeout=2)
                            if r.status_code == 200:
                                break
                        except Exception:
                            logger.debug("Waiting for model server at %s (not ready yet)", server_url_inner)

                server_url = f"http://127.0.0.1:{sm.load_config().get('port', 8000)}"
                _cb(f"\n── Running custom benchmark: {mid} ──\n")
                res = br.run_custom_benchmark(
                    model_id=mid,
                    custom_prompts=prompts,
                    server_url=server_url,
                    max_tokens=max_tokens,
                    output_callback=_cb,
                    label=label,
                    stop_event=stop_event,
                    enable_thinking=enable_thinking,
                    server_settings=server_settings_snapshot,
                    dashboard_version=_dash_ver,
                )
                all_results.append(res)
        except Exception as exc:
            with _custom_lock:
                _custom_runs[run_id]["error"] = str(exc)
        finally:
            if switched and original_model and sm.load_config().get("model", "") != original_model:
                _cb(f"\n── Restoring {original_model} ──\n")
                cfg = sm.load_config()
                cfg["model"] = original_model
                sm.save_config(cfg)
                sm.stop_server()
                sm.start_server(cfg)
            with _custom_lock:
                _custom_runs[run_id]["results"] = all_results[-1] if all_results else None
                _custom_runs[run_id]["all_results"] = all_results
                _custom_runs[run_id]["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "run_id": run_id}


@app.get("/custom-benchmark/output/{run_id}")
def custom_benchmark_output(run_id: str, since: int = 0, _: None = Depends(_check_auth)) -> dict:
    """Return output lines since `since` index, plus running status and results when done."""
    if run_id not in _custom_runs:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    run = _custom_runs[run_id]
    lines = run["lines"][since:]
    return {
        "running": run["running"],
        "lines": lines,
        "results": run.get("results"),
        "all_results": run.get("all_results", []),
        "error": run.get("error"),
        "total_lines": len(run["lines"]),
    }


@app.post("/custom-benchmark/stop/{run_id}")
def stop_custom_benchmark(run_id: str, _: None = Depends(_check_auth)) -> dict:
    """Set the stop flag on a running custom benchmark."""
    if run_id not in _custom_runs:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    stop_event = _custom_runs[run_id].get("stop_event")
    if stop_event:
        stop_event.set()
    _custom_runs[run_id]["running"] = False
    return {"ok": True}


import os as _os_mod
import re as _re_mod
import signal as _signal_mod


def _find_restart_cmd() -> list[str]:
    """Return the command to relaunch vllm-mlx-ui after a restart or upgrade.

    Prefers the stable /opt/homebrew/bin/vllm-mlx-ui symlink (updated by brew
    immediately after upgrade) so we always launch the newest version.
    Falls back to PATH lookup, then the python -m approach via the opt symlink.
    """
    import shutil as _shutil
    for candidate in ["/opt/homebrew/bin/vllm-mlx-ui", "/usr/local/bin/vllm-mlx-ui"]:
        if _os_mod.path.exists(candidate) and _os_mod.access(candidate, _os_mod.X_OK):
            return [candidate]
    found = _shutil.which("vllm-mlx-ui")
    if found:
        return [found]
    import sys as _sys2
    return [_sys2.executable, "-m", "vllm_mlx.dashboard.mgmt_server"]


@app.get("/engines")
def list_engines(_: None = Depends(_check_auth)) -> dict:
    """Return all registered inference engines with install status and capabilities."""
    from vllm_mlx.dashboard.engines.registry import list_engines as _list_engines
    return {"engines": _list_engines()}


@app.post("/engines/reload")
def reload_engines(_: None = Depends(_check_auth)) -> dict:
    """Re-scan entry points and manifest files, then atomically update the engine registry.

    Returns the updated engine list.  Use this after installing a new engine
    plugin to surface it in the UI without restarting the server.
    """
    from vllm_mlx.dashboard.engines.registry import list_engines as _list_engines
    from vllm_mlx.dashboard.engines.registry import reload as _reload_registry
    try:
        _reload_registry()
        engines = _list_engines()
        return {"ok": True, "engines": engines}
    except Exception as exc:
        logger.warning("Engine registry reload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registry reload failed: {exc}") from exc


@app.get("/engines/{engine_id}/config-schema")
def get_engine_config_schema(engine_id: str, _: None = Depends(_check_auth)) -> dict:
    """Return the engine-specific config schema for the dynamic settings panel."""
    from vllm_mlx.dashboard.engines.registry import get_engine as _get_engine
    try:
        engine = _get_engine(engine_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine_id}") from None
    return {
        "engine_id": engine_id,
        "name": engine.name,
        "fields": engine.config_schema(),
    }


@app.post("/engines/{engine_id}/install")
async def install_engine(engine_id: str, _: None = Depends(_check_auth)):
    """Install the specified engine (SSE stream of install output).

    pip-based engines: runs ``pip install``.
    Homebrew-based engines (llama.cpp on macOS): runs ``brew install``.
    External engines with no headless installer: raises 400 with instructions.
    """
    import asyncio as _asyncio
    import subprocess as _sp

    from fastapi.responses import StreamingResponse

    from vllm_mlx.dashboard.engines.registry import get_engine as _get_engine

    try:
        engine = _get_engine(engine_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine_id}") from None
    if engine.install_method == "bundled":
        raise HTTPException(status_code=400, detail=f"Engine {engine_id!r} is bundled and cannot be installed.")

    req_errors = engine.check_requirements()
    if req_errors:
        raise HTTPException(
            status_code=400,
            detail="\n".join(req_errors),
        )

    try:
        cmd = engine.install_command()
    except NotImplementedError as exc:
        # Engine has no headless installer (e.g. LM Studio desktop app).
        raise HTTPException(
            status_code=400,
            detail=str(exc) or f"Engine {engine_id!r} has no automated installer — see engine description.",
        ) from None

    async def _stream():
        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.STDOUT,
            )
            if proc.stdout:
                async for line in proc.stdout:
                    yield line
            await proc.wait()
            if proc.returncode == 0:
                # Invalidate flag probe cache so the newly-installed binary is re-probed
                try:
                    from vllm_mlx.dashboard.engines.flag_probe import invalidate as _fp_inv
                    _fp_inv(cmd[0] if cmd else None)
                except Exception:
                    pass
                yield b"\n=== Auto-registering model... ===\n"
                try:
                    discovered = engine.get_discovered_models()
                    if discovered:
                        m = discovered[0]
                        from vllm_mlx.dashboard.server_manager import (
                            load_config,
                            save_config,
                        )
                        cfg = load_config()
                        engine_settings = dict(cfg.get("engine_settings", {}))
                        engine_settings.setdefault(engine_id, {})
                        engine_settings[engine_id]["launch_model"] = m.get("path", m["id"])
                        cfg["engine_settings"] = engine_settings
                        cfg["model"] = m["id"]
                        save_config(cfg)
                        yield f"Model registered: {m.get('display', m['id'])}\n".encode()
                except Exception as exc:
                    yield f"⚠ Model registration skipped: {exc}\n".encode()
                yield "✅ Install complete.\n".encode()
            else:
                yield f"❌ Install failed (exit {proc.returncode}).\n".encode()
        except Exception as e:
            yield f"❌ Install failed: {e}\n".encode()

    return StreamingResponse(_stream(), media_type="text/plain")


@app.post("/engines/{engine_id}/uninstall")
async def uninstall_engine(engine_id: str, _: None = Depends(_check_auth)):
    """Uninstall the specified engine (SSE stream of output)."""
    import asyncio as _asyncio

    from fastapi.responses import StreamingResponse

    from vllm_mlx.dashboard.engines.registry import get_engine as _get_engine

    try:
        engine = _get_engine(engine_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {engine_id}") from None

    try:
        cmd = engine.uninstall_command()
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or f"Engine {engine_id!r} has no automated uninstaller.",
        ) from None

    async def _stream():
        proc = await _asyncio.create_subprocess_exec(
            *cmd,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
        )
        if proc.stdout:
            async for line in proc.stdout:
                yield line
        await proc.wait()
        exit_msg = f"\n{'✅ Uninstall complete.' if proc.returncode == 0 else f'❌ Uninstall failed (exit {proc.returncode}).'}\n"
        yield exit_msg.encode()

    return StreamingResponse(_stream(), media_type="text/plain")


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
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            _os_mod.kill(_os_mod.getpid(), _signal_mod.SIGTERM)
    _thr.Thread(target=_do_shutdown, daemon=True).start()
    return {"ok": True}


@app.post("/restart")
def restart_app(_: None = Depends(_check_auth)) -> dict:
    """Restart the vllm-mlx-ui process (re-reads config, picks up code changes)."""
    import subprocess as _sp
    import sys as _sys
    import threading as _thr

    def _do_restart():
        import time as _t
        _t.sleep(0.3)
        try:
            from vllm_mlx.dashboard.server_manager import RELAUNCH_FLAG
            from vllm_mlx.dashboard.server_manager import STATE_DIR as _sd
            _sd.mkdir(parents=True, exist_ok=True)
            RELAUNCH_FLAG.write_text("1")
        except Exception:
            logger.warning("Operation failed", exc_info=True)
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
                "release_url": p.release_url,
            }
            for p in packages
        ],
        "any_update": any(p.update_available for p in packages),
        "install_method": _uc._detect_install_method(),
    }


@app.post("/updates/install")
def install_updates_endpoint(_: None = Depends(_check_auth)) -> dict:
    """Start an upgrade and self-restart after it completes."""
    import subprocess as _sp
    import threading as _thr

    from vllm_mlx.dashboard import update_checker as _uc
    cmd = _uc.upgrade_command()
    # engine_upgrade_commands uses sys.executable -m pip internally,
    # so it always targets the same environment as the running process.
    engine_cmds = _uc.engine_upgrade_commands()

    def _do_upgrade():
        import time as _t
        _uc.upgrade_status = "upgrading"
        # Snapshot engine config schemas so we can detect new settings post-upgrade
        _uc.snapshot_engine_schemas()
        try:
            main_result = _sp.run(cmd, timeout=300, check=False)
            if main_result.returncode != 0:
                logger.warning("Main upgrade exited with code %d", main_result.returncode)
        except Exception as e:
            logger.warning("Main upgrade failed: %s", e, exc_info=True)
            _uc.upgrade_status = "error:upgrade command failed"
            return
        # Engine upgrades — run as argv lists, no shell quoting issues
        engine_errors = 0
        for ec in engine_cmds:
            try:
                result = _sp.run(ec, timeout=300, check=False)
                if result.returncode != 0:
                    engine_errors += 1
                    logger.warning("Engine upgrade exited with code %d: %s", result.returncode, ec)
            except Exception:
                engine_errors += 1
                logger.warning("Engine upgrade failed: %s", ec, exc_info=True)
        # Detect new engine settings after upgrade
        _uc.bust_cache()
        discovered = _uc.discover_new_features()
        if discovered:
            logger.info("Post-upgrade feature discovery: %d engines have new settings", len(discovered))
            for feat in discovered:
                logger.info("  %s: %s", feat["engine_name"], ", ".join(feat["new_settings"]))
        # Model weight upgrades — re-download GGUF files that have new versions
        try:
            from vllm_mlx.dashboard.engines.registry import ENGINES as _mdl_engines, _registry_lock as _mdl_lock
            with _mdl_lock:
                _mdl_snapshot = dict(_mdl_engines)
            for _mdl_engine in _mdl_snapshot.values():
                try:
                    if not hasattr(_mdl_engine, "model_update_available"):
                        continue
                    if not _mdl_engine.model_update_available():
                        continue
                    _mdl_cmd = _mdl_engine.model_upgrade_command()
                    if not _mdl_cmd:
                        continue
                    logger.info("Upgrading model weights for %s", _mdl_engine.name)
                    _mdl_result = _sp.run(_mdl_cmd, timeout=600, check=False)
                    if _mdl_result.returncode == 0:
                        _mdl_engine.refresh_model_version()
                    else:
                        logger.warning(
                            "Model weight upgrade for %s exited with code %d",
                            _mdl_engine.name, _mdl_result.returncode,
                        )
                except Exception as _mdl_exc:
                    logger.warning("Model weight upgrade failed: %s", _mdl_exc, exc_info=True)
        except Exception:
            logger.warning("Failed to discover model weight upgrades", exc_info=True)

        # Stop inference server so new engine binary takes effect on restart
        try:
            from vllm_mlx.dashboard.server_manager import get_server_status, stop_server
            if get_server_status().get("running"):
                logger.info("Stopping inference server after engine upgrades...")
                stop_server()
        except Exception:
            logger.warning("Failed to stop inference server after upgrade", exc_info=True)
        # Bust cache so the next /updates check reflects newly installed versions
        _uc.bust_cache()
        # Invalidate flag probe cache so newly-upgraded binaries are re-probed
        try:
            from vllm_mlx.dashboard.engines.flag_probe import (
                invalidate as _fp_invalidate,
            )
            _fp_invalidate()
        except Exception:
            logger.warning("Failed to invalidate flag probe cache after upgrade", exc_info=True)
        _uc.upgrade_status = "restarting"
        _t.sleep(2)
        try:
            from vllm_mlx.dashboard.server_manager import (
                AUTO_START_FLAG,
                RELAUNCH_FLAG,
            )
            from vllm_mlx.dashboard.server_manager import (
                STATE_DIR as _sd,
            )
            _sd.mkdir(parents=True, exist_ok=True)
            RELAUNCH_FLAG.write_text("1")
            AUTO_START_FLAG.write_text("1")
        except Exception:
            logger.warning("Operation failed", exc_info=True)
        _os_mod.kill(_os_mod.getpid(), _signal_mod.SIGTERM)

    _thr.Thread(target=_do_upgrade, daemon=True).start()
    return {"ok": True, "message": "Upgrade started. The server will restart in ~30s."}


@app.get("/updates/install-status")
def install_status(_: None = Depends(_check_auth)) -> dict:
    """Return the current upgrade phase for frontend progress polling."""
    from vllm_mlx.dashboard import update_checker as _uc
    discovered = _uc.latest_discovered_features
    return {
        "status": _uc.upgrade_status,
        "discovered_features": discovered if discovered else None,
    }


@app.get("/updates/discovered-features")
def get_discovered_features(_: None = Depends(_check_auth)) -> list:
    """Return features discovered after the last upgrade (new engine settings)."""
    from vllm_mlx.dashboard import update_checker as _uc
    with _uc._latest_discovered_lock:
        return list(_uc.latest_discovered_features)


@app.delete("/updates/discovered-features")
def dismiss_discovered_features(_: None = Depends(_check_auth)) -> dict:
    """Dismiss discovered features — clear memory and remove the file."""
    from vllm_mlx.dashboard import update_checker as _uc
    _uc.clear_discovered_features()
    return {"ok": True}


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
        logger.warning("Operation failed", exc_info=True)

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
        except _sp.CalledProcessError:
            ip = ""  # exit code 1 = no IP assigned to this interface — expected
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
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
        logger.warning("Operation failed", exc_info=True)

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
                        logger.warning("Operation failed", exc_info=True)
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    if not subnets:
        return []

    # Build full candidate list (skip .0 and .255)
    candidates: list[str] = []
    own_ips: set[str] = set()
    try:
        own_ips = {r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None)}
    except Exception:
        logger.warning("Operation failed", exc_info=True)

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
                        logger.warning("Operation failed", exc_info=True)
                    return {"ip": ip, "port": MGMT_PORT, "name": name}
        except Exception:
            logger.warning("Operation failed", exc_info=True)
        return None

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = {pool.submit(_probe, ip): ip for ip in candidates}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                found.append(result)

    return found


@app.get("/fleet/discover")
def fleet_discover(_: None = Depends(_check_auth)) -> list:
    """Scan the local subnet for other vllm-mlx-ui management servers.

    Probes port 8502 (the mgmt server default) across the local /24 subnet(s),
    then confirms each responsive host by fetching ``/status`` to retrieve
    version and active model information.

    Returns a list of ``{ip, hostname, port, version, model_id}`` dicts for
    hosts that are confirmed vllm-mlx-ui instances.
    """
    import json as _json
    import socket
    import subprocess as _sp
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor, as_completed

    MGMT_PORT = 8502
    CONNECT_TIMEOUT = 0.3
    HTTP_TIMEOUT = 1.0

    # Collect /24 subnets from active non-loopback interfaces
    subnets: set[str] = set()
    try:
        out = _sp.check_output(["ifconfig"], text=True, stderr=_sp.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127." not in line:
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    base = ".".join(ip.split(".")[:3])
                    subnets.add(base)
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    if not subnets:
        return []

    # Collect own IPs to skip
    own_ips: set[str] = set()
    try:
        own_ips = {r[4][0] for r in socket.getaddrinfo(socket.gethostname(), None)}
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    candidates: list[str] = [
        f"{base}.{i}"
        for base in subnets
        for i in range(1, 255)
        if f"{base}.{i}" not in own_ips
    ]

    def _probe(ip: str) -> dict | None:
        # Phase 1: quick TCP connect
        try:
            with socket.create_connection((ip, MGMT_PORT), timeout=CONNECT_TIMEOUT):
                pass
        except Exception as e:
            logger.warning("Operation failed: %s", e, exc_info=True)
            return None

        # Phase 2: confirm vllm-mlx-ui by fetching /status
        try:
            url = f"http://{ip}:{MGMT_PORT}/status"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                body = _json.loads(resp.read().decode())
        except Exception:
            logger.warning("Port was open but /status failed — skipping", exc_info=True)
            return None

        hostname = ip
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            logger.warning("Operation failed", exc_info=True)

        return {
            "ip": ip,
            "hostname": hostname,
            "port": MGMT_PORT,
            "version": body.get("version", ""),
            "model_id": body.get("model", body.get("model_id", "")),
        }

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = {pool.submit(_probe, ip): ip for ip in candidates}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                found.append(result)

    found.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
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
        raise HTTPException(status_code=408, detail="Folder dialog timed out") from None


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
    content = await asyncio.to_thread(_read_doc_file, full)
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")


def _read_doc_file(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _build_docs_toc() -> dict:
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


@app.get("/api/docs", include_in_schema=False)
async def _list_docs() -> dict:
    """Return a structured table of contents for the docs directory."""
    return await asyncio.to_thread(_build_docs_toc)


# ── Chat history ──────────────────────────────────────────────────────────────
# NOTE: These routes MUST be registered before the SPA catch-all below.
# FastAPI matches routes in definition order; /{full_path:path} would intercept
# GET /chats and GET /chats/{id} if they were defined after it.

class SaveMessageModel(BaseModel):
    role: str
    content: str
    reasoning: str | None = None


class SaveChatRequest(BaseModel):
    id: str
    title: str
    model: str = ""
    engine: str = ""
    is_draft: bool = False
    created_at: int | None = None
    messages: list[SaveMessageModel] = []


@app.get("/chats")
def list_chats(_: None = Depends(_check_auth)) -> dict:
    """Return all saved conversation summaries (no message content)."""
    try:
        convs = cs.list_conversations()
        return {"conversations": convs}
    except Exception as exc:
        logger.warning("list_chats failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/chats/draft")
def get_draft_chat(_: None = Depends(_check_auth)) -> dict:
    """Return the most recently updated draft conversation (active session), or 404."""
    try:
        draft = cs.get_latest_draft()
        if not draft:
            raise HTTPException(status_code=404, detail="No draft found")
        return draft
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("get_draft_chat failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str, _: None = Depends(_check_auth)) -> dict:
    """Return a full conversation with all messages."""
    try:
        conv = cs.get_conversation(chat_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("get_chat failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/chats")
def delete_all_chats(_: None = Depends(_check_auth)) -> dict:
    """Delete all saved conversations and messages."""
    try:
        count = cs.delete_all_conversations()
        return {"ok": True, "deleted": count}
    except Exception as exc:
        logger.warning("delete_all_chats failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, _: None = Depends(_check_auth)) -> dict:
    """Delete a single conversation."""
    try:
        found = cs.delete_conversation(chat_id)
        if not found:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("delete_chat failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── SPA catch-all — MUST remain last ─────────────────────────────────────────
# This catch-all serves index.html for all unmatched GET paths, enabling
# Vue Router's history mode. It MUST be the last route registered so it does
# not intercept API routes defined above (e.g. /chats, /chats/{id}).

if _os.path.isdir(_UI_DIST):
    app.mount("/assets", StaticFiles(directory=_os.path.join(_UI_DIST, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_spa(full_path: str = "") -> PlainTextResponse:
        index = _os.path.join(_UI_DIST, "index.html")
        if not _os.path.isfile(index):
            return PlainTextResponse(
                "Serving vllm-mlx-ui… this page appears after the app has started.\n"
                "If this persists, run `brew upgrade vllm-mlx-ui` and restart the process.",
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return FileResponse(index, headers={"Cache-Control": "no-store"})


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
