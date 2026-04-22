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

import threading
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
        response.headers["X-Frame-Options"] = "ALLOWALL"
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response


app.add_middleware(_PermissiveHeadersMiddleware)


# ── Auth ─────────────────────────────────────────────────────────────────────

def _check_auth(x_api_key: str | None = Header(default=None)) -> None:
    cfg = sm.load_config()
    key = cfg.get("mgmt_api_key", "").strip()
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
    return sm.get_metrics()


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/config")
def get_config(_: None = Depends(_check_auth)) -> dict:
    return sm.load_config()


@app.post("/config")
def set_config(data: dict[str, Any], _: None = Depends(_check_auth)) -> dict:
    sm.save_config(data)
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
        _download_status[model_id] = {"status": "downloading", "error": None}

    def _do_download() -> None:
        try:
            mm.download_model(model_id, req.token or None)
            with _download_lock:
                _download_status[model_id] = {"status": "done", "error": None}
        except Exception as exc:
            with _download_lock:
                _download_status[model_id] = {"status": "error", "error": str(exc)}

    threading.Thread(target=_do_download, daemon=True).start()
    return {"ok": True, "message": f"Download started for {model_id}", "status": "downloading"}


@app.get("/models/download_status/{model_id:path}")
def download_status(model_id: str, _: None = Depends(_check_auth)) -> dict:
    with _download_lock:
        return _download_status.get(model_id, {"status": "unknown", "error": None})


@app.delete("/models/{model_id:path}")
def delete_model(model_id: str, _: None = Depends(_check_auth)) -> dict:
    try:
        mm.delete_model(model_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Benchmarks ────────────────────────────────────────────────────────────────

@app.get("/benchmarks")
def list_benchmarks(_: None = Depends(_check_auth)) -> list:
    return br.load_results()


@app.delete("/benchmarks/{result_id}")
def delete_benchmark(result_id: str, _: None = Depends(_check_auth)) -> dict:
    br.delete_result(result_id)
    return {"ok": True}


# ── Auto model-switch proxy ───────────────────────────────────────────────────
# When a chat client (e.g. OpenAI-compatible app) sends a request with a model
# name that differs from the currently loaded model, this proxy endpoint
# automatically stops the server, reloads with the new model and optimal
# settings, waits for it to be healthy, then forwards the request.

_swap_lock = threading.Lock()


def _hot_swap_if_needed(requested_model: str) -> None:
    """Reload the inference server if the requested model differs from loaded."""
    cfg = sm.load_config()
    current = cfg.get("model", "").strip()
    if current == requested_model:
        return

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
        import time as _time
        _time.sleep(2)
        sm.start_server(cfg)

        # Wait up to 120 s for the server to become healthy
        for _ in range(60):
            _time.sleep(2)
            status = sm.get_server_status()
            if status.get("healthy"):
                break


@app.post("/v1/chat/completions")
async def proxy_chat(request: dict[str, Any], _: None = Depends(_check_auth)) -> Any:
    """
    Proxy for /v1/chat/completions.
    If the requested model differs from the loaded one, the server is
    automatically reloaded with the new model before forwarding.

    Enable this proxy by pointing your OpenAI client at:
      http://<this-machine-ip>:8502/v1/chat/completions
    """
    import httpx

    requested_model = request.get("model", "").strip()
    if requested_model:
        _hot_swap_if_needed(requested_model)

    cfg = sm.load_config()
    target = sm.get_server_url(cfg)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = cfg.get("api_key", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            if request.get("stream"):
                # Stream the response back
                from fastapi.responses import StreamingResponse

                async def _stream():
                    async with client.stream(
                        "POST", f"{target}/v1/chat/completions",
                        json=request, headers=headers,
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk

                return StreamingResponse(_stream(), media_type="text/event-stream")
            else:
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


# ── Server startup ────────────────────────────────────────────────────────────

def start_mgmt_server(host: str = "0.0.0.0", port: int = 8502) -> None:
    """Start the management API server (blocking). Call from a daemon thread."""
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_mgmt_server_thread(host: str = "0.0.0.0", port: int = 8502) -> threading.Thread:
    """Start the management API server in a background daemon thread."""
    t = threading.Thread(target=start_mgmt_server, args=(host, port), daemon=True)
    t.start()
    return t
