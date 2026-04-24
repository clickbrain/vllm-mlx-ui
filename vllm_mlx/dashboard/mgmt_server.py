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
from . import server_manager as sm

app = FastAPI(
    title="vllm-mlx Management API",
    description="Remote control API for the vllm-mlx dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # Restrict to localhost origins — the mgmt API is called from Python (httpx),
    # not from browser JavaScript, so this never blocks legitimate use.
    # Wildcard origins would allow any malicious website to control the server
    # via fetch() without credentials.
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://localhost:8502",
        "http://127.0.0.1:8502",
        "http://localhost",
        "http://127.0.0.1",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Remove X-Frame-Options so the management API can be embedded in iFrames
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _StarletteRequest


class _PermissiveHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _StarletteRequest, call_next):
        response = await call_next(request)
        # Allow framing from any origin (needed for embedding in Streamlit iframes).
        # X-Frame-Options ALLOWALL is non-standard and ignored by browsers;
        # Content-Security-Policy frame-ancestors is the correct mechanism.
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
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
    return {"ok": True}


# ── Server lifecycle ──────────────────────────────────────────────────────────

@app.get("/status")
def status(_: None = Depends(_check_auth)) -> dict:
    return sm.get_server_status()


@app.post("/start")
def start(_: None = Depends(_check_auth)) -> dict:
    config = sm.load_config()
    if not config.get("model"):
        raise HTTPException(status_code=400, detail="No model selected. Set a model in config first.")
    ok, msg = sm.start_server(config)
    return {"ok": ok, "message": msg}


@app.post("/stop")
def stop(_: None = Depends(_check_auth)) -> dict:
    ok, msg = sm.stop_server()
    return {"ok": ok, "message": msg}


@app.get("/logs")
def logs(lines: int = 200, _: None = Depends(_check_auth)) -> dict:
    return {"logs": sm.get_logs(lines)}


@app.get("/metrics")
def metrics(_: None = Depends(_check_auth)) -> dict:
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
    return sm.load_config()


@app.post("/config")
def set_config(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    # Defense-in-depth: strip connectivity keys before persisting.
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
    return mm.get_cached_models()


@app.get("/models/cache_size")
def cache_size(_: None = Depends(_check_auth)) -> dict:
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
    with _download_lock:
        return _download_status.get(model_id, {"status": "unknown", "error": None})


@app.delete("/models/{model_id:path}")
def delete_model(model_id: str, _: None = Depends(_check_auth)) -> dict:
    try:
        ok, msg = mm.delete_model(model_id)
        return {"ok": ok, "message": msg}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
    return br.load_results()


@app.delete("/benchmarks/{result_id}")
def delete_benchmark(result_id: int, _: None = Depends(_check_auth)) -> dict:
    results = br.load_results()
    if not (0 <= result_id < len(results)):
        raise HTTPException(status_code=404, detail=f"Benchmark result {result_id} not found")
    br.delete_result(result_id)
    return {"ok": True}


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


@app.post("/v1/chat/completions")
async def proxy_chat(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """
    Proxy for /v1/chat/completions.
    If auto_model_switch is enabled and the requested model differs from the
    loaded one, the server is automatically reloaded with the new model before
    forwarding. Hot-swap runs in a thread so it does not block the event loop.

    Enable this proxy by pointing your OpenAI client at:
      http://<this-machine-ip>:8502/v1/chat/completions
    """
    import asyncio
    import httpx

    requested_model = request.get("model", "").strip()
    if requested_model:
        cfg_check = sm.load_config()
        if cfg_check.get("auto_model_switch", False):
            await asyncio.to_thread(_hot_swap_if_needed, requested_model)


    cfg = sm.load_config()
    target = sm.get_server_url(cfg)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = cfg.get("api_key", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        if request.get("stream"):
            # Stream the response back.
            # The httpx client must be created INSIDE the generator — if it were
            # created in the outer async-with block, Python would close it when
            # this coroutine returns the StreamingResponse, before FastAPI has a
            # chance to iterate the generator body.
            from fastapi.responses import StreamingResponse

            async def _stream():
                async with httpx.AsyncClient(timeout=300) as _client:
                    async with _client.stream(
                        "POST", f"{target}/v1/chat/completions",
                        json=request, headers=headers,
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk

            return StreamingResponse(_stream(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{target}/v1/chat/completions",
                    json=request, headers=headers,
                )
                return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/auto_switch_enabled")
def auto_switch_status(_: None = Depends(_check_auth)) -> dict:
    cfg = sm.load_config()
    return {"enabled": cfg.get("auto_model_switch", False)}


@app.post("/auto_switch_enabled")
def set_auto_switch(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    cfg = sm.load_config()
    cfg["auto_model_switch"] = bool(data.get("enabled", True))
    sm.save_config(cfg)
    return {"ok": True, "enabled": cfg["auto_model_switch"]}


# ── Vue UI static serving ─────────────────────────────────────────────────────
# Serve the built Vue UI from ui/dist/ at the root path.
# API routes (/status, /memory, etc.) take priority because they are registered
# first. The catch-all "/" route returns index.html for SPA client-side routing.

import os as _os

_UI_DIST = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "ui", "dist")

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
