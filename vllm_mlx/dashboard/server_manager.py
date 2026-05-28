# SPDX-License-Identifier: Apache-2.0
"""
Server process lifecycle management for the vllm-mlx dashboard.

Handles starting, stopping, and monitoring the inference server subprocess.
State (PID, config, logs) is persisted to ~/.vllm_mlx_ui/.
"""

import contextlib
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

import psutil
import requests
from requests.adapters import HTTPAdapter

from vllm_mlx.dashboard.engines.registry import ENGINES, get_engine

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".vllm_mlx_ui"
PID_FILE = STATE_DIR / "server.pid"          # legacy — superseded by SERVER_STATE_FILE
SERVER_STATE_FILE = STATE_DIR / "server_state.json"  # current runtime state
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

# Last crash log captured when the inference server process dies unexpectedly.
# Persists in memory so it survives PID file cleanup across multiple status polls.
_last_crash_log: str | None = None

# Set to True while stop_server() is executing an intentional shutdown so that
# get_server_status() does not misinterpret the dead process as a crash.
_intentional_stop_in_progress: bool = False

# External API engine mode — no local process; status is managed by flags.
# Set by mgmt_server.py when the user enables the openai-compatible engine.
_external_api_mode: bool = False
_external_api_healthy: bool = False

# Lock protecting both _last_crash_log and _intentional_stop_in_progress from
# concurrent reads and writes across the Streamlit rerun thread and the
# background monitor thread.
_server_state_lock = threading.Lock()


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
        logger.warning("Operation failed", exc_info=True)
    return url


_resolved_urls: dict[str, str] = {}  # cache: original_url → ipv4_url
_resolved_urls_lock = threading.Lock()

# Short TTL cache for load_config() in local (non-Streamlit) mode.
# The /poll endpoint fires every 3 s; without this cache every poll read the
# config file from disk.  save_config() resets _local_cfg_ts to force a
# re-read on the next call.
_local_cfg_cache: dict[str, Any] | None = None
_local_cfg_ts: float = 0.0
_local_cfg_lock = threading.Lock()
_LOCAL_CFG_TTL: float = 1.5  # seconds — short enough that config changes propagate quickly


def _mgmt_url(base: str) -> str:
    """Return an IPv4-resolved version of the mgmt base URL (cached)."""
    with _resolved_urls_lock:
        if base in _resolved_urls:
            return _resolved_urls[base]
    ipv4_url = _force_ipv4_url(base)
    with _resolved_urls_lock:
        _resolved_urls[base] = ipv4_url
    return ipv4_url



_DEFAULT_CONFIG: dict[str, Any] = {
    # ── Schema versioning ───────────────────────────────────────────────────
    "config_version": 2,
    # ── Engine selection ────────────────────────────────────────────────────
    # engine_id: which inference engine to use ("vllm-mlx", "rapid-mlx", …)
    "engine_id": "vllm-mlx",
    # engine_settings: engine-specific config namespace.  Keyed by engine_id.
    # config["model"] is ALWAYS the canonical HF repo ID regardless of engine.
    # Engine-specific launch aliases go here (e.g. engine_settings["rapid-mlx"]["launch_model"]).
    "engine_settings": {},
    # ── Common settings ─────────────────────────────────────────────────────
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
    # Per-model settings overrides (e.g. {"model_id": {"trust_remote_code": true}})
    "model_settings": {},
    "embedding_model": "",
    "rerank_model": "",
    "enable_metrics": False,
    "offline": False,
    # v0.2.9: SSD KV cache tiering (spill KV blocks to disk for long-context)
    "ssd_cache_dir": "",
    "ssd_cache_max_gb": 0,
    # v0.2.9: Pre-warm KV cache on startup (reduces cold-start TTFT for agents)
    "warm_prompts": "",
    # v0.2.9: Chunked prefill tuning (tokens per prefill step)
    "prefill_step_size": 0,
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
    # Unified models directory — shared by all MLX and GGUF engines.
    # When set, used as HF_HUB_CACHE (MLX models land in models--{org}--{name}/
    # subdirs) and as the scan root for GGUF files.  Empty = use HF default
    # (~/.cache/huggingface/hub).  Ollama uses its own ~/.ollama/models/ store.
    "model_cache_dir": "",
}

# Immutable default config — prevents accidental mutation at module level.
# All callers use DEFAULT_CONFIG.copy() or {**DEFAULT_CONFIG, ...} which work
# correctly with MappingProxyType.
DEFAULT_CONFIG: MappingProxyType = MappingProxyType(_DEFAULT_CONFIG)


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
    except ImportError:
        return False
    except Exception as e:
        logger.warning("Unexpected error checking Streamlit context: %s", e, exc_info=True)
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
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
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


def _init_default_api_key() -> None:
    """Generate a random management API key on first launch.

    Called when the config file doesn't exist yet. Ensures the management
    API is never accessible without authentication when remote mode is enabled.
    """
    if CONFIG_FILE.exists():
        return
    default_key = secrets.token_urlsafe(32)
    _ensure_state_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump({**DEFAULT_CONFIG, "mgmt_api_key": default_key}, f)
    logger.info("Generated random management API key on first launch")


def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _migrate_config(saved: dict[str, Any]) -> dict[str, Any]:
    """Migrate a saved config dict to the current schema version (idempotent).

    v1 → v2:
      - Add ``engine_id`` defaulting to "vllm-mlx"
      - Add ``engine_settings`` with per-engine defaults populated from the registry
      - Add ``config_version: 2``
    """
    version = saved.get("config_version", 1)
    if version >= 2:
        return saved
    migrated = dict(saved)
    migrated["config_version"] = 2
    migrated.setdefault("engine_id", "vllm-mlx")
    migrated.setdefault("engine_settings", {})
    try:
        for eid, engine in ENGINES.items():
            if eid not in migrated["engine_settings"]:
                migrated["engine_settings"][eid] = engine.default_engine_settings()
    except Exception as e:
        logger.warning("Config migration: could not populate engine defaults: %s", e)
    logger.info("Migrated server config from v%d to v2", version)
    return migrated


def _load_local_config() -> dict[str, Any]:
    """Load config from disk only — no remote fetch. Used to read connectivity settings.

    NOTE: This function reads from disk ONLY and never contacts the remote mgmt API.
    Used by mgmt_server.py to read config without triggering _mgmt_base() recursion.
    Benchmarks use load_config() instead, which may fetch from remote.
    """
    _ensure_state_dir()
    _init_default_api_key()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            saved = _migrate_config(saved)
            merged = {**DEFAULT_CONFIG, **saved}
            # Deep-merge engine_settings so missing engine namespaces are populated.
            merged["engine_settings"] = {
                **DEFAULT_CONFIG.get("engine_settings", {}),
                **saved.get("engine_settings", {}),
            }
            return merged
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    return DEFAULT_CONFIG.copy()


def load_config() -> dict[str, Any]:
    """Load server configuration, merging remote config when in remote mode.

    In local mode reads from CONFIG_FILE on disk and merges with DEFAULT_CONFIG.
    In remote mode (active Streamlit session + connection_mode == "remote") fetches
    config from the management API and overlays local connectivity keys so the
    address used to reach the remote machine is never overwritten.

    A 10-second session-state cache prevents repeated HTTP calls on fast Streamlit
    reruns (fragment auto-refresh fires every 5 s).  A 1.5-second in-process cache
    covers local mode (mgmt_server /poll fires every 3 s and calls load_config).

    Returns:
        Merged config dict with all DEFAULT_CONFIG keys guaranteed present.
    """
    global _local_cfg_cache, _local_cfg_ts
    _ensure_state_dir()

    # Fast path: in non-Streamlit context (mgmt_server uvicorn) return the
    # in-process cached config to avoid a disk read on every /poll cycle.
    # save_config() resets _local_cfg_ts to 0.0 to force a re-read.
    if not _in_streamlit():
        with _local_cfg_lock:
            if _local_cfg_cache is not None and time.monotonic() - _local_cfg_ts < _LOCAL_CFG_TTL:
                return _local_cfg_cache

    local: dict[str, Any] = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            saved = _migrate_config(saved)
            local = {**DEFAULT_CONFIG, **saved}
            local["engine_settings"] = {
                **DEFAULT_CONFIG.get("engine_settings", {}),
                **saved.get("engine_settings", {}),
            }
        except Exception:
            logger.warning("Operation failed", exc_info=True)

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
                logger.warning("Operation failed", exc_info=True)
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
                        logger.warning("Operation failed", exc_info=True)
                return result
        except Exception:
            logger.warning("Operation failed", exc_info=True)  # Fall back to local config silently

    # Store in in-process cache for non-Streamlit context.
    if not _in_streamlit():
        with _local_cfg_lock:
            _local_cfg_cache = local
            _local_cfg_ts = time.monotonic()
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
    """Persist the given config dict to disk and optionally sync to the remote machine.

    Backs up the previous config file with a .bak suffix before overwriting.
    Invalidates the Streamlit session-state config cache so the next
    load_config() call returns fresh data.  When remote mode is active, pushes
    the config to the management API (local-only connectivity keys stripped).

    Args:
        config: Full config dict to persist.  All keys in DEFAULT_CONFIG should
            be present; extra keys are written as-is.
    """
    _ensure_state_dir()
    # Backup previous config before overwriting (gives users a recovery path)
    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.replace(CONFIG_FILE.with_suffix(".json.bak"))
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Invalidate all config caches so the next load_config() fetches fresh data.
    global _local_cfg_ts
    with _local_cfg_lock:
        _local_cfg_ts = 0.0  # force re-read on next load_config() call
    if _in_streamlit():
        try:
            import streamlit as _st
            _st.session_state.pop("_cfg_cache", None)
            _st.session_state.pop("_cfg_ts", None)
        except Exception:
            logger.warning("Operation failed", exc_info=True)
    mgmt = _mgmt_base(config)
    if mgmt:
        try:
            # Strip local-only connectivity keys so we never overwrite the
            # remote machine's own network settings with the local values.
            remote_payload = {k: v for k, v in config.items() if k not in _LOCAL_ONLY_KEYS}
            _http.post(f"{mgmt}/config", json=remote_payload,
                       headers=_mgmt_headers(config), timeout=5)
        except Exception:
            logger.warning("Operation failed", exc_info=True)  # Best effort; local save already succeeded


def _write_server_state(pid: int, config: dict[str, Any]) -> None:
    """Write runtime state to SERVER_STATE_FILE (atomic rename)."""
    state = {
        "pid": pid,
        "engine_id": config.get("engine_id", "vllm-mlx"),
        "host": config.get("host", "127.0.0.1"),
        "port": config.get("port", 8000),
        "model": config.get("model", ""),
        "started_at": time.time(),
    }
    _ensure_state_dir()
    tmp = SERVER_STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    tmp.replace(SERVER_STATE_FILE)


def _read_server_state() -> dict[str, Any] | None:
    """Read the runtime state file.  Returns None if not present or corrupted.

    Backward compat: if only the legacy PID_FILE exists (plain integer), returns a
    minimal state dict treating the engine as "vllm-mlx".

    NOTE: Does NOT validate that the recorded PID is alive — callers
    (get_server_status, stop_server) are responsible for that check so they can
    capture crash logs and attempt process adoption before declaring the server
    dead.
    """
    if SERVER_STATE_FILE.exists():
        try:
            with open(SERVER_STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not read server_state.json: %s", e)
            return None
    # Legacy: plain PID file from schema v1
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            return {"pid": pid, "engine_id": "vllm-mlx"}
        except Exception as e:
            logger.warning("Could not read legacy PID file: %s", e)
    return None


def _clear_server_state() -> None:
    SERVER_STATE_FILE.unlink(missing_ok=True)
    PID_FILE.unlink(missing_ok=True)  # also clear legacy file


def _get_pid() -> int | None:
    state = _read_server_state()
    if state:
        try:
            return int(state["pid"])
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("Malformed server state: %s", e)
    return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _try_adopt_server(port: int, host: str, config: dict[str, Any] | None = None) -> int | None:
    """If our inference server is running on *port* but we've lost its PID file
    (e.g. after a management-server restart), find the process and re-adopt it.

    Engine mismatch: if the running server was started with a different engine_id
    than the current config, return None rather than silently adopting a process
    the user can't control correctly.

    Returns the adopted PID if successful, None otherwise.
    """
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    # Quick HTTP probe — try /health first (responds faster than /v1/models),
    # then fall back to /v1/models for engines that only expose the OpenAI API.
    probe_ok = False
    for probe_path in ("/health", "/v1/models"):
        try:
            import urllib.request as _ur
            _ur.urlopen(f"http://{connect_host}:{port}{probe_path}", timeout=2).read()
            probe_ok = True
            break
        except Exception:
            continue
    if not probe_ok:
        return None  # nothing responded — don't adopt

    # Check for engine mismatch against existing state file (if any)
    if config is not None:
        existing_state = _read_server_state()
        if existing_state:
            running_engine = existing_state.get("engine_id", "vllm-mlx")
            desired_engine = config.get("engine_id", "vllm-mlx")
            if running_engine != desired_engine:
                logger.warning(
                    "Cannot adopt server: running engine=%r, desired engine=%r",
                    running_engine, desired_engine,
                )
                return None

    # Find PID of the process holding the port via lsof.
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["lsof", "-t", "-i", f"tcp:{port}", "-n", "-P"],
            text=True, stderr=_sp.DEVNULL,
        ).strip()
        for tok in out.split():
            try:
                pid = int(tok)
            except ValueError:
                continue
            if _is_process_alive(pid):
                _write_server_state(pid, config or {"host": host, "port": port})
                return pid
    except Exception:
        logger.warning("Operation failed", exc_info=True)
    return None


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
            logger.warning("Operation failed", exc_info=True)  # Fallback: assume remote (safe when remote_server_url is configured)

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
    """Returns (is_healthy, health_data). Never raises.

    Tries the engine's declared ``health_path`` first (``/health`` for most
    engines), then falls back to ``/v1/models`` for engines that only expose
    the OpenAI-compatible endpoint (e.g. LM Studio, Ollama).
    """
    try:
        if config is None:
            config = load_config()
        url = get_server_url(config)

        # Determine the primary health endpoint from the engine adapter.
        engine_id = config.get("engine_id", "vllm-mlx")
        try:
            health_path = getattr(get_engine(engine_id), "health_path", "/health")
        except Exception:
            health_path = "/health"

        # Try primary endpoint.
        try:
            r = _http.get(f"{url}{health_path}", timeout=2)
            if r.status_code == 200:
                try:
                    return True, r.json()
                except Exception:
                    return True, {}
        except Exception:
            pass

        # Fallback: if the primary wasn't /v1/models, try that too.
        if health_path != "/v1/models":
            try:
                r = _http.get(f"{url}/v1/models", timeout=2)
                if r.status_code == 200:
                    return True, {}
            except Exception:
                pass
    except Exception:
        logger.warning("check_health failed", exc_info=True)
    return False, {}


def set_server_healthy() -> None:
    """Mark the external API engine as healthy (no local process)."""
    global _external_api_mode, _external_api_healthy
    with _server_state_lock:
        _external_api_mode = True
        _external_api_healthy = True


def set_server_stopped() -> None:
    """Mark the external API engine as stopped (no local process)."""
    global _external_api_mode, _external_api_healthy
    with _server_state_lock:
        _external_api_healthy = False
        _external_api_mode = False


def get_server_status() -> dict[str, Any]:
    """Returns a status dict safe to call on every Streamlit rerun."""
    global _last_crash_log
    with _server_state_lock:
        if _external_api_mode:
            return {
                "running": _external_api_healthy,
                "healthy": _external_api_healthy,
                "pid": None,
                "health": {},
                "mode": "external_api",
            }
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
        # PID file missing — check if the server is actually running (e.g. after
        # management-server restart) and adopt it if so.
        _port = int(cfg.get("port", 8000))
        _host = cfg.get("host", "127.0.0.1")
        pid = _try_adopt_server(_port, _host)
        if pid is None:
            result: dict[str, Any] = {"running": False, "healthy": False, "pid": None, "health": {}}
            with _server_state_lock:
                if _last_crash_log:
                    result["crash_log"] = _last_crash_log
            return result
    if not _is_process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        # Only capture crash log when the stop was NOT intentional (real crash).
        # During a planned model switch/restart, _intentional_stop_in_progress is
        # True and we skip this so the UI doesn't flash a false crash banner.
        with _server_state_lock:
            intentional = _intentional_stop_in_progress
        if intentional:
            with _server_state_lock:
                _last_crash_log = None
            return {"running": False, "healthy": False, "pid": None, "health": {}}
        # Defensive check: the PID may be stale but the server could still be
        # running (e.g. process was restarted externally).  Do a direct health
        # probe before declaring a crash — if the server responds, adopt it.
        _port = int(cfg.get("port", 8000))
        _host = cfg.get("host", "127.0.0.1")
        adopted_pid = _try_adopt_server(_port, _host, cfg)
        if adopted_pid is not None:
            logger.info("Stale PID %s; adopted running server PID %s", pid, adopted_pid)
            with _server_state_lock:
                _last_crash_log = None
            healthy, health_data = check_health(cfg)
            return {
                "running": True,
                "healthy": healthy,
                "pid": adopted_pid,
                "health": health_data,
            }
        crash_log = ""
        try:
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text(errors="replace").splitlines()
                crash_log = "\n".join(lines[-40:])
        except Exception:
            logger.warning("Operation failed", exc_info=True)
        with _server_state_lock:
            _last_crash_log = crash_log or None
        return {"running": False, "healthy": False, "pid": None, "health": {}, "crash_log": crash_log}
    # Running — clear any stale crash log
    with _server_state_lock:
        _last_crash_log = None
    healthy, health_data = check_health()
    return {
        "running": True,
        "healthy": healthy,
        "pid": pid,
        "health": health_data,
    }


def _build_command(config: dict[str, Any]) -> list[str]:
    """Build the inference server launch command, delegating to the selected engine.

    The engine is determined by ``config["engine_id"]``.  Falls back to
    "vllm-mlx" if the configured engine is unknown.
    """
    engine_id = config.get("engine_id", "vllm-mlx")
    try:
        engine = get_engine(engine_id)
    except KeyError:
        logger.warning("Unknown engine_id %r — falling back to vllm-mlx", engine_id)
        engine = get_engine("vllm-mlx")
    return engine.build_command(config)


def _build_env(config: dict[str, Any]) -> dict | None:
    """Return the environment dict for the engine subprocess, or None to inherit parent env.

    If the selected engine's ``build_env()`` returns a non-empty dict, merges
    it on top of ``os.environ`` so the subprocess inherits all current vars
    plus the engine-specific overrides.  Returns ``None`` if no overrides.
    """
    engine_id = config.get("engine_id", "vllm-mlx")
    try:
        engine = get_engine(engine_id)
    except KeyError:
        return None
    extra = engine.build_env(config)
    if not extra:
        return None
    return {**os.environ, **{str(k): str(v) for k, v in extra.items()}}


def _build_cwd(config: dict[str, Any]) -> str | None:
    """Return the working directory for the engine subprocess, or None.

    Delegates to the selected engine's ``get_working_directory()``.
    Returns ``None`` meaning "inherit the parent's CWD".
    """
    engine_id = config.get("engine_id", "vllm-mlx")
    try:
        engine = get_engine(engine_id)
    except KeyError:
        return None
    return engine.get_working_directory()


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
    try:
        result = _sp.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in result.stdout.strip().split() if p.strip().isdigit()]
        if not pids:
            _clear_server_state()
            return True, f"Port {port} is no longer in use."
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
        time.sleep(1.5)
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        _clear_server_state()
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
        engine_id = config.get("engine_id", "vllm-mlx")
        try:
            eng = get_engine(engine_id)
            # Fixed-model engines (e.g. apple-fm) don't need a model ID — they
            # expose a single built-in model.  Skip the "no model" check.
            if eng.get_fixed_model_display():
                pass  # proceed without a model ID
            else:
                discovered = eng.get_discovered_models()
                if discovered:
                    # Engine auto-discovers its model — populate config
                    m = discovered[0]
                    engine_settings = dict(config.get("engine_settings", {}))
                    engine_settings.setdefault(engine_id, {})
                    engine_settings[engine_id]["launch_model"] = m.get("path", m["id"])
                    config["model"] = m["id"]
                    config["engine_settings"] = engine_settings
                    save_config(config)
                else:
                    return False, "No model specified. Set a model in the configuration below."
        except (KeyError, Exception):
            return False, "No model specified. Set a model in the configuration below."

    port = int(config.get("port", 8000))
    host = config.get("host", "127.0.0.1")

    # Check for a stale server occupying the port BEFORE spending minutes loading.
    # Brief retry loop: a just-stopped server may take a moment to release the port
    # even after the process exits (kernel socket cleanup).
    if _port_in_use(port, host):
        for _ in range(10):
            time.sleep(0.5)
            if not _port_in_use(port, host):
                break
        else:
            # Port still in use — check if it's already our inference server
            # (e.g. after a management-server restart that lost the PID file).
            adopted = _try_adopt_server(port, host, config)
            if adopted:
                return False, "Server is already running."
            return False, (
                f"⚠️ Port {port} is already in use by a previous server session.\n"
                f"Click **Kill stale server** below to free the port, then try again."
            )

    global _last_crash_log, _intentional_stop_in_progress
    save_config(config)
    _ensure_state_dir()
    with _server_state_lock:
        _last_crash_log = None  # clear any previous crash before starting fresh
        _intentional_stop_in_progress = False  # we're starting fresh

    # Pre-flight: verify the engine binary is actually available before
    # touching LOG_FILE or launching anything.  Returns a clean error
    # message instead of letting FileNotFoundError escape to the ASGI layer.
    engine_id_for_check = config.get("engine_id", "vllm-mlx")

    # "openai-compatible" is the only engine with no local process to start.
    # The proxy layer routes requests directly to the configured remote URL.
    # All other engines (ollama, llama-cpp, ds4, lmstudio, apple-fm, etc.)
    # DO launch a local process via build_command() and must not be short-circuited here.
    if engine_id_for_check == "openai-compatible":
        return True, "External API engine 'openai-compatible' ready — no local process to start."

    try:
        _chk_engine = get_engine(engine_id_for_check)
        if not _chk_engine.is_installed():
            return False, (
                f"Engine '{engine_id_for_check}' is not installed. "
                "Please install it or switch to a different engine in Settings → Engine."
            )
    except KeyError:
        pass  # unknown engine — let _build_command handle it

    cmd = _build_command(config)
    env = _build_env(config)
    cwd = _build_cwd(config)
    try:
        with open(LOG_FILE, "w") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
                cwd=cwd,
            )
    except (FileNotFoundError, OSError) as exc:
        binary = cmd[0] if cmd else "(unknown)"
        return False, (
            f"Failed to launch engine '{engine_id_for_check}': "
            f"binary '{binary}' not found. "
            "Install the engine or switch to a different one in Settings → Engine. "
            f"(Detail: {exc})"
        )
    _write_server_state(proc.pid, config)

    # Fail-fast check: if the engine exits immediately (bad model ID, port conflict,
    # corrupted weights), detect it within 3s and return a useful error with logs.
    # If still alive after 3s, assume it is loading (can take 1-2 minutes for
    # large models) and return success — the UI polls health separately.
    for _ in range(6):
        time.sleep(0.5)
        if not _is_process_alive(proc.pid):
            _clear_server_state()
            logs = "\n".join(get_logs(last_n_lines=20))
            return False, f"Server exited immediately. Check logs:\n{logs}"

    engine_id = config.get("engine_id", "vllm-mlx")
    return True, f"Server starting (PID {proc.pid}, engine={engine_id}). Loading model — this may take a minute…"


def stop_server() -> tuple[bool, str]:
    """Send SIGTERM to the server process (local) or via mgmt API (remote)."""
    global _intentional_stop_in_progress
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
        _clear_server_state()
        return False, "Server was not running (cleaned up stale state file)."

    try:
        with _server_state_lock:
            _intentional_stop_in_progress = True
        # Kill the whole process group — start_new_session=True makes the child
        # its own session/process group leader, so pid == pgid.  This ensures
        # MLX/Metal worker subprocesses (which hold GPU memory) are also killed.
        # Without this, workers survive as orphans and degrade TTFT on the next
        # model load because they compete for the same GPU memory.
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # Already gone
        for _ in range(10):
            time.sleep(0.5)
            if not _is_process_alive(pid):
                break
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Already gone
            # SIGKILL is asynchronous — wait for the kernel to actually kill the
            # process before we return to the caller.
            for _ in range(10):
                time.sleep(0.2)
                if not _is_process_alive(pid):
                    break
        # Also wait for port release: the kernel may hold the listening socket
        # briefly after process death, causing a spurious "port in use" error if
        # start_server() is called immediately after.
        port = int(cfg.get("port", 8000))
        host = cfg.get("host", "127.0.0.1")
        for _ in range(10):
            if not _port_in_use(port, host):
                break
            time.sleep(0.2)
        _clear_server_state()
        return True, "Server stopped."
    except Exception as e:
        _clear_server_state()  # clear stale state even on unexpected error
        return False, f"Error stopping server: {e}"
    finally:
        with _server_state_lock:
            _intentional_stop_in_progress = False


def get_logs(last_n_lines: int = 150) -> list[str]:
    """Return the tail of the inference server log as a list of lines.

    In remote mode fetches from the management API.  In local mode reads
    directly from LOG_FILE.

    Args:
        last_n_lines: Maximum number of trailing lines to return.

    Returns:
        A list of the most recent log lines, or a placeholder message
        when no log file exists yet.
    """
    cfg = load_config()
    mgmt = _mgmt_base(cfg)
    if mgmt:
        try:
            r = _http.get(f"{mgmt}/logs", params={"lines": last_n_lines},
                             headers=_mgmt_headers(cfg), timeout=5)
            data = r.json()
            lines = data.get("lines", data.get("logs", []))
            if isinstance(lines, str):
                return lines.splitlines()
            return list(lines)
        except Exception as e:
            logger.warning("Could not fetch remote logs", exc_info=True)
            return [f"(Could not fetch remote logs: {e})"]
    if not LOG_FILE.exists():
        return ["(No log file yet — start the server to see output here.)"]
    with open(LOG_FILE) as f:
        all_lines = f.readlines()
    return [l.rstrip("\n") for l in all_lines[-last_n_lines:]]


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
            logger.warning("Operation failed", exc_info=True)
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
        logger.debug("get_metrics: server not yet reachable at %s", url)
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
            logger.warning("Operation failed", exc_info=True)
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
        logger.warning("Operation failed", exc_info=True)
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
            logger.warning("Operation failed", exc_info=True)
        return {"total_gb": 0, "available_gb": 0, "used_gb": 0, "percent": 0, "pressure": "unknown"}

    try:
        vm = psutil.virtual_memory()
        total = vm.total / (1024 ** 3)
        available = vm.available / (1024 ** 3)
        # Use (total - available) so used_gb is consistent with vm.percent,
        # which macOS computes as (total - available) / total * 100.
        # vm.used alone under-reports on macOS because it excludes inactive/cached pages.
        used = total - available
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
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
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
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
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
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        notes.append("purge not available (normal)")

    # Final GC pass after allocator compaction
    gc.collect()
    notes.append("Python GC (final pass)")

    return notes


def force_release_memory() -> dict:
    """
    Release memory from the inference server process, orphaned processes, and
    compress the system heap.  In remote mode, proxies to the remote machine's
    management API.

    This does NOT stop the intentionally-running inference server. To unload
    a model and reclaim its memory, use stop_server() explicitly (or the
    Stop Server button in the UI).

    Steps:
    1. Call POST /v1/memory/release on the running inference server (if any).
       This runs mx.clear_cache(), Python GC, and malloc_zone_pressure_relief
       INSIDE the inference server process where the Metal buffers live.
    2. Find and terminate ORPHANED vllm_mlx / benchmark subprocesses.
    3. General macOS heap compression in this (mgmt_server) process.

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
    server_heap_notes: list[str] = []

    # ── 1. Ask the inference server to release its own Metal + heap memory ────
    # The model weights and Metal buffer pool live in the inference server
    # process — malloc_zone_pressure_relief in this process does nothing for
    # them.  Calling /v1/memory/release runs mx.clear_cache(), GC, and heap
    # compaction INSIDE that process.
    cfg_for_release = load_config()
    _server_url = get_server_url(cfg_for_release)
    _api_key = cfg_for_release.get("api_key", "")
    _auth_headers: dict[str, str] = {}
    if _api_key:
        _auth_headers["Authorization"] = f"Bearer {_api_key}"
    try:
        r = _http.post(
            f"{_server_url}/v1/memory/release",
            headers=_auth_headers,
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            server_heap_notes = [f"[inference server] {n}" for n in data.get("notes", [])]
            server_freed = data.get("freed_gb", 0.0)
            if server_freed > 0:
                server_heap_notes.insert(0, f"[inference server] freed {server_freed:.2f} GB")
        elif r.status_code == 404:
            # Older inference server — fall back to existing cache-clear endpoints
            server_heap_notes.append("[inference server] /v1/memory/release not available (older build)")
            for cache_path in ["/v1/cache/prefix", "/v1/cache"]:
                try:
                    cr = _http.delete(
                        f"{_server_url}{cache_path}",
                        headers=_auth_headers,
                        timeout=10,
                    )
                    if cr.status_code in (200, 204):
                        server_heap_notes.append(f"[inference server] {cache_path} cleared")
                except Exception:
                    logger.warning("Operation failed", exc_info=True)
        else:
            warnings.append(f"Inference server memory release returned HTTP {r.status_code}")
    except Exception as e:
        warnings.append(f"Could not reach inference server for memory release: {e}")

    # ── 2. Terminate ORPHANED vllm processes ─────────────────────────────────
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
        logger.warning("Operation failed", exc_info=True)

    # Protect the full parent-process chain (app.py, shell, etc.)
    try:
        _p = psutil.Process(own_pid)
        while _p.ppid() not in (0, 1):
            _protected_pids.add(_p.ppid())
            _p = psutil.Process(_p.ppid())
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    # Protect the Streamlit subprocess (child of app.py; its cmdline contains
    # vllm_mlx path so it would match _VLLM_MARKERS without this guard).
    try:
        if STREAMLIT_PID_FILE.exists():
            _streamlit_pid = int(STREAMLIT_PID_FILE.read_text().strip())
            _protected_pids.add(_streamlit_pid)
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    _VLLM_MARKERS = (
        "vllm_mlx", "vllm-mlx", "vllm_mlx.benchmark", "vllm-mlx-bench",
    )

    try:
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
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    _os.kill(p["pid"], signal.SIGKILL)
    except ImportError:
        warnings.append("psutil not available — cannot scan for orphaned processes")
    except Exception as e:
        warnings.append(f"Process scan failed: {e}")

    # ── 3. General heap compression (mgmt_server process) ────────────────────
    heap_notes = server_heap_notes + _release_system_heap()

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
