# SPDX-License-Identifier: Apache-2.0
"""
Server process lifecycle management for the vllm-mlx dashboard.

Handles starting, stopping, and monitoring the inference server subprocess.
State (PID, config, logs) is persisted to ~/.vllm_mlx_ui/.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

STATE_DIR = Path.home() / ".vllm_mlx_ui"
PID_FILE = STATE_DIR / "server.pid"
CONFIG_FILE = STATE_DIR / "server_config.json"
LOG_FILE = STATE_DIR / "server.log"
AUTO_START_FLAG = STATE_DIR / "auto_start_after_relaunch.flag"

TOOL_CALL_PARSERS = [
    "",
    "auto",
    "mistral",
    "qwen",
    "qwen3_coder",
    "llama",
    "hermes",
    "harmony",
    "gpt-oss",
    "deepseek",
    "kimi",
    "granite",
    "nemotron",
    "xlam",
    "functionary",
    "gemma4",
    "glm47",
    "minimax",
]

REASONING_PARSERS = ["", "qwen3", "deepseek_r1", "gemma4", "harmony", "gpt_oss", "glm4"]

DEFAULT_CONFIG: dict[str, Any] = {
    "model": "",
    "served_model_name": "",
    "host": "127.0.0.1",
    "port": 8000,
    "api_key": "",
    "continuous_batching": False,
    "max_tokens": 32768,
    "max_request_tokens": 32768,
    "reasoning_parser": "",
    "tool_call_parser": "",
    "enable_auto_tool_choice": False,
    "gpu_memory_utilization": 0.90,
    "enable_prefix_cache": True,
    "cache_memory_mb": 0,
    "kv_cache_quantization": False,
    "kv_cache_quantization_bits": 8,
    "use_paged_cache": False,
    "enable_mtp": False,
    "mtp_num_draft_tokens": 1,
    "rate_limit": 0,
    "timeout": 300.0,
    "stream_interval": 1,
    "mllm": False,
    "trust_remote_code": False,
    "embedding_model": "",
    "rerank_model": "",
    "enable_metrics": False,
    "offline": False,
    # Dashboard network settings (controls the Streamlit UI, not the inference server)
    "ui_host": "127.0.0.1",
    "ui_port": 8501,
    "mgmt_port": 8502,
    # Remote mode: point dashboard at a server on another machine.
    # When set, overrides local subprocess calls with HTTP calls to the mgmt API.
    "remote_server_url": "",   # inference API  e.g. http://192.168.1.42:8000
    "remote_mgmt_url": "",     # management API e.g. http://192.168.1.42:8502
    "mgmt_api_key": "",        # optional shared secret for the management API
}


# ── Remote management helpers ────────────────────────────────────────────────

def _mgmt_base(config: dict[str, Any] | None = None) -> str | None:
    """Return the management API base URL if remote mode is active.

    Returns None (forcing local mode) when the UI session has the connection
    toggle set to "local", even if a remote_mgmt_url is configured.
    """
    # Respect the UI's local/remote mode toggle when running inside Streamlit.
    try:
        import streamlit as _st
        if _st.session_state.get("connection_mode", "local") == "local":
            return None
    except Exception:
        pass  # Not in a Streamlit context (e.g., CLI or mgmt API process)
    if config is None:
        config = load_config()
    url = config.get("remote_mgmt_url", "").strip()
    return url.rstrip("/") if url else None


def _mgmt_headers(config: dict[str, Any] | None = None) -> dict[str, str]:
    if config is None:
        config = load_config()
    key = config.get("mgmt_api_key", "").strip()
    return {"X-Api-Key": key} if key else {}


def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _load_local_config() -> dict[str, Any]:
    """Load config from disk only — no remote fetch. Used to read connectivity settings."""
    _ensure_state_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def load_config() -> dict[str, Any]:
    _ensure_state_dir()
    local: dict[str, Any] = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            local = {**DEFAULT_CONFIG, **saved}
        except Exception:
            pass
    mgmt = _mgmt_base(local)
    if mgmt:
        try:
            r = requests.get(f"{mgmt}/config", headers=_mgmt_headers(local), timeout=3)
            if r.status_code == 200:
                remote_cfg = r.json()
                # Preserve local UI/connectivity settings so we don't overwrite
                # the address we need to reach the remote machine.
                for keep in ("remote_server_url", "remote_mgmt_url", "mgmt_api_key",
                             "ui_host", "ui_port", "mgmt_port"):
                    if keep in local:
                        remote_cfg[keep] = local[keep]
                return {**DEFAULT_CONFIG, **remote_cfg}
        except Exception:
            pass  # Fall back to local config silently
    return local


def save_config(config: dict[str, Any]) -> None:
    _ensure_state_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            requests.post(f"{mgmt}/config", json=config,
                          headers=_mgmt_headers(config), timeout=5)
        except Exception:
            pass  # Best effort; local save already succeeded


def _get_pid() -> int | None:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except Exception:
            return None
    return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def get_server_url(config: dict[str, Any] | None = None) -> str:
    if config is None:
        config = load_config()
    remote = config.get("remote_server_url", "").strip()
    if remote:
        return remote.rstrip("/")
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8000)
    return f"http://{host}:{port}"


def check_health(config: dict[str, Any] | None = None) -> tuple[bool, dict]:
    """Returns (is_healthy, health_data). Never raises."""
    try:
        url = get_server_url(config)
        r = requests.get(f"{url}/health", timeout=2)
        if r.status_code == 200:
            return True, r.json()
    except Exception:
        pass
    return False, {}


def get_server_status() -> dict[str, Any]:
    """Returns a status dict safe to call on every Streamlit rerun."""
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = requests.get(f"{mgmt}/status", headers=_mgmt_headers(cfg), timeout=3)
            if r.status_code == 200:
                return r.json()
            return {"running": False, "healthy": False, "pid": None, "health": {}, "error": f"Mgmt API {r.status_code}"}
        except Exception as e:
            return {"running": False, "healthy": False, "pid": None, "health": {}, "error": str(e)}
    # Local mode
    pid = _get_pid()
    if pid is None:
        return {"running": False, "healthy": False, "pid": None, "health": {}}
    if not _is_process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return {"running": False, "healthy": False, "pid": None, "health": {}}
    healthy, health_data = check_health()
    return {
        "running": True,
        "healthy": healthy,
        "pid": pid,
        "health": health_data,
    }


def _build_command(config: dict[str, Any]) -> list[str]:
    """Build the vllm-mlx serve command from config."""
    binary = shutil.which("vllm-mlx")
    cmd = [binary] if binary else [sys.executable, "-m", "vllm_mlx.cli"]
    cmd += ["serve", config["model"]]

    cmd += ["--host", str(config.get("host", "127.0.0.1"))]
    cmd += ["--port", str(config.get("port", 8000))]

    if config.get("served_model_name"):
        cmd += ["--served-model-name", config["served_model_name"]]
    if config.get("api_key"):
        cmd += ["--api-key", config["api_key"]]
    if config.get("continuous_batching"):
        cmd += ["--continuous-batching"]
    if config.get("max_tokens", 32768) != 32768:
        cmd += ["--max-tokens", str(config["max_tokens"])]
    if config.get("max_request_tokens", 32768) != 32768:
        cmd += ["--max-request-tokens", str(config["max_request_tokens"])]
    if config.get("reasoning_parser"):
        cmd += ["--reasoning-parser", config["reasoning_parser"]]
    if config.get("tool_call_parser"):
        cmd += ["--tool-call-parser", config["tool_call_parser"]]
    if config.get("enable_auto_tool_choice") and config.get("tool_call_parser"):
        cmd += ["--enable-auto-tool-choice"]
    if config.get("gpu_memory_utilization", 0.90) != 0.90:
        cmd += ["--gpu-memory-utilization", str(config["gpu_memory_utilization"])]
    if not config.get("enable_prefix_cache", True):
        cmd += ["--disable-prefix-cache"]
    if config.get("cache_memory_mb", 0) > 0:
        cmd += ["--cache-memory-mb", str(config["cache_memory_mb"])]
    if config.get("kv_cache_quantization"):
        cmd += ["--kv-cache-quantization"]
        if config.get("kv_cache_quantization_bits", 8) != 8:
            cmd += ["--kv-cache-quantization-bits", str(config["kv_cache_quantization_bits"])]
    if config.get("use_paged_cache"):
        cmd += ["--use-paged-cache"]
    if config.get("enable_mtp"):
        cmd += ["--enable-mtp"]
        if config.get("mtp_num_draft_tokens", 1) != 1:
            cmd += ["--mtp-num-draft-tokens", str(config["mtp_num_draft_tokens"])]
    if config.get("rate_limit", 0) > 0:
        cmd += ["--rate-limit", str(config["rate_limit"])]
    if config.get("stream_interval", 1) != 1:
        cmd += ["--stream-interval", str(config["stream_interval"])]
    if config.get("mllm"):
        cmd += ["--mllm"]
    if config.get("trust_remote_code"):
        cmd += ["--trust-remote-code"]
    if config.get("embedding_model"):
        cmd += ["--embedding-model", config["embedding_model"]]
    if config.get("rerank_model"):
        cmd += ["--rerank-model", config["rerank_model"]]
    if config.get("enable_metrics"):
        cmd += ["--enable-metrics"]
    if config.get("offline"):
        cmd += ["--offline"]

    return cmd


def start_server(config: dict[str, Any]) -> tuple[bool, str]:
    """
    Start the server as a background subprocess (local) or via mgmt API (remote).
    Returns immediately — the server loads the model asynchronously.
    """
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            # Push config to remote first so it starts with latest settings
            requests.post(f"{mgmt}/config", json=config, headers=_mgmt_headers(config), timeout=5)
            r = requests.post(f"{mgmt}/start", headers=_mgmt_headers(config), timeout=10)
            d = r.json()
            return d.get("ok", False), d.get("message", str(r.status_code))
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    pid = _get_pid()
    if pid and _is_process_alive(pid):
        return False, "Server is already running."

    if not config.get("model", "").strip():
        return False, "No model specified. Set a model in the configuration below."

    save_config(config)
    _ensure_state_dir()

    cmd = _build_command(config)
    with open(LOG_FILE, "w") as log_fh:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(str(proc.pid))

    # Give it a moment to fail fast (bad model path, port conflict, etc.)
    for _ in range(6):
        time.sleep(0.5)
        if not _is_process_alive(proc.pid):
            PID_FILE.unlink(missing_ok=True)
            logs = get_logs(last_n_lines=20)
            return False, f"Server exited immediately. Check logs:\n{logs}"

    return True, f"Server starting (PID {proc.pid}). Loading model — this may take a minute…"


def stop_server() -> tuple[bool, str]:
    """Send SIGTERM to the server process (local) or via mgmt API (remote)."""
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = requests.post(f"{mgmt}/stop", headers=_mgmt_headers(cfg), timeout=10)
            d = r.json()
            return d.get("ok", False), d.get("message", str(r.status_code))
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    pid = _get_pid()
    if pid is None:
        return False, "Server is not running."
    if not _is_process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return False, "Server was not running (cleaned up stale PID file)."

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not _is_process_alive(pid):
                break
        else:
            os.kill(pid, signal.SIGKILL)
        PID_FILE.unlink(missing_ok=True)
        return True, "Server stopped."
    except Exception as e:
        return False, f"Error stopping server: {e}"


def get_logs(last_n_lines: int = 150) -> str:
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = requests.get(f"{mgmt}/logs", params={"lines": last_n_lines},
                             headers=_mgmt_headers(cfg), timeout=5)
            return r.json().get("logs", "")
        except Exception as e:
            return f"(Could not fetch remote logs: {e})"
    if not LOG_FILE.exists():
        return "(No log file yet — start the server to see output here.)"
    with open(LOG_FILE) as f:
        lines = f.readlines()
    return "".join(lines[-last_n_lines:])


def get_metrics(api_key: str = "") -> dict | None:
    """Poll for real-time engine metrics.
    In remote mode, proxies through the management API so the caller
    does not need direct access to the inference server port.
    """
    config = load_config()
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            r = requests.get(f"{mgmt}/metrics", headers=_mgmt_headers(config), timeout=3)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None
    # Local mode — call inference API directly
    url = get_server_url(config)
    headers = {}
    key = api_key or config.get("api_key", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = requests.get(f"{url}/v1/status", headers=headers, timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def get_cache_stats(api_key: str = "") -> dict | None:
    """Fetch cache statistics.
    In remote mode, proxies through the management API.
    """
    config = load_config()
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            r = requests.get(f"{mgmt}/cache/stats", headers=_mgmt_headers(config), timeout=3)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None
    url = get_server_url(config)
    headers = {}
    key = api_key or config.get("api_key", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = requests.get(f"{url}/v1/cache/stats", headers=headers, timeout=2)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def clear_cache(cache_type: str = "all", api_key: str = "") -> tuple[bool, str]:
    """Clear server caches. cache_type: 'all' or 'prefix'.
    In remote mode, proxies through the management API.
    """
    config = load_config()
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            r = requests.delete(
                f"{mgmt}/cache/{cache_type}", headers=_mgmt_headers(config), timeout=5
            )
            if r.status_code in (200, 204):
                return True, r.json().get("status", "ok")
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)
    # Local mode
    url = get_server_url(config)
    headers = {}
    key = api_key or config.get("api_key", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    endpoint = "/v1/cache/prefix" if cache_type == "prefix" else "/v1/cache"
    try:
        r = requests.delete(f"{url}{endpoint}", headers=headers, timeout=5)
        return r.status_code in (200, 204), r.json().get("status", "ok")
    except Exception as e:
        return False, str(e)
