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
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

STATE_DIR = Path.home() / ".vllm_mlx_ui"
PID_FILE = STATE_DIR / "server.pid"
UI_PID_FILE = STATE_DIR / "ui.pid"
STREAMLIT_PID_FILE = STATE_DIR / "streamlit.pid"
CONFIG_FILE = STATE_DIR / "server_config.json"
LOG_FILE = STATE_DIR / "server.log"
AUTO_START_FLAG = STATE_DIR / "auto_start_after_relaunch.flag"
RELAUNCH_FLAG   = STATE_DIR / "relaunch_pending.flag"

# ── Persistent HTTP session ────────────────────────────────────────────────────
# A single Session is reused across all remote API calls so TCP connections stay
# alive (HTTP keep-alive) and are never re-opened unnecessarily.  This is the
# primary fix for slow remote-mode response times: without keep-alive every call
# re-does mDNS resolution + TCP handshake + TLS (if HTTPS) which can take 1-3 s.
_http = requests.Session()
_http.mount("http://", HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=8))
_http.mount("https://", HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=8))


def _force_ipv4_url(url: str) -> str:
    """Replace a .local mDNS hostname with its IPv4 address.

    macOS mDNS advertises both IPv6 link-local (fe80::…) and IPv4 addresses for
    .local hostnames.  Python's requests tries IPv6 first; link-local IPv6 lacks
    a scope ID so the connection always fails and waits for the timeout before
    falling back to IPv4.  Resolving once to IPv4 and caching the result makes
    the first call instant and subsequent calls reuse the keep-alive connection.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host.endswith(".local"):
        return url
    try:
        addrs = socket.getaddrinfo(host, parsed.port or 80, socket.AF_INET, socket.SOCK_STREAM)
        if addrs:
            ipv4 = addrs[0][4][0]
            port_part = f":{parsed.port}" if parsed.port else ""
            return urlunparse(parsed._replace(netloc=f"{ipv4}{port_part}"))
    except Exception:
        pass
    return url


_resolved_urls: dict[str, str] = {}  # cache: original_url → ipv4_url


def _mgmt_url(base: str) -> str:
    """Return an IPv4-resolved version of the mgmt base URL (cached)."""
    if base not in _resolved_urls:
        _resolved_urls[base] = _force_ipv4_url(base)
    return _resolved_urls[base]

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
    # Startup behavior: "auto" = load last model, "ask" = show picker, "none" = manual
    "startup_model_behavior": "auto",
    # Auto model switch (proxy hot-swap) — local feature, not synced to remote
    "auto_model_switch": True,
    # Last used connection mode — "local" or "remote". Persisted so the UI
    # restores the correct target on browser refresh / app restart.
    "connection_mode": "local",
}


# ── Streamlit context detection ────────────────────────────────────────────────

def _in_streamlit() -> bool:
    """Return True only when called from an active Streamlit script context.

    This is used to decide whether it is safe to access st.session_state and
    whether remote mode should be active.  Must return False for every
    non-Streamlit call site (mgmt API uvicorn threads, CLI, tests) to prevent
    infinite recursion and console noise.

    IMPORTANT: calling get_script_run_ctx() from an AnyIO worker thread
    (uvicorn's request handler pool) emits a "missing ScriptRunContext" WARNING
    on every call.  We short-circuit for those threads by checking the thread
    name BEFORE touching any Streamlit API so the warning never fires.
    """
    import threading
    thread_name = threading.current_thread().name
    # AnyIO worker threads are uvicorn request handlers — never Streamlit contexts.
    if "AnyIO" in thread_name:
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


# ── Remote management helpers ────────────────────────────────────────────────

def _mgmt_base(config: dict[str, Any] | None = None) -> str | None:
    """Return the management API base URL if remote mode is active, else None.

    CRITICAL RECURSION GUARD: this function is called by load_config() to
    decide whether to fetch config from the remote mgmt API or from disk.
    If the mgmt server itself calls load_config() (which it does on every
    request), _mgmt_base() MUST return None or an infinite loop results:
      mgmt_server endpoint → load_config() → _mgmt_base() → remote HTTP →
      mgmt_server endpoint → load_config() → ...

    Returns None (forcing local disk read) when ANY condition holds:
    - Not inside an active Streamlit browser session (e.g., called from
      mgmt_server uvicorn threads, CLI tools, tests)
    - UI session has the connection toggle set to "local"
    - remote_mgmt_url is not configured

    All three must be true to return the remote URL.
    """
    # Remote mode only makes sense inside an active Streamlit browser session.
    # If we're not in Streamlit (e.g. called from uvicorn/mgmt_server, a CLI
    # tool, or a test), always return None to prevent infinite recursion where
    # the mgmt API's own load_config() tries to fetch from itself.
    if not _in_streamlit():
        return None
    try:
        import streamlit as _st
        if _st.session_state.get("connection_mode", "local") == "local":
            return None
    except Exception:
        return None
    if config is None:
        config = load_config()
    url = config.get("remote_mgmt_url", "").strip()
    if not url:
        return None
    raw = url.rstrip("/")
    return _mgmt_url(raw)  # IPv4-resolved, cached


def _mgmt_headers(config: dict[str, Any] | None = None) -> dict[str, str]:
    if config is None:
        config = load_config()
    key = config.get("mgmt_api_key", "").strip()
    return {"X-Api-Key": key} if key else {}


def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _load_local_config() -> dict[str, Any]:
    """Load config from disk only — no remote fetch. Used to read connectivity settings.

    NOTE: This function reads from disk ONLY and never contacts the remote mgmt API.
    Used by mgmt_server.py to read config without triggering _mgmt_base() recursion.
    _ui.py and benchmarks use load_config() instead, which may fetch from remote.
    """
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

    # 10s TTL avoids repeated HTTP calls during fast Streamlit reruns (fragment
    # auto-refresh fires every 5s). Short enough that config changes propagate
    # quickly; long enough to save round-trips on consecutive page renders.
    # Only access session_state when we're actually inside a Streamlit context
    # to avoid ScriptRunContext warnings from the mgmt API process.
    mgmt = _mgmt_base(local)
    if mgmt:
        if _in_streamlit():
            try:
                import streamlit as _st
                cached = _st.session_state.get("_cfg_cache")
                if (cached
                        and "_cfg_ts" in _st.session_state
                        and time.monotonic() - _st.session_state["_cfg_ts"] < 10):
                    return cached
            except Exception:
                pass
        try:
            r = _http.get(f"{mgmt}/config", headers=_mgmt_headers(local), timeout=3)
            if r.status_code == 200:
                remote_cfg = r.json()
                # Preserve local UI/connectivity settings so we don't overwrite
                # the address we need to reach the remote machine.
                for keep in _LOCAL_ONLY_KEYS:
                    if keep in local:
                        remote_cfg[keep] = local[keep]
                result = {**DEFAULT_CONFIG, **remote_cfg}
                if _in_streamlit():
                    try:
                        import streamlit as _st
                        _st.session_state["_cfg_cache"] = result
                        _st.session_state["_cfg_ts"] = time.monotonic()
                    except Exception:
                        pass
                return result
        except Exception:
            pass  # Fall back to local config silently
    return local


# Keys that control how the LOCAL client reaches the REMOTE machine.
# These must NEVER be synced to the remote machine — e.g., sending
# remote_mgmt_url="http://192.168.1.42:8502" to 192.168.1.42 would make
# it call itself on every load_config(), creating an infinite loop.
# set_config() on the mgmt server filters these out (mgmt_server.py).
_LOCAL_ONLY_KEYS = frozenset({
    "remote_server_url", "remote_mgmt_url", "mgmt_api_key",
    "ui_host", "ui_port", "mgmt_port",
    "_firewall_configured",
    "auto_model_switch",
    "connection_mode",        # last-used connection target (local/remote)
    "startup_model_behavior", # startup UX preference
})


def save_config(config: dict[str, Any]) -> None:
    _ensure_state_dir()
    # Backup previous config before overwriting (gives users a recovery path)
    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.replace(CONFIG_FILE.with_suffix(".json.bak"))
        except Exception:
            pass
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Invalidate the config cache so the next load_config() fetches fresh data.
    if _in_streamlit():
        try:
            import streamlit as _st
            _st.session_state.pop("_cfg_cache", None)
            _st.session_state.pop("_cfg_ts", None)
        except Exception:
            pass
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            # Strip local-only connectivity keys so we never overwrite the
            # remote machine's own network settings with the local values.
            remote_payload = {k: v for k, v in config.items() if k not in _LOCAL_ONLY_KEYS}
            _http.post(f"{mgmt}/config", json=remote_payload,
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
    """Return the bare base URL of the inference server — no trailing slash, no /v1.

    All callers append their own path (e.g. /health, /v1/chat/completions).

    In local mode the remote_server_url saved in config is intentionally
    ignored so that a leftover remote config never hijacks the local health
    check.  This mirrors the logic in _mgmt_base().
    """
    if config is None:
        config = load_config()

    # Check connection_mode toggle, not just whether remote_server_url exists.
    # A user may have saved remote settings but explicitly disabled remote mode.
    # The toggle is their intent; the saved URL is just data.
    _use_remote = True
    if _in_streamlit():
        try:
            import streamlit as _st
            _use_remote = _st.session_state.get("connection_mode", "local") == "remote"
        except Exception:
            pass  # Fallback: assume remote (safe when remote_server_url is configured)

    if _use_remote:
        remote = config.get("remote_server_url", "").strip()
        if remote:
            # Strip trailing /v1 (or /v1/) — users often paste the OpenAI base URL
            # which includes /v1, but all our callers append /v1/... themselves.
            url = remote.rstrip("/")
            if url.endswith("/v1"):
                url = url[:-3]
            return _mgmt_url(url)  # IPv4-resolved, cached

    # Local mode: connect to the server on this machine.
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8000)
    # 0.0.0.0 is a valid bind address but not a valid outbound host on macOS.
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def check_health(config: dict[str, Any] | None = None) -> tuple[bool, dict]:
    """Returns (is_healthy, health_data). Never raises."""
    try:
        url = get_server_url(config)
        r = _http.get(f"{url}/health", timeout=2)
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
            r = _http.get(f"{mgmt}/status", headers=_mgmt_headers(cfg), timeout=3)
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
    # Only override token limits when the user explicitly changed them from defaults.
    # max_tokens and max_request_tokens both default to 32768 in the engine.
    # When both are passed, max_request_tokens must >= max_tokens — the engine
    # enforces this invariant and will error if violated.
    _max_tok = config.get("max_tokens", 32768)
    _max_req = config.get("max_request_tokens", 32768)
    if _max_req < _max_tok:
        _max_req = _max_tok
    if _max_tok != 32768 or _max_req != 32768:
        cmd += ["--max-tokens", str(_max_tok), "--max-request-tokens", str(_max_req)]
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


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if something is already listening on host:port."""
    check_host = "127.0.0.1" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((check_host, port)) == 0


def kill_stale_server(port: int, host: str = "127.0.0.1") -> tuple[bool, str]:
    """
    Find and kill whatever process is listening on port, then clean up our
    state files.  Called when the UI detects an EADDRINUSE situation.
    """
    import subprocess as _sp
    check_host = "127.0.0.1" if host == "0.0.0.0" else host
    try:
        result = _sp.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.strip().isdigit()]
        if not pids:
            PID_FILE.unlink(missing_ok=True)
            return True, f"Port {port} is no longer in use."
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(1.5)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        PID_FILE.unlink(missing_ok=True)
        return True, f"Killed stale server process(es) {pids} on port {port}."
    except Exception as e:
        return False, f"Could not kill stale server: {e}"


def start_server(config: dict[str, Any]) -> tuple[bool, str]:
    """
    Start the server as a background subprocess (local) or via mgmt API (remote).
    Returns immediately — the server loads the model asynchronously.
    """
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            # Push config to remote first so it starts with latest settings.
            # Strip local-only keys so we never overwrite remote connectivity settings.
            remote_payload = {k: v for k, v in config.items() if k not in _LOCAL_ONLY_KEYS}
            _http.post(f"{mgmt}/config", json=remote_payload, headers=_mgmt_headers(config), timeout=5)
            r = _http.post(f"{mgmt}/start", headers=_mgmt_headers(config), timeout=10)
            d = r.json()
            return d.get("ok", False), d.get("message", str(r.status_code))
        except Exception as e:
            return False, f"Could not reach management API: {e}"

    pid = _get_pid()
    if pid and _is_process_alive(pid):
        return False, "Server is already running."

    if not config.get("model", "").strip():
        return False, "No model specified. Set a model in the configuration below."

    # Check for a stale server occupying the port BEFORE spending minutes loading
    port = int(config.get("port", 8000))
    host = config.get("host", "127.0.0.1")
    if _port_in_use(port, host):
        return False, (
            f"⚠️ Port {port} is already in use by a previous server session.\n"
            f"Click **Kill stale server** below to free the port, then try again."
        )

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

    # Fail-fast check: if vllm exits immediately (bad model ID, port conflict,
    # corrupted weights), detect it within 3s and return a useful error with logs.
    # If still alive after 3s, assume it is loading (can take 1-2 minutes for
    # large models) and return success — the UI polls health separately.
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
            r = _http.post(f"{mgmt}/stop", headers=_mgmt_headers(cfg), timeout=10)
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
            r = _http.get(f"{mgmt}/logs", params={"lines": last_n_lines},
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
    # In local mode, call the inference server's /v1/status directly — bypasses
    # the mgmt API (which would just proxy it anyway, adding latency).
    # In remote mode, route through mgmt API because the caller may not have
    # direct network access to the inference server port.
    if mgmt:
        try:
            r = _http.get(f"{mgmt}/metrics", headers=_mgmt_headers(config), timeout=3)
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
        r = _http.get(f"{url}/v1/status", headers=headers, timeout=3)
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
            r = _http.get(f"{mgmt}/cache/stats", headers=_mgmt_headers(config), timeout=3)
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
        r = _http.get(f"{url}/v1/cache/stats", headers=headers, timeout=2)
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
            r = _http.delete(
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
        r = _http.delete(f"{url}{endpoint}", headers=headers, timeout=5)
        return r.status_code in (200, 204), r.json().get("status", "ok")
    except Exception as e:
        return False, str(e)


def get_memory_stats() -> dict:
    """
    Return current unified memory usage stats.
    Keys: total_gb, available_gb, used_gb, percent, pressure (low/medium/high/critical)
    In remote mode, fetches from the remote machine's management API.
    """
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = _http.get(f"{mgmt}/memory/stats", headers=_mgmt_headers(cfg), timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {"total_gb": 0, "available_gb": 0, "used_gb": 0, "percent": 0, "pressure": "unknown"}

    try:
        import psutil
        vm = psutil.virtual_memory()
        total = vm.total / (1024 ** 3)
        available = vm.available / (1024 ** 3)
        used = vm.used / (1024 ** 3)
        pct = vm.percent
        if pct < 60:
            pressure = "low"
        elif pct < 80:
            pressure = "medium"
        elif pct < 92:
            pressure = "high"
        else:
            pressure = "critical"
        return {
            "total_gb": round(total, 1),
            "available_gb": round(available, 1),
            "used_gb": round(used, 1),
            "percent": round(pct, 1),
            "pressure": pressure,
        }
    except Exception:
        return {"total_gb": 0, "available_gb": 0, "used_gb": 0, "percent": 0, "pressure": "unknown"}


def _release_system_heap() -> list[str]:
    """
    General macOS memory compression techniques — frees all heap allocations
    that are no longer referenced, returning pages to the OS.

    Runs several complementary strategies:
    - malloc_zone_pressure_relief: tells the macOS allocator to compact and
      return all free chunks in every malloc zone to the OS immediately.
    - Python GC (multiple passes) to break reference cycles first.
    - madvise MADV_FREE on anonymous mappings via ctypes if available.
    - Attempt `purge` (flushes disk-backed inactive memory; no-ops without sudo
      but harmless to try).

    Returns a list of human-readable notes about what was attempted.
    """
    import ctypes
    import gc
    import subprocess as _sp

    notes: list[str] = []

    # Pass 1 & 2: Python GC — break cycles before asking allocator to compact
    gc.collect()
    gc.collect()
    notes.append("Python GC (2 passes)")

    # macOS malloc zone pressure relief — most impactful on Apple Silicon.
    # malloc_zone_pressure_relief(zone=NULL, goal=0) → compact ALL zones,
    # return ALL available free memory to the OS kernel.
    try:
        libc = ctypes.CDLL("libSystem.B.dylib", use_errno=True)
        libc.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.malloc_zone_pressure_relief.restype = None
        libc.malloc_zone_pressure_relief(None, ctypes.c_size_t(0))
        notes.append("malloc_zone_pressure_relief (all zones)")
    except Exception as e:
        notes.append(f"malloc_zone_pressure_relief skipped: {e}")

    # MLX Metal buffer cache — only clear if MLX is already loaded in this
    # process. Importing mlx.core when it isn't loaded triggers Metal GPU
    # framework initialization (~200-500 MB of unified memory allocation),
    # which would INCREASE memory rather than freeing it.
    try:
        import sys as _sys
        if "mlx.core" in _sys.modules:
            _sys.modules["mlx.core"].clear_cache()
            notes.append("MLX Metal buffer cache cleared")
        else:
            notes.append("MLX not loaded in this process — Metal cache skip")
    except Exception:
        notes.append("MLX cache clear skipped")

    # `purge`: flushes inactive file-backed pages (disk cache), freeing RAM for
    # active use.  Requires sudo so it will fail silently in most cases, but
    # it's worth attempting; some users run the dashboard with elevated rights.
    try:
        result = _sp.run(
            ["purge"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            notes.append("macOS purge (inactive file cache flushed)")
        else:
            notes.append("purge not available without sudo (normal)")
    except Exception:
        notes.append("purge not available (normal)")

    # Final GC pass after allocator compaction
    gc.collect()
    notes.append("Python GC (final pass)")

    return notes


def force_release_memory() -> dict:
    """
    Release memory from orphaned/crashed processes and compress the system heap.
    In remote mode, proxies to the remote machine's management API.

    This does NOT stop the intentionally-running inference server. To unload
    a model and reclaim its memory, use stop_server() explicitly (or the
    Stop Server button in the UI).

    Steps:
    1. Find and terminate ORPHANED vllm_mlx / benchmark subprocesses.
       These are processes that should not exist — leftover from crashes or
       previous sessions. The active inference server (tracked by PID_FILE)
       is explicitly protected and never killed.
    2. General macOS heap compression: malloc_zone_pressure_relief (compacts
       all malloc zones and returns free chunks to the OS), Python GC, MLX
       Metal cache clear (only if MLX is already loaded), optional purge.

    Returns a dict:
      before        : memory stats before cleanup
      after         : memory stats after cleanup
      freed_gb      : estimated GB freed (OS accounting may lag slightly)
      server_stopped: always False (server is never stopped by this function)
      procs_killed  : list[dict] — pid, mem_gb, cmd for each terminated process
      heap_notes    : list[str] — what the general heap release attempted
      warnings      : list[str]
    """
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = _http.post(f"{mgmt}/memory/release", headers=_mgmt_headers(cfg), timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            before = get_memory_stats()
            return {
                "before": before, "after": before, "freed_gb": 0.0,
                "server_stopped": False, "procs_killed": [], "heap_notes": [],
                "warnings": [f"Remote release failed: {e}"],
            }

    import os as _os

    before = get_memory_stats()
    warnings: list[str] = []
    procs_killed: list[dict] = []

    # ── 1. Terminate ORPHANED vllm processes ─────────────────────────────────
    # Kill only vllm processes that are NOT the active inference server.
    # The active server PID is recorded in PID_FILE; we protect it along
    # with our own process chain so we never kill anything intentional.
    own_pid = _os.getpid()
    _protected_pids: set[int] = {own_pid}

    # Protect the active inference server if one is running
    try:
        if PID_FILE.exists():
            _active_pid = int(PID_FILE.read_text().strip())
            _protected_pids.add(_active_pid)
    except Exception:
        pass

    # Protect the full parent-process chain (app.py, shell, etc.)
    try:
        import psutil as _ps
        _p = _ps.Process(own_pid)
        while _p.ppid() not in (0, 1):
            _protected_pids.add(_p.ppid())
            _p = _ps.Process(_p.ppid())
    except Exception:
        pass

    # Protect the Streamlit subprocess (child of app.py; its cmdline contains
    # vllm_mlx path so it would match _VLLM_MARKERS without this guard).
    try:
        if STREAMLIT_PID_FILE.exists():
            _streamlit_pid = int(STREAMLIT_PID_FILE.read_text().strip())
            _protected_pids.add(_streamlit_pid)
    except Exception:
        pass

    _VLLM_MARKERS = (
        "vllm_mlx", "vllm-mlx", "vllm_mlx.benchmark", "vllm-mlx-bench",
    )

    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            try:
                pid = proc.info["pid"]
                if pid in _protected_pids:
                    continue
                cmdline = " ".join(proc.info.get("cmdline") or [])
                mem_gb = (proc.info.get("memory_info") or type("", (), {"rss": 0})()).rss / (1024 ** 3)
                is_vllm = any(m in cmdline for m in _VLLM_MARKERS)
                if is_vllm:
                    _os.kill(pid, signal.SIGTERM)
                    procs_killed.append({
                        "pid": pid,
                        "mem_gb": round(mem_gb, 1),
                        "cmd": cmdline[:120],
                        "reason": "orphaned vllm",
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                pass

        if procs_killed:
            time.sleep(1.5)
            for p in procs_killed:
                try:
                    _os.kill(p["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
    except ImportError:
        warnings.append("psutil not available — cannot scan for orphaned processes")
    except Exception as e:
        warnings.append(f"Process scan failed: {e}")

    # ── 2. General heap compression ───────────────────────────────────────────
    heap_notes = _release_system_heap()

    # Allow OS memory accounting to settle
    time.sleep(1.0)

    after = get_memory_stats()
    freed = max(0.0, round(before["used_gb"] - after["used_gb"], 1))

    return {
        "before": before,
        "after": after,
        "freed_gb": freed,
        "server_stopped": False,
        "procs_killed": procs_killed,
        "heap_notes": heap_notes,
        "warnings": warnings,
    }
