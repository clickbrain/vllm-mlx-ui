# SPDX-License-Identifier: Apache-2.0
"""
vllm-mlx Dashboard — Streamlit UI.

Six pages accessible from the left sidebar:
  📊 Overview   — Live server metrics and charts
  🖥️ Server     — Start / stop / configure the inference server
  📦 Models     — Search, download, and delete models
  ⚡ Benchmarks — Run benchmarks and compare results
  💬 Chat — Interactive chat with named history and model switching
  ⚙️ Settings   — HuggingFace token, refresh rate, storage info
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import signal
import subprocess
import time
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# Suppress Streamlit's "missing ScriptRunContext" warnings that are emitted by
# fragment auto-refresh threads (AnyIO worker threads). Streamlit itself marks
# these as ignorable but they flood the terminal on every 5-second refresh.
import importlib.metadata
import logging as _logging
_logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).setLevel(_logging.ERROR)

from vllm_mlx.dashboard import benchmark_runner as br
from vllm_mlx.dashboard import model_manager as mm
from vllm_mlx.dashboard import server_manager as sm

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="vllm-mlx",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — base styles (mode-specific overrides injected below)
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
.banner { padding:.75rem 1rem; border-radius:.5rem; margin-bottom:1rem; font-size:.95rem; }
.banner-green  { background:#022c22; border:1px solid #10b981; color:#6ee7b7; }
.banner-yellow { background:#2d1f00; border:1px solid #f59e0b; color:#fcd34d; }
.banner-red    { background:#2d0808; border:1px solid #ef4444; color:#fca5a5; }

div[data-testid="stMetric"] {
    background:#1c1c1e;
    border:1px solid #3a3a3c;
    padding:.9rem 1rem;
    border-radius:.6rem;
}

section[data-testid="stSidebar"] button { width:100%; }
div[data-testid="stChatMessage"] { padding:.5rem 0; }
pre { max-height:420px; overflow-y:auto; }

/* Quick Switch dropdown — taller scrollable list */
section[data-testid="stSidebar"] [data-baseweb="select"] [role="listbox"],
section[data-testid="stSidebar"] [data-baseweb="popover"] [role="listbox"] {
    max-height: 60vh !important;
}
/* Prevent long model names from being clipped in the closed selector */
section[data-testid="stSidebar"] [data-baseweb="select"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] [data-baseweb="select"] span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
}

/* Mode badge styles */
.mode-badge {
    display:inline-block;
    padding:.25rem .75rem;
    border-radius:999px;
    font-size:.8rem;
    font-weight:700;
    letter-spacing:.04em;
    text-transform:uppercase;
    margin-bottom:.5rem;
}
.mode-badge-local  { background:#0a2540; color:#60a5fa; border:1px solid #2563eb; }
.mode-badge-remote { background:#2d1500; color:#fbbf24; border:1px solid #d97706; }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------
def _init_state() -> None:
    # Restore the last-used connection mode from disk so browser refreshes
    # and app restarts don't silently revert to local mode.
    try:
        _persisted_mode = sm._load_local_config().get("connection_mode", "local")
    except Exception:
        _persisted_mode = "local"

    defaults: dict[str, Any] = {
        "page": "📊 Overview",
        "metrics_history": [],
        "system_prompt": "",
        "refresh_rate": 5,
        "hf_token": "",
        "search_results": [],
        "search_query": "",
        "preset_values": {},
        "lib_sort": "size_gb",
        "chats": {},
        "active_chat_id": None,
        # "local" or "remote" — controls which backend all API calls target.
        # Restored from disk so the user's last choice persists across refreshes.
        "connection_mode": _persisted_mode,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()


# ── Auto update check (once per session, non-blocking background thread) ────
if not st.session_state.get("_update_check_started"):
    st.session_state["_update_check_started"] = True
    import threading as _threading
    def _bg_update_check():
        try:
            from vllm_mlx.dashboard import update_checker as _uc
            _uc.check_updates()   # stores result in session_state when done
        except Exception:
            pass
    _threading.Thread(target=_bg_update_check, daemon=True).start()


def _is_remote() -> bool:
    """Return True when the user has toggled into remote mode."""
    return st.session_state.get("connection_mode", "local") == "remote"


# ---------------------------------------------------------------------------
# Mode-specific CSS — injected on every render so sidebar colours update
# immediately when the toggle is flipped.
# ---------------------------------------------------------------------------
def _inject_mode_css() -> None:
    if _is_remote():
        st.markdown(
            """
<style>
/* ── REMOTE MODE — amber/orange colour scheme ── */
section[data-testid="stSidebar"] > div:first-child {
    background: #1a0e00 !important;
    border-right: 3px solid #d97706 !important;
}
/* Primary buttons amber */
button[data-testid="baseButton-primary"] {
    background-color: #d97706 !important;
    border-color: #b45309 !important;
    color: #fff !important;
}
button[data-testid="baseButton-primary"]:hover {
    background-color: #b45309 !important;
}
/* Metric cards warm tint */
div[data-testid="stMetric"] {
    background: #1f1200 !important;
    border-color: #78350f !important;
}
</style>
""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
<style>
/* ── LOCAL MODE — blue colour scheme (default) ── */
section[data-testid="stSidebar"] > div:first-child {
    background: #0d1117 !important;
    border-right: 3px solid #2563eb !important;
}
button[data-testid="baseButton-primary"] {
    background-color: #1d4ed8 !important;
    border-color: #1e40af !important;
    color: #fff !important;
}
button[data-testid="baseButton-primary"]:hover {
    background-color: #1e40af !important;
}
</style>
""",
            unsafe_allow_html=True,
        )


_inject_mode_css()
def _api_headers(config: dict | None = None) -> dict[str, str]:
    if config is None:
        config = sm.load_config()
    key = config.get("api_key", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _banner(text: str, kind: str = "green") -> None:
    st.markdown(
        f'<div class="banner banner-{kind}">{text}</div>', unsafe_allow_html=True
    )


def _extract_tps(val) -> float | None:
    """Extract a usable tokens/sec number from a scalar or dict result."""
    if val is None:
        return None
    if isinstance(val, dict):
        # Prefer generation_mean (excludes prompt-processing overhead),
        # fall back to mean or total_throughput.
        return (
            val.get("generation_mean")
            or val.get("mean")
            or val.get("total_throughput")
        )
    return float(val) if val else None


def _extract_ttft(val) -> float | None:
    """Extract mean TTFT (ms) from a scalar or dict result."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get("mean")
    return float(val) if val else None


def _plotly_defaults(fig: go.Figure, height: int = 260) -> go.Figure:
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#F5F5F7", size=12),
        margin=dict(l=0, r=0, t=24, b=0),
        height=height,
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor="#2c2c2e", linecolor="#3a3a3c")
    fig.update_yaxes(gridcolor="#2c2c2e", linecolor="#3a3a3c")
    return fig


def _get_all_local_addresses() -> list[dict[str, str]]:
    """
    Return every routable IPv4 address on this machine, plus the mDNS .local name.

    Each entry: {"label": human-readable name, "ip": the address/hostname}
    Uses `ifconfig` on macOS (no extra dependencies).
    """
    import re as _re
    import socket as _sock
    import subprocess as _sub

    results: list[dict[str, str]] = []
    seen: set[str] = set()

    # --- parse ifconfig for all IPv4 addresses ----------------------------------
    try:
        raw = _sub.run(
            ["ifconfig"], capture_output=True, text=True, timeout=3
        ).stdout
        # Each interface block starts with "<ifname>: ..."
        # We look for: inet <ip> netmask ... [broadcast ...]
        iface = "unknown"
        for line in raw.splitlines():
            m_iface = _re.match(r'^(\S+):', line)
            if m_iface:
                iface = m_iface.group(1)
            m_inet = _re.match(r'\s+inet (\d+\.\d+\.\d+\.\d+)', line)
            if m_inet:
                ip = m_inet.group(1)
                if ip.startswith("127.") or ip in seen:
                    continue
                seen.add(ip)
                # Give a friendly label based on interface name / address range
                if iface.startswith("en"):
                    if ip.startswith("169.254."):
                        label = f"{iface} (link-local / Thunderbolt or USB-C)"
                    else:
                        label = f"{iface} (Wi-Fi / Ethernet)"
                elif iface.startswith("bridge") or iface.startswith("vmnet"):
                    label = f"{iface} (virtual network)"
                elif iface.startswith("utun") or iface.startswith("tun") or iface.startswith("ppp"):
                    label = f"{iface} (VPN)"
                elif ip.startswith("169.254."):
                    label = f"{iface} (link-local)"
                else:
                    label = iface
                results.append({"label": label, "ip": ip})
    except Exception:
        pass

    # --- fallback if ifconfig failed --------------------------------------------
    if not results:
        try:
            ip = _sock.gethostbyname(_sock.gethostname())
            if not ip.startswith("127."):
                results.append({"label": "detected IP", "ip": ip})
        except Exception:
            results.append({"label": "localhost", "ip": "127.0.0.1"})

    # --- mDNS .local hostname ---------------------------------------------------
    try:
        hostname = _sock.gethostname()
        local_name = hostname if hostname.endswith(".local") else f"{hostname}.local"
        results.append({"label": ".local mDNS (works on same network without IP)", "ip": local_name})
    except Exception:
        pass

    return results


def _connection_info_block(port: int, model: str = "", api_key: str = "", mgmt_port: int = 8502, lan_only: bool = False) -> None:
    """Render a connection info expander — prominently shows client setup values."""
    import shutil as _shutil
    addrs = _get_all_local_addresses()
    # Separate into useful categories: prefer non-link-local IPs first
    _ip_addrs = [a for a in addrs if not a["ip"].endswith(".local") and not a["ip"].startswith("169.254.")]
    _ll_addrs = [a for a in addrs if not a["ip"].endswith(".local") and a["ip"].startswith("169.254.")]
    _mdns_addrs = [a for a in addrs if a["ip"].endswith(".local")]
    _sorted_addrs = _ip_addrs + _ll_addrs + _mdns_addrs

    # Find the vllm-mlx-ui binary path for firewall instructions
    _bin_path = _shutil.which("vllm-mlx-ui") or "/opt/homebrew/bin/vllm-mlx-ui"

    with st.expander("📡 Connection info — copy these into your client", expanded=True):
        if lan_only:
            st.warning(
                "⚠️ **Server is only reachable from this Mac** (listening on localhost).  \n"
                "To allow other devices to connect: go to **Server → Configuration**, "
                "change *Listen on* to **0.0.0.0 — all interfaces**, and restart."
            )
            return

        st.markdown("### 🖥 Connecting from another Mac or device")
        st.caption(
            "On the **client machine**, open vllm-mlx-ui → ⚙️ Settings → 🔗 Remote Server "
            "and enter the values for the address you want to use:"
        )

        for a in _sorted_addrs:
            if a["ip"].endswith(".local"):
                continue  # skip .local — shown below as a fallback note
            _infer_url = f"http://{a['ip']}:{port}/v1"
            _mgmt_url = f"http://{a['ip']}:{mgmt_port}"
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(f"**{a['label']}**")
                with c2:
                    st.markdown("Inference server URL")
                    st.code(_infer_url, language="text")
                    st.markdown("Management API URL")
                    st.code(_mgmt_url, language="text")

        if _mdns_addrs:
            st.caption(
                f"💡 You can also try `{_mdns_addrs[0]['ip']}` as the hostname — "
                "but an IP address above is faster and more reliable."
            )

        if model:
            st.divider()
            st.markdown("**OpenAI-compatible client settings** (Cursor, Continue, LM Studio, etc.)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("Base URL")
                st.code(f"http://{(_ip_addrs or _ll_addrs or _mdns_addrs)[0]['ip']}:{port}/v1", language="text")
            with c2:
                st.markdown("Model")
                st.code(model, language="text")
            if api_key:
                st.markdown("API key")
                st.code(api_key, language="text")

        st.divider()
        st.markdown("#### 🔒 Firewall — allow remote connections")
        st.markdown(
            "macOS firewall may block incoming connections on port "
            f"**{mgmt_port}** (management) and **{port}** (inference).  \n"
            "Run this once in Terminal on **this Mac** to allow them:"
        )
        st.code(
            f"/usr/libexec/ApplicationFirewall/socketfilterfw --add {_bin_path}\n"
            f"/usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp {_bin_path}",
            language="bash"
        )
        st.caption(f"Binary location: `{_bin_path}`")


def _swap_model(new_model_id: str) -> None:
    """Stop the server (if running), update the model config, and restart."""
    config = sm.load_config()
    status = sm.get_server_status()

    if status["running"]:
        with st.spinner("Stopping server…"):
            sm.stop_server()
            import time as _time
            _time.sleep(2)

    # Try to fetch optimal settings for the new model
    presets: dict = {}
    try:
        with st.spinner(f"Reading model card for **{new_model_id.split('/')[-1]}**…"):
            presets = mm.get_model_presets(new_model_id)
        if presets.get("max_tokens"):
            config["max_tokens"] = presets["max_tokens"]
            config["max_request_tokens"] = presets["max_tokens"]
    except Exception:
        pass

    config["model"] = new_model_id
    sm.save_config(config)

    with st.spinner(f"Starting server with **{new_model_id.split('/')[-1]}**…"):
        ok, msg = sm.start_server(config)

    if ok:
        st.success(f"✅ Switched to **{new_model_id.split('/')[-1]}**. Model is loading — this takes 10–60 seconds.")
        if presets:
            parts = []
            if presets.get("context_length"):
                parts.append(f"Context: **{presets['context_length']:,}** tokens")
            if presets.get("architecture"):
                parts.append(f"Arch: {presets['architecture']}")
            if presets.get("bits"):
                parts.append(f"{presets['bits']}-bit")
            if presets.get("recommended_temperature"):
                parts.append(f"Temp: {presets['recommended_temperature']}")
            if presets.get("is_vision"):
                parts.append("👁 Vision model")
            if parts:
                st.info("✨ Optimal settings applied — " + " · ".join(parts))
        _connection_info_block(
            port=config.get("port", 8000),
            model=new_model_id,
            api_key=config.get("api_key", ""),
            mgmt_port=config.get("mgmt_port", 8502),
            lan_only=config.get("host", "127.0.0.1") == "127.0.0.1",
        )
        st.session_state["_swap_confirm"] = None
        import time as _time
        _time.sleep(1)
        st.rerun()
    else:
        st.error(f"Failed to start: {msg}")


# ===========================================================================
# Page: Overview
# ===========================================================================
def page_overview() -> None:
    st.title("📊 Overview")

    @st.fragment(run_every=5)
    def _overview_live() -> None:
        config = sm.load_config()
        status = sm.get_server_status()

        # Loading state — server running but model not yet ready
        if status["running"] and not status["healthy"]:
            _banner("🟡 <strong>Server starting</strong> — waiting for model to load…", "yellow")
            st.caption("Model is loading into memory. This can take up to 60 seconds.")
            col1, col2, col3, col4 = st.columns(4)
            for col, label in zip(
                [col1, col2, col3, col4],
                ["⏱ Uptime", "📨 Active", "⏳ Queued", "✅ Completed"],
            ):
                col.metric(label, "—")
            return

        if status["running"] and status["healthy"]:
            h = status["health"]
            model_display = h.get("model_name", config.get("model", "—"))
            if "/" not in model_display and config.get("model"):
                model_display = config["model"]
            _banner(
                f"🟢 <strong>Server running</strong> &nbsp;·&nbsp; "
                f"Model: <strong>{model_display}</strong> &nbsp;·&nbsp; "
                f"Type: {h.get('model_type', 'llm')} &nbsp;·&nbsp; "
                f"PID: {status['pid']}",
                "green",
            )
        else:
            _banner("🔴 <strong>Server stopped</strong> — go to <em>Server</em> to start it.", "red")

        metrics = None
        if status["running"] and status["healthy"]:
            metrics = sm.get_metrics(config.get("api_key", ""))

        col1, col2, col3, col4 = st.columns(4)

        if metrics:
            uptime = int(metrics.get("uptime_s", 0))
            h_val, rem = divmod(uptime, 3600)
            m_val, s_val = divmod(rem, 60)
            col1.metric("⏱ Uptime", f"{h_val:02d}:{m_val:02d}:{s_val:02d}")
            col2.metric("📨 Active", metrics.get("num_running", 0))
            col3.metric("⏳ Queued", metrics.get("num_waiting", 0))
            col4.metric("✅ Completed", f"{metrics.get('total_requests_processed', 0):,}")

            col5, col6, col7, col8 = st.columns(4)
            col5.metric("📝 Prompt tokens", f"{metrics.get('total_prompt_tokens', 0):,}")
            col6.metric("💬 Output tokens", f"{metrics.get('total_completion_tokens', 0):,}")
            metal = metrics.get("metal") or {}
            active_gb = metal.get("active_memory_gb")
            peak_gb = metal.get("peak_memory_gb")
            col7.metric("🔧 Metal memory", f"{active_gb:.2f} GB" if active_gb is not None else "—")
            col8.metric("📈 Peak memory", f"{peak_gb:.2f} GB" if peak_gb is not None else "—")

            st.session_state.metrics_history.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "active": metrics.get("num_running", 0),
                    "queued": metrics.get("num_waiting", 0),
                    "total": metrics.get("total_requests_processed", 0),
                    "memory_gb": active_gb or 0,
                }
            )
            if len(st.session_state.metrics_history) > 120:
                st.session_state.metrics_history = st.session_state.metrics_history[-120:]
        else:
            for col, label in zip(
                [col1, col2, col3, col4],
                ["⏱ Uptime", "📨 Active", "⏳ Queued", "✅ Completed"],
            ):
                col.metric(label, "—")

        history = st.session_state.metrics_history
        if history:
            df = pd.DataFrame(history)
            left, right = st.columns(2)

            with left:
                st.subheader("Requests over time")
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=df["time"], y=df["active"], name="Active",
                        fill="tozeroy", line=dict(color="#7C3AED", width=2),
                        fillcolor="rgba(124,58,237,0.15)",
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=df["time"], y=df["queued"], name="Queued",
                        fill="tozeroy", line=dict(color="#F59E0B", width=2),
                        fillcolor="rgba(245,158,11,0.1)",
                    )
                )
                st.plotly_chart(_plotly_defaults(fig), width="stretch")

            with right:
                st.subheader("Metal GPU memory (GB)")
                fig2 = go.Figure()
                fig2.add_trace(
                    go.Scatter(
                        x=df["time"], y=df["memory_gb"], name="Memory GB",
                        fill="tozeroy", line=dict(color="#10B981", width=2),
                        fillcolor="rgba(16,185,129,0.15)",
                    )
                )
                st.plotly_chart(_plotly_defaults(fig2), width="stretch")

        if metrics and metrics.get("requests"):
            st.subheader("Active requests")
            st.dataframe(pd.DataFrame(metrics["requests"]), width="stretch", hide_index=True)

        if status["running"] and status["healthy"]:
            try:
                cache_data = sm.get_cache_stats(config.get("api_key", ""))
                if cache_data and not cache_data.get("error"):
                    with st.expander("🗄 Cache statistics"):
                        st.json(cache_data)
            except Exception:
                pass

    _overview_live()

    # ── Memory panel ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader("🧠 Unified Memory")

    mem = sm.get_memory_stats()
    _PRESSURE_COLOR = {"low": "#10B981", "medium": "#F59E0B",
                       "high": "#EF4444", "critical": "#7F1D1D", "unknown": "#6B7280"}
    bar_color = _PRESSURE_COLOR.get(mem["pressure"], "#6B7280")
    pct = mem["percent"]
    used = mem["used_gb"]
    total = mem["total_gb"]

    st.markdown(
        f"""
        <div style='margin-bottom:6px;font-size:0.85rem;color:#9CA3AF;'>
          Used <strong style='color:{bar_color}'>{used:.1f} GB</strong>
          of {total:.1f} GB
          &nbsp;·&nbsp; <strong style='color:{bar_color}'>{pct:.0f}%</strong>
          &nbsp;·&nbsp; pressure: <strong style='color:{bar_color}'>{mem["pressure"]}</strong>
        </div>
        <div style='background:#1F2937;border-radius:6px;height:14px;width:100%;overflow:hidden;margin-bottom:12px;'>
          <div style='background:{bar_color};height:100%;width:{min(pct,100):.1f}%;
                      transition:width 0.4s ease;border-radius:6px;'></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if pct >= 80:
        _banner(
            f"⚠️ <strong>High memory pressure ({pct:.0f}%)</strong> — "
            "click <em>🧹 Release Memory</em> to free RAM from inactive processes.",
            "yellow",
        )

    if st.button("🧹 Release Memory", key="_mem_release_overview",
                 help="Stop orphaned processes, compress heap, clear MLX Metal cache"):
        with st.spinner("Releasing memory…"):
            result = sm.force_release_memory()
        b = result["before"]
        a = result["after"]
        freed = result["freed_gb"]

        if freed > 0:
            _banner(
                f"✅ Released <strong>{freed:.1f} GB</strong> "
                f"({b['used_gb']:.1f} GB → {a['used_gb']:.1f} GB used, "
                f"{a['percent']:.0f}% pressure)",
                "green",
            )
        else:
            _banner(
                f"ℹ️ Cleanup ran — memory now {a['used_gb']:.1f} GB used "
                f"({a['percent']:.0f}%). OS may reclaim more over the next few seconds.",
                "blue",
            )

        details: list[str] = []
        if result["server_stopped"]:
            details.append("• Inference server stopped")
        for p in result["procs_killed"]:
            reason = p.get("reason", "")
            details.append(
                f"• Terminated PID {p['pid']} ({p['mem_gb']:.1f} GB, {reason}): "
                f"{p['cmd'][:80]}"
            )
        details += [f"• {n}" for n in result.get("heap_notes", [])]
        if result["warnings"]:
            details += [f"⚠ {w}" for w in result["warnings"]]

        if details:
            with st.expander("Release details"):
                st.code("\n".join(details))


# ===========================================================================
# Page: Server
# ===========================================================================
def _model_selectbox(
    label: str,
    saved: str,
    candidates: list[str],
    key: str,
    help: str = "",
) -> str:
    """
    Render a selectbox for model selection.
    If ``saved`` is not in ``candidates``, it is prepended so the saved value
    is always selectable.  A trailing "✏️ Enter manually…" option lets the user
    type any model ID.
    """
    options = list(candidates)
    if saved and saved not in options:
        options.insert(0, saved)
    options_with_manual = options + ["✏️ Enter manually…"]
    cur_idx = options_with_manual.index(saved) if saved in options_with_manual else 0
    # Pre-populate to avoid default-value/session-state conflict
    if key not in st.session_state or st.session_state[key] not in options_with_manual:
        st.session_state[key] = options_with_manual[cur_idx]
    choice = st.selectbox(label, options_with_manual, key=key, help=help)
    if choice == "✏️ Enter manually…":
        return st.text_input(f"{label} (ID)", value=saved, key=f"{key}_manual",
                             placeholder="mlx-community/…")
    return choice


def page_server() -> None:
    st.title("🖥️ Server")
    config = sm.load_config()
    status = sm.get_server_status()

    # Show persistent result from previous button action (survives rerun)
    if "_srv_action_result" in st.session_state:
        ok, msg = st.session_state.pop("_srv_action_result")
        if ok:
            st.success(msg)
        else:
            st.error(msg)
            # Port-conflict: offer a one-click fix
            if "already in use" in msg or "stale server" in msg.lower():
                port = config.get("port", 8000)
                host = config.get("host", "127.0.0.1")
                if st.button(f"🔪 Kill stale server on port {port}", type="primary"):
                    killed, kmsg = sm.kill_stale_server(port, host)
                    if killed:
                        st.success(kmsg + " Click ▶ Start Server to continue.")
                    else:
                        st.error(kmsg)
                    st.rerun()
            else:
                logs = sm.get_logs(last_n_lines=30).strip()
                if logs:
                    with st.expander("📋 Server log (click to diagnose)"):
                        st.code(logs, language="text")

    def _render_status_banner(s: dict) -> None:
        """Render status banner + action buttons. Safe to call from a fragment."""
        col_status, col_btns = st.columns([3, 1])
        with col_status:
            if s["running"] and s["healthy"]:
                h = s["health"]
                # Prefer full model ID from config — health endpoint may return short name
                model_display = h.get("model_name", config.get("model", "—"))
                if "/" not in model_display and config.get("model"):
                    model_display = config["model"]
                st.success(
                    f"🟢 Running — PID {s['pid']} · "
                    f"Model: **{model_display}** · "
                    f"Type: {h.get('model_type', 'llm')}"
                )
            elif s["running"]:
                st.warning(f"🟡 Starting — PID {s['pid']} · loading model…")
                st.caption("The model is loading into memory. This can take up to 60 seconds.")
            else:
                st.error("🔴 Stopped")
                recent = sm.get_logs(last_n_lines=10).strip()
                if recent and "start the server" not in recent:
                    with st.expander("📋 Last log output (click to see why it stopped)"):
                        st.code(recent, language="text")
        with col_btns:
            if s["running"]:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("⏹ Stop", width="stretch",
                                 type="secondary", key="_stop_btn"):
                        with st.spinner("Stopping…"):
                            ok, msg = sm.stop_server()
                        st.session_state["_srv_action_result"] = (ok, msg)
                        time.sleep(0.5)
                        st.rerun()
                with c2:
                    if st.button("🔄 Restart", width="stretch",
                                 type="primary", key="_restart_btn"):
                        sel = st.session_state.get("_model_sel", "")
                        if sel and not sel.startswith("✏️"):
                            config["model"] = sel
                        elif st.session_state.get("_model_sel_manual", ""):
                            config["model"] = st.session_state["_model_sel_manual"]
                        with st.spinner("Restarting…"):
                            sm.stop_server()
                            time.sleep(2)
                            ok, msg = sm.start_server(config)
                        st.session_state["_srv_action_result"] = (ok, msg)
                        st.rerun()
            else:
                if st.button("▶ Start Server", width="stretch",
                             type="primary", key="_start_btn"):
                    sel = st.session_state.get("_model_sel", "")
                    if sel and not sel.startswith("✏️"):
                        config["model"] = sel
                    elif st.session_state.get("_model_sel_manual", ""):
                        config["model"] = st.session_state["_model_sel_manual"]
                    with st.spinner("Starting server…"):
                        ok, msg = sm.start_server(config)
                    st.session_state["_srv_action_result"] = (ok, msg)
                    st.rerun()

    # While the model is loading, poll every 3 seconds using a fragment so
    # only the small status area refreshes — not the entire page.
    if status["running"] and not status["healthy"]:
        @st.fragment(run_every=3)
        def _loading_status_fragment():
            s = sm.get_server_status()
            logs = sm.get_logs(last_n_lines=40).strip()

            # Detect port-conflict crash — stop spinning and show a fix button
            if "address already in use" in logs.lower() or "eaddrinuse" in logs.lower():
                port = config.get("port", 8000)
                host = config.get("host", "127.0.0.1")
                sm.PID_FILE.unlink(missing_ok=True)
                _banner(
                    f"🔴 <strong>Start failed</strong> — port {port} is already in use "
                    f"by a previous server session.", "red"
                )
                if st.button(f"🔪 Kill stale server on port {port}", type="primary",
                             key="kill_stale_fragment"):
                    killed, kmsg = sm.kill_stale_server(port, host)
                    if killed:
                        st.success(kmsg + " Click ▶ Start Server to try again.")
                    else:
                        st.error(kmsg)
                    st.rerun()
                return

            _render_status_banner(s)
            # Show live server log so the user can see what's happening
            if logs:
                with st.expander("📋 Server log (live)", expanded=False):
                    st.code(logs[-4000:], language="text")
            # When model finishes loading, do a full rerun to show connection info
            if s["running"] and s["healthy"]:
                st.rerun()
        _loading_status_fragment()
    else:
        _render_status_banner(status)

    # ── Connection info card ─────────────────────────────────────────────────
    if status["running"] and status["healthy"]:
        _model_loaded = status["health"].get("model_name", config.get("model", ""))
        _connection_info_block(
            port=config.get("port", 8000),
            model=_model_loaded,
            api_key=config.get("api_key", ""),
            mgmt_port=config.get("mgmt_port", 8502),
            lan_only=config.get("host", "127.0.0.1") == "127.0.0.1",
        )

    st.subheader("⚙️ Configuration")
    st.caption("Save changes, then (re)start the server to apply them.")

    # ── Model selection (outside form for live preset loading) ───────────────
    cached_models = mm.get_cached_models()
    all_model_ids = [m["id"] for m in cached_models]

    # Classify cached models by role
    emb_candidates = [m["id"] for m in cached_models
                      if any(kw in m["id"].lower()
                             for kw in ["embed", "minilm", "e5-", "bge", "gte-", "nomic"])]
    rerank_candidates = [m["id"] for m in cached_models
                         if any(kw in m["id"].lower()
                                for kw in ["rerank", "cross-encoder", "jina"])]
    # LLM candidates = everything not exclusively embedding/rerank
    llm_candidates = all_model_ids if all_model_ids else []

    st.markdown("**Main model**")
    mc1, mc2 = st.columns([4, 1])
    with mc1:
        selected_model = _model_selectbox(
            "Main model",
            saved=config.get("model", ""),
            candidates=llm_candidates,
            key="_model_sel",
            help="Select from your locally downloaded models. "
                 "Go to the Models tab to download more.",
        )
    with mc2:
        st.write("")  # vertical align
        load_presets_btn = st.button(
            "✨ Load optimal settings",
            help="Read this model's HuggingFace card and pre-fill recommended settings",
            width="stretch",
        )
        model_size = next(
            (m["size_gb"] for m in cached_models if m["id"] == selected_model), None
        )
        if model_size:
            st.caption(f"💾 {model_size:.1f} GB on disk")
        if not all_model_ids:
            st.caption("No models yet — go to **Models** tab.")

    # Preset loading
    presets: dict[str, Any] = st.session_state.get("preset_values", {})
    preset_model = st.session_state.get("_preset_for_model", "")
    if load_presets_btn and selected_model and not selected_model.startswith("✏️"):
        with st.spinner(f"Reading model card for **{selected_model.split('/')[-1]}**…"):
            presets = mm.get_model_presets(selected_model)
        st.session_state["preset_values"] = presets
        st.session_state["_preset_for_model"] = selected_model
        preset_model = selected_model

    if presets and preset_model == selected_model:
        parts = []
        if presets.get("context_length"):
            parts.append(f"Context: <strong>{presets['context_length']:,}</strong> tokens")
        if presets.get("architecture"):
            parts.append(f"Arch: {presets['architecture']}")
        if presets.get("bits"):
            parts.append(f"Quantisation: {presets['bits']}-bit")
        if presets.get("is_vision"):
            parts.append("👁 Vision / multimodal model")
        if presets.get("recommended_temperature"):
            parts.append(f"Recommended temperature: {presets['recommended_temperature']}")
        if parts:
            _banner("✨ Optimal settings loaded — " + " &nbsp;·&nbsp; ".join(parts), "green")

    st.markdown("**Optional: embedding and rerank models**")
    emb_col, rerank_col = st.columns(2)
    with emb_col:
        selected_emb_raw = _model_selectbox(
            "Embedding model",
            saved=config.get("embedding_model", ""),
            candidates=["(none)"] + emb_candidates,
            key="_emb_sel",
            help="Pre-load for /v1/embeddings. Leave as (none) if not needed.",
        )
        selected_emb = "" if selected_emb_raw == "(none)" else selected_emb_raw
    with rerank_col:
        selected_rerank_raw = _model_selectbox(
            "Rerank model",
            saved=config.get("rerank_model", ""),
            candidates=["(none)"] + rerank_candidates,
            key="_rerank_sel",
            help="Pre-load for /v1/rerank. Leave as (none) if not needed.",
        )
        selected_rerank = "" if selected_rerank_raw == "(none)" else selected_rerank_raw

    st.divider()

    # ── Configuration form ───────────────────────────────────────────────────
    with st.form("server_config_form"):
        st.markdown("**Network**")
        b1, b2 = st.columns(2)
        with b1:
            served_model_name = st.text_input(
                "Served model name (optional)",
                value=config.get("served_model_name", ""),
                help="The model name returned in /v1/models. Defaults to the model ID. "
                     "Useful when your client expects a specific name like 'gpt-4'.",
            )
            host = st.selectbox(
                "Listen on",
                ["127.0.0.1 — this Mac only", "0.0.0.0 — all network interfaces (LAN access)"],
                index=0 if config.get("host", "127.0.0.1") == "127.0.0.1" else 1,
                help="Use 0.0.0.0 to allow other devices on your network to connect.",
            )
            host_value = "127.0.0.1" if host.startswith("127") else "0.0.0.0"
        with b2:
            port = st.number_input(
                "Port", value=int(config.get("port", 8000)), min_value=1024, max_value=65535,
                help="Default is 8000. Change if another app is using that port.",
            )
            api_key = st.text_input(
                "API key (optional)",
                value=config.get("api_key", ""),
                type="password",
                help="Set a secret key to secure the server. Leave blank for no authentication.",
            )
            rate_limit = st.number_input(
                "Rate limit (requests/minute, 0 = unlimited)",
                value=int(config.get("rate_limit", 0)),
                min_value=0,
            )

        st.markdown("**Generation**")
        g1, g2 = st.columns(2)
        with g1:
            continuous_batching = st.checkbox(
                "Continuous batching",
                value=config.get("continuous_batching", False),
                help="Better throughput when serving multiple users simultaneously.",
            )
            preset_ctx = presets.get("max_tokens") if preset_model == selected_model else None
            max_tokens = st.number_input(
                "Context length (max tokens)"
                + (" ✨" if preset_ctx else ""),
                value=int(preset_ctx or config.get("max_tokens", 32768)),
                min_value=256,
                max_value=131072,
                help="Maximum number of tokens the model can process (prompt + response). "
                     "Higher = more memory. Use ✨ Load optimal settings to auto-detect.",
            )
        with g2:
            rp_opts = sm.REASONING_PARSERS
            rp_cur = config.get("reasoning_parser", "")
            reasoning_parser = st.selectbox(
                "Reasoning parser",
                rp_opts,
                index=rp_opts.index(rp_cur) if rp_cur in rp_opts else 0,
                help="Extracts hidden reasoning (e.g. DeepSeek-R1 <think> blocks) into a "
                     "separate field. Leave blank unless your model uses chain-of-thought.",
            )
            tcp_opts = sm.TOOL_CALL_PARSERS
            tcp_cur = config.get("tool_call_parser", "")
            tool_call_parser = st.selectbox(
                "Tool / function call parser",
                tcp_opts,
                index=tcp_opts.index(tcp_cur) if tcp_cur in tcp_opts else 0,
                help="Required for apps that use tool/function calling. "
                     "'auto' works for most models.",
            )

        st.markdown("**Memory & performance**")
        m1, m2 = st.columns(2)
        with m1:
            gpu_mem = st.slider(
                "GPU memory utilisation",
                min_value=0.50, max_value=0.99,
                value=float(config.get("gpu_memory_utilization", 0.90)),
                step=0.01, format="%.0f%%",
                help="What fraction of your Mac's RAM to dedicate to the model. "
                     "90% is a safe default. Increase for large models.",
            )
            enable_prefix_cache = st.checkbox(
                "Prefix cache (recommended)",
                value=config.get("enable_prefix_cache", True),
                help="Speeds up repeated prompts by caching their state. Almost always beneficial.",
            )
            cache_memory_mb = st.number_input(
                "Cache memory cap (MB, 0 = auto)",
                value=int(config.get("cache_memory_mb", 0)),
                min_value=0, step=256,
                help="Limit how much RAM the prefix cache can use. 0 = ~20% of available.",
            )
        with m2:
            kv_quant = st.checkbox(
                "KV cache quantization",
                value=config.get("kv_cache_quantization", False),
                help="Compresses the KV cache to use less RAM. Slight quality trade-off.",
            )
            use_paged = st.checkbox(
                "Paged KV cache (experimental)",
                value=config.get("use_paged_cache", False),
                help="Advanced memory management similar to vLLM. "
                     "Try this if you run out of memory with large batches.",
            )
            enable_mtp = st.checkbox(
                "Multi-token prediction (MTP)",
                value=config.get("enable_mtp", False),
                help="Generates multiple tokens at once for faster output. "
                     "Only works with models that have built-in MTP support.",
            )

        st.markdown("**Advanced**")
        a1, a2 = st.columns(2)
        with a1:
            stream_interval = st.number_input(
                "Stream interval (tokens)",
                value=int(config.get("stream_interval", 1)),
                min_value=1, max_value=64,
                help="1 = send each token as it arrives (smoothest). "
                     "Higher = batch tokens before sending (more efficient for fast clients).",
            )
            trust_remote = st.checkbox(
                "Trust remote code",
                value=config.get("trust_remote_code", False),
                help="Allow the model to run its own Python code during loading. "
                     "Only enable this if you trust the model source.",
            )
        with a2:
            force_mllm_hint = "✨ (model card suggests vision)" if presets.get("is_vision") and preset_model == selected_model else ""
            force_mllm = st.checkbox(
                f"Vision / multimodal mode (MLLM) {force_mllm_hint}",
                value=config.get("mllm", False) or (
                    bool(presets.get("is_vision")) and preset_model == selected_model
                ),
                help="Enable if your model can process images or video. "
                     "Auto-detected for most models.",
            )
            enable_metrics_flag = st.checkbox(
                "Expose Prometheus /metrics endpoint",
                value=config.get("enable_metrics", False),
                help="Enables monitoring integration for advanced users.",
            )
            offline_mode = st.checkbox(
                "Offline mode",
                value=config.get("offline", False),
                help="Never contact HuggingFace over the network. "
                     "Only use models already downloaded to your Mac.",
            )

        submitted = st.form_submit_button("💾 Save configuration", type="primary")

    if submitted:
        new_cfg = {
            **config,
            "model": selected_model,
            "served_model_name": served_model_name.strip(),
            "embedding_model": selected_emb,
            "rerank_model": selected_rerank,
            "host": host_value,
            "port": int(port),
            "api_key": api_key,
            "rate_limit": int(rate_limit),
            "continuous_batching": continuous_batching,
            "max_tokens": int(max_tokens),
            "max_request_tokens": int(max_tokens),  # must be >= max_tokens; keep in sync
            "reasoning_parser": reasoning_parser,
            "tool_call_parser": tool_call_parser,
            "gpu_memory_utilization": float(gpu_mem),
            "enable_prefix_cache": enable_prefix_cache,
            "cache_memory_mb": int(cache_memory_mb),
            "kv_cache_quantization": kv_quant,
            "use_paged_cache": use_paged,
            "enable_mtp": enable_mtp,
            "stream_interval": int(stream_interval),
            "trust_remote_code": trust_remote,
            "mllm": force_mllm,
            "enable_metrics": enable_metrics_flag,
            "offline": offline_mode,
        }
        sm.save_config(new_cfg)
        if status["running"]:
            st.warning("✅ Configuration saved.")
            if st.button("🔄 Restart Server now to apply changes", type="primary",
                         width="stretch", key="_restart_after_save"):
                with st.spinner("Restarting…"):
                    sm.stop_server()
                    time.sleep(2)
                    ok, msg = sm.start_server(new_cfg)
                st.session_state["_srv_action_result"] = (ok, msg)
                st.rerun()
        else:
            st.success("✅ Configuration saved.")

    if status["running"] and status["healthy"]:
        st.divider()
        st.subheader("🗄 Cache controls")
        cc1, cc2, _ = st.columns([1, 1, 2])
        with cc1:
            if st.button("🗑 Clear all caches", width="stretch"):
                ok, msg = sm.clear_cache("all", config.get("api_key", ""))
                st.success(msg) if ok else st.error(msg)
        with cc2:
            if st.button("🗑 Clear prefix cache", width="stretch"):
                ok, msg = sm.clear_cache("prefix", config.get("api_key", ""))
                st.success(msg) if ok else st.error(msg)

    st.divider()
    st.subheader("📋 Server logs")
    lc1, lc2 = st.columns(2)
    with lc1:
        if st.button("🔄 Refresh logs"):
            st.rerun()
    with lc2:
        n_lines = st.select_slider("Lines", [50, 100, 200, 500], value=100)
    st.code(sm.get_logs(n_lines), language=None)


# ===========================================================================
# Page: Models
# ===========================================================================
def page_models() -> None:
    st.title("📦 Models")

    tab_lib, tab_search, tab_direct = st.tabs(
        ["📚 My library", "🔍 Search mlx-community", "⬇️ Download by ID"]
    )

    # ── My library ───────────────────────────────────────────────────────────
    with tab_lib:
        st.subheader("Locally cached models")
        if st.button("🔄 Refresh library"):
            st.rerun()

        with st.spinner("Scanning cache…"):
            cached = mm.get_cached_models()

        if not cached:
            STARTER_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"
            st.markdown("### 📦 No models downloaded yet")
            st.markdown(
                "You need at least one model before you can start the server.  \n"
                "Click below to download the recommended starter model (~1.8 GB), "
                "or use the **🔍 Search** / **⬇ Download by ID** tabs to pick your own."
            )
            col_btn, col_spacer = st.columns([2, 5])
            with col_btn:
                start_dl = st.button(
                    "⬇️ Download Starter Model",
                    type="primary",
                    width="stretch",
                    help=STARTER_MODEL,
                )
            st.caption(f"Starter model: `{STARTER_MODEL}`")
            if start_dl or st.session_state.get("_starter_dl_triggered"):
                st.session_state["_starter_dl_triggered"] = True
                with st.spinner(
                    f"Downloading **{STARTER_MODEL.split('/')[-1]}**…  "
                    "This may take several minutes depending on your connection."
                ):
                    ok, msg = mm.download_model(STARTER_MODEL)
                st.session_state.pop("_starter_dl_triggered", None)
                if ok:
                    st.success(f"✅ **{STARTER_MODEL.split('/')[-1]}** downloaded! "
                               "Refresh this tab to see it in your library.")
                    st.balloons()
                else:
                    st.error(f"❌ Download failed: {msg}")
                    st.info("You can try again using the **⬇ Download by ID** tab above.")
        else:
            total_gb = sum(m["size_gb"] for m in cached)
            mc1, mc2 = st.columns(2)
            mc1.metric("Total disk used", f"{total_gb:.1f} GB")
            mc2.metric("Models cached", len(cached))
            st.caption(f"Cache: `{mm.get_hf_cache_dir()}`")

            # Disk usage pie chart
            if len(cached) > 1:
                fig_pie = px.pie(
                    pd.DataFrame(cached),
                    values="size_gb",
                    names="id",
                    title="Disk usage by model",
                    color_discrete_sequence=px.colors.qualitative.Vivid,
                )
                st.plotly_chart(_plotly_defaults(fig_pie, height=320), width="stretch")

            st.divider()

            _status_lib = sm.get_server_status()
            _lib_config = sm.load_config()
            _active_model = _lib_config.get("model", "")
            if _status_lib["running"] and _status_lib["healthy"]:
                _active_model = _status_lib["health"].get("model_name", _active_model)

            for model in cached:
                is_active = model["id"] == _active_model
                c_name, c_size, c_use, c_del = st.columns([4, 1, 1, 1])
                with c_name:
                    badge = " &nbsp;<span style='background:#10b981;color:#fff;padding:2px 7px;border-radius:4px;font-size:.75rem'>● active</span>" if is_active else ""
                    hf_url = f"https://huggingface.co/{model['id']}"
                    st.markdown(
                        f"**{model['id']}**{badge} &nbsp;"
                        f"[<small>↗ Model Card</small>]({hf_url})",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"`{model['path']}`")
                with c_size:
                    st.write(f"{model['size_gb']:.2f} GB")
                with c_use:
                    if is_active:
                        st.button("✓ Active", key=f"use_{model['id']}", disabled=True,
                                  width="stretch")
                    else:
                        if st.button(
                            "⚡ Switch",
                            key=f"use_{model['id']}",
                            width="stretch",
                            type="primary",
                            help="Switch the server to this model (restarts if running)",
                        ):
                            st.session_state["_swap_confirm"] = model["id"]
                            st.rerun()
                with c_del:
                    if st.button(
                        "🗑",
                        key=f"del_{model['id']}",
                        width="stretch",
                        help="Delete from disk",
                    ):
                        st.session_state[f"_confirm_{model['id']}"] = True

                # ── Swap confirmation ──
                if st.session_state.get("_swap_confirm") == model["id"]:
                    _short = model["id"].split("/")[-1]
                    if _status_lib["running"]:
                        st.warning(
                            f"⚡ Switch to **{_short}**? "
                            "The server will restart and the current model will be unloaded "
                            f"(~{model['size_gb']:.1f} GB will be released, new model will load)."
                        )
                    else:
                        st.info(f"Set active model to **{_short}** and start the server?")
                    sw_yes, sw_no, _ = st.columns([1, 1, 4])
                    with sw_yes:
                        if st.button("✅ Confirm", key=f"_sw_yes_{model['id']}", type="primary"):
                            _swap_model(model["id"])
                    with sw_no:
                        if st.button("Cancel", key=f"_sw_no_{model['id']}"):
                            st.session_state["_swap_confirm"] = None
                            st.rerun()

                # ── Delete confirmation ──
                if st.session_state.get(f"_confirm_{model['id']}"):
                    st.warning(
                        f"⚠️ Delete **{model['id']}** ({model['size_gb']:.2f} GB)? "
                        "This cannot be undone."
                    )
                    yes_c, no_c, _ = st.columns([1, 1, 4])
                    with yes_c:
                        if st.button("Yes, delete", key=f"_yes_{model['id']}", type="primary"):
                            with st.spinner(f"Deleting {model['id']}…"):
                                ok, msg = mm.delete_model(model["id"])
                            st.toast(msg, icon="✅" if ok else "❌")
                            st.session_state.pop(f"_confirm_{model['id']}", None)
                            time.sleep(0.5)
                            st.rerun()
                    with no_c:
                        if st.button("Cancel", key=f"_no_{model['id']}"):
                            st.session_state.pop(f"_confirm_{model['id']}", None)
                            st.rerun()
                st.divider()

    # ── Search ───────────────────────────────────────────────────────────────
    with tab_search:
        st.subheader("Search mlx-community on HuggingFace")

        q_col, btn_col = st.columns([4, 1])
        with q_col:
            query_input = st.text_input(
                "Search query",
                value=st.session_state.search_query,
                placeholder="Llama, Qwen, Gemma, Mistral, DeepSeek…",
                label_visibility="collapsed",
            )
        with btn_col:
            do_search = st.button("🔍 Search", type="primary", width="stretch")

        st.caption("Quick filters:")
        qf_cols = st.columns(8)
        for i, tag in enumerate(["Llama", "Qwen", "Gemma", "Mistral", "Phi", "DeepSeek", "Falcon", "Mamba"]):
            with qf_cols[i]:
                if st.button(tag, key=f"qf_{tag}", width="stretch"):
                    st.session_state.search_query = tag
                    st.rerun()

        if do_search:
            st.session_state.search_query = query_input
            with st.spinner("Searching HuggingFace…"):
                results = mm.search_mlx_models(query_input, limit=60)
            if results and results[0].get("error"):
                st.error(f"Search failed: {results[0]['error']}")
                st.session_state.search_results = []
            else:
                st.session_state.search_results = results

        results: list[dict] = st.session_state.search_results
        if results:
            def _bits(model_id: str, tags: list) -> int | None:
                name = model_id.lower()
                tag_str = " ".join(t.lower() for t in tags)
                for bits, pats in {
                    4: ["4bit", "4-bit", "q4_", "int4"],
                    8: ["8bit", "8-bit", "q8_", "int8"],
                    3: ["3bit", "3-bit"],
                    6: ["6bit", "6-bit"],
                    16: ["fp16", "bfloat16", "bf16"],
                }.items():
                    if any(p in name or p in tag_str for p in pats):
                        return bits
                return None

            def _params_b(model_id: str) -> float:
                m = re.search(r"[\-_]?(\d+(?:\.\d+)?)b[\-_]", model_id.lower())
                if m:
                    return float(m.group(1))
                m2 = re.search(r"(\d+(?:\.\d+)?)b$", model_id.lower().split("/")[-1])
                if m2:
                    return float(m2.group(1))
                return 0.0

            # Enrich results with computed fields
            for r in results:
                if "_bits" not in r:
                    r["_bits"] = _bits(r["id"], r.get("tags", []))
                if "_params" not in r:
                    r["_params"] = _params_b(r["id"])

            # ── Filter controls ──
            st.markdown("**Filters**")
            f1, f2, f3 = st.columns([2, 2, 2])
            with f1:
                sort_by = st.selectbox(
                    "Sort by",
                    ["⬇️ Downloads", "❤️ Likes", "🆕 Most recent", "🔤 Name (A–Z)"],
                    key="sort_res",
                )
            with f2:
                bits_options = ["Any quantization", "4-bit", "8-bit", "3-bit", "6-bit",
                                "fp16 / bf16 (full)"]
                bits_filter = st.selectbox("Quantization", bits_options, key="bits_filter")
            with f3:
                size_options = ["Any size", "< 1B params", "1–3B", "3–8B", "8–30B",
                                "30–70B", "> 70B"]
                size_filter = st.selectbox("Model size", size_options, key="size_filter")

            # Apply filters
            filtered = list(results)

            if bits_filter != "Any quantization":
                bits_map = {"4-bit": 4, "8-bit": 8, "3-bit": 3, "6-bit": 6,
                            "fp16 / bf16 (full)": 16}
                want_bits = bits_map.get(bits_filter)
                filtered = [r for r in filtered if r.get("_bits") == want_bits]

            if size_filter != "Any size":
                size_ranges = {
                    "< 1B params": (0, 1),
                    "1–3B": (1, 3),
                    "3–8B": (3, 8),
                    "8–30B": (8, 30),
                    "30–70B": (30, 70),
                    "> 70B": (70, 99999),
                }
                lo, hi = size_ranges[size_filter]
                filtered = [r for r in filtered if lo <= r.get("_params", 0) < hi]

            # Sort
            if sort_by == "⬇️ Downloads":
                filtered = sorted(filtered, key=lambda x: x.get("downloads", 0) or 0,
                                  reverse=True)
            elif sort_by == "❤️ Likes":
                filtered = sorted(filtered, key=lambda x: x.get("likes", 0) or 0,
                                  reverse=True)
            elif sort_by == "🆕 Most recent":
                filtered = sorted(filtered,
                                  key=lambda x: x.get("last_modified") or "",
                                  reverse=True)
            else:
                filtered = sorted(filtered, key=lambda x: x.get("id", ""))

            # Result count + already-downloaded indicators
            cached_ids = {m["id"] for m in mm.get_cached_models()}
            count_msg = f"**{len(filtered)}** of {len(results)} models"
            if bits_filter != "Any quantization" or size_filter != "Any size":
                count_msg += " (filtered)"
            st.write(count_msg)

            # Full-width banner for the last download result (cleared after display)
            if st.session_state.get("_dl_result"):
                _dl_ok, _dl_msg, _dl_id = st.session_state.pop("_dl_result")
                short_name = _dl_id.split("/")[-1]
                if _dl_ok:
                    st.success(f"✅ **{short_name}** downloaded successfully  \n"
                               f"`{_dl_id}`")
                else:
                    st.error(f"❌ Download failed for **{short_name}**: {_dl_msg}")

            hdr = st.columns([4, 1, 1, 1, 1, 1, 1])
            for col, label in zip(hdr, ["Model", "⬇️", "❤️", "Bits", "Fit", "Card", ""]):
                col.markdown(f"**{label}**")
            st.divider()

            for r in filtered:
                rc = st.columns([4, 1, 1, 1, 1, 1, 1])
                already = r["id"] in cached_ids
                name_str = r["id"]
                if already:
                    name_str += " ✓"
                rc[0].write(name_str)
                rc[1].write(f"{r['downloads']:,}")
                rc[2].write(f"{r['likes']:,}")
                bits_val = r.get("_bits")
                rc[3].write(f"`{bits_val}-bit`" if bits_val else "—")
                # Fit badge — fast name-only estimate, no API call
                _fit = mm.check_model_fit(r["id"], use_api=False)
                if _fit["fit_level"]:
                    _fit_label = (
                        f"{_fit['emoji']} {_fit['model_gb']:.0f} GB"
                        if _fit["model_gb"] else _fit["emoji"]
                    )
                    rc[4].write(_fit_label)
                else:
                    rc[4].write("❓")
                hf_url = f"https://huggingface.co/{r['id']}"
                rc[5].markdown(f"[↗ Card]({hf_url})")
                with rc[6]:
                    if already:
                        st.button("✓ Got it", key=f"get_{r['id']}", disabled=True,
                                  width="stretch")
                    else:
                        if st.button("⬇️ Get", key=f"get_{r['id']}", width="stretch"):
                            with st.spinner(
                                f"Downloading **{r['id'].split('/')[-1]}**… "
                                "this may take several minutes."
                            ):
                                ok, msg = mm.download_model(
                                    r["id"],
                                    hf_token=st.session_state.get("hf_token") or None,
                                )
                            st.session_state["_dl_result"] = (ok, msg, r["id"])
                            if ok:
                                st.balloons()
                            st.rerun()

    # ── Download by ID ───────────────────────────────────────────────────────
    with tab_direct:
        st.subheader("Download a model by its HuggingFace ID")
        st.markdown(
            "Browse models at "
            "[huggingface.co/mlx-community](https://huggingface.co/mlx-community) "
            "and paste the full ID below."
        )
        with st.form("direct_download_form"):
            direct_id = st.text_input(
                "Model ID",
                placeholder="mlx-community/Llama-3.2-3B-Instruct-4bit",
            )
            direct_token = st.text_input(
                "HuggingFace token (only needed for gated / private models)",
                value=st.session_state.get("hf_token", ""),
                type="password",
                help="Get yours at huggingface.co/settings/tokens",
            )
            fc1, fc2 = st.columns(2)
            check_btn = fc1.form_submit_button("🔍 Check fit before downloading")
            dl_btn = fc2.form_submit_button("⬇️ Download", type="primary")

        if (check_btn or dl_btn) and direct_id.strip():
            token = direct_token.strip() or st.session_state.get("hf_token") or None
            if token:
                st.session_state["hf_token"] = token

            # ── Fit check card ──────────────────────────────────────────────
            with st.spinner("Checking model size against your RAM…"):
                _fit = mm.check_model_fit(direct_id.strip(), hf_token=token, use_api=True)

            fit_bg = {
                mm.FIT_PERFECT:   "rgba(34,197,94,0.15)",
                mm.FIT_GOOD:      "rgba(234,179,8,0.15)",
                mm.FIT_MARGINAL:  "rgba(249,115,22,0.15)",
                mm.FIT_TOO_TIGHT: "rgba(239,68,68,0.15)",
            }.get(_fit["fit_level"] or "", "rgba(100,100,100,0.10)")

            _src_note = {
                "api":  "Size from HuggingFace Hub",
                "name": "Size estimated from model name",
                "unknown": "",
            }.get(_fit["source"], "")

            st.markdown(
                f"""<div style="border-radius:8px;padding:14px 18px;
                    background:{fit_bg};margin-bottom:12px">
                <span style="font-size:1.4em">{_fit['emoji']}</span>
                &nbsp;<strong>{_fit['label']}</strong><br>
                <small>{_fit['tip']}</small>
                {"<br><small style='opacity:.6'>(" + _src_note + ")</small>" if _src_note else ""}
                </div>""",
                unsafe_allow_html=True,
            )

            _fc1, _fc2, _fc3 = st.columns(3)
            _fc1.metric("Your RAM", f"{_fit['total_ram_gb']:.0f} GB",
                        help="Total unified memory (GPU + RAM share this pool on Apple Silicon)")
            if _fit["model_gb"]:
                _fc2.metric("Model size", f"{_fit['model_gb']:.1f} GB")
                _headroom = _fit["total_ram_gb"] - _fit["model_gb"]
                _fc3.metric("Headroom", f"{_headroom:.1f} GB",
                            delta_color="normal" if _headroom > 2 else "inverse",
                            delta="✅ ok" if _headroom > 2 else "⚠️ tight")

            if dl_btn:
                if _fit["fit_level"] == mm.FIT_TOO_TIGHT:
                    st.error(
                        "⛔ Download blocked — this model is too large for your RAM. "
                        "It will crash when you try to load it. "
                        "Choose a smaller or more-quantized variant instead."
                    )
                else:
                    with st.spinner(f"Downloading **{direct_id}**… this may take several minutes."):
                        ok, msg = mm.download_model(direct_id.strip(), hf_token=token)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.balloons()
                    else:
                        st.error(msg)
        elif dl_btn and not direct_id.strip():
            st.warning("Enter a model ID first.")


# ===========================================================================
# Page: Benchmarks
# ===========================================================================
def page_benchmarks() -> None:
    st.title("⚡ Benchmarks")

    tab_run, tab_results = st.tabs(["🚀 Run benchmark", "📊 History & charts"])

    with tab_run:
        st.subheader("Run a benchmark on your hardware")
        st.caption(
            "Measures TTFT, TPOT, tokens/sec, and memory. "
            "The benchmark loads the model itself — the inference server does not need to be running."
        )

        # ── Warn if inference server is running (double memory usage = likely OOM) ──
        _bench_status = sm.get_server_status()
        _server_running = _bench_status["running"]
        if _server_running:
            _bench_model_name = (_bench_status.get("health") or {}).get(
                "model_name", sm.load_config().get("model", "")
            )
            st.warning(
                "⚠️ **The inference server is currently running.** "
                "Benchmarking while the server is active loads a second copy of the model "
                "into GPU memory, which will likely cause an out-of-memory crash.\n\n"
                "**Stop the server before running a benchmark** to avoid crashes.",
                icon="⚠️",
            )
            if st.button("⏹ Stop server now & continue", type="primary",
                         key="_bench_stop_server"):
                with st.spinner("Stopping server…"):
                    sm.stop_server()
                st.rerun()

        cached = mm.get_cached_models()
        model_ids = [m["id"] for m in cached]
        config = sm.load_config()

        # Model selectbox is OUTSIDE the form so changing it immediately
        # reruns the page and updates the pre-flight memory check.
        if model_ids:
            cur_idx = (
                model_ids.index(config.get("model", model_ids[0]))
                if config.get("model") in model_ids
                else 0
            )
            bench_model = st.selectbox("Model to benchmark", model_ids,
                                       index=cur_idx, key="_bench_model_sel")
        else:
            bench_model = st.text_input(
                "Model to benchmark",
                value=config.get("model", ""),
                placeholder="mlx-community/Llama-3.2-3B-Instruct-4bit",
                key="_bench_model_text",
            )

        with st.form("bench_form"):
            bc1, bc2 = st.columns(2)
            with bc1:
                n_prompts = st.slider("Prompts", 1, 20, 3, help="More = more accurate average. Start low to avoid memory pressure.")
                max_tok = st.slider("Max tokens per response", 64, 1024, 128, step=64,
                                    help="Lower = less KV cache memory. Reduce if you get crashes.")
            with bc2:
                is_mllm = st.checkbox("Vision / multimodal model (MLLM)")
                is_video = st.checkbox("Video benchmark (MLLM only)")
                mem_safe = st.checkbox(
                    "🛡 Memory safe mode",
                    help="Uses 1 prompt and 64 max tokens to minimise memory pressure on large models.",
                )
                st.info(
                    "💡 Stop the inference server and close other heavy apps "
                    "before benchmarking to free GPU memory.\n\n"
                    "Results are saved automatically for comparison."
                )
            run_btn = st.form_submit_button(
                "🚀 Run benchmark", type="primary",
                disabled=_server_running,
            )
            if _server_running:
                st.caption("⛔ Stop the inference server first (button above).")

        # ── Release Memory button ────────────────────────────────────────────
        if st.button("🧹 Release Memory", key="_mem_release_bench",
                     help="Free RAM from orphaned processes and compress heap before benchmarking"):
            with st.spinner("Releasing memory…"):
                _mr = sm.force_release_memory()
            _freed = _mr["freed_gb"]
            _after = _mr["after"]
            if _freed > 0:
                st.success(
                    f"✅ Released {_freed:.1f} GB — "
                    f"{_after['used_gb']:.1f} GB used ({_after['percent']:.0f}%) now"
                )
            else:
                st.info(
                    f"Cleanup ran — {_after['used_gb']:.1f} GB used "
                    f"({_after['percent']:.0f}%). OS may reclaim more shortly."
                )

        # ── Pre-flight memory check ──────────────────────────────────────────
        if bench_model:
            _pf = br.pre_flight_check(bench_model)
            # In remote mode, override local psutil RAM values with remote machine stats
            if _is_remote():
                _remote_mem = sm.get_memory_stats()
                if _remote_mem["total_gb"] > 0:
                    _pf["total_gb"] = _remote_mem["total_gb"]
                    _pf["available_gb"] = _remote_mem["available_gb"]
                    if _pf["model_gb"]:
                        _req = _pf["model_gb"] * 1.25
                        _pf["will_fit"] = _req <= _pf["available_gb"] * 0.80
                        if not _pf["will_fit"]:
                            _pf["warning"] = (
                                f"This model needs ~{_req:.1f} GB but only "
                                f"{_pf['available_gb']:.1f} GB of "
                                f"{_pf['total_gb']:.0f} GB unified memory is available "
                                f"on the remote machine."
                            )
                        elif _req > _pf["available_gb"] * 0.60:
                            _pf["warning"] = (
                                f"This model needs ~{_req:.1f} GB and "
                                f"{_pf['available_gb']:.1f} GB is available on the remote "
                                f"machine — it will fit but memory is tight."
                            )
                        else:
                            _pf["warning"] = None
            if _pf["total_gb"] > 0:
                _mem_col1, _mem_col2, _mem_col3 = st.columns(3)
                _mem_col1.metric("Total RAM", f"{_pf['total_gb']:.0f} GB")
                _mem_col2.metric("Available RAM", f"{_pf['available_gb']:.1f} GB")
                if _pf["model_gb"]:
                    _est = _pf["model_gb"] * 1.25
                    _mem_col3.metric(
                        "Est. model memory",
                        f"{_est:.1f} GB",
                        delta=f"{'✅ fits' if _pf['will_fit'] else '❌ too large'}",
                        delta_color="normal" if _pf["will_fit"] else "inverse",
                    )
            if _pf["warning"]:
                if _pf["will_fit"] is False:
                    st.error(
                        f"❌ **Memory warning:** {_pf['warning']}\n\n"
                        "Running the benchmark will likely crash Python with a Metal OOM error. "
                        "**Restart your Mac** to reclaim leaked GPU memory, then try again — "
                        "or choose a smaller/more-quantized model."
                    )
                else:
                    st.warning(f"⚠️ {_pf['warning']}")

        if run_btn:
            output_area = st.empty()
            output_buf: list[str] = []

            def on_line(line: str) -> None:
                output_buf.append(line)
                output_area.code("".join(output_buf[-40:]), language=None)

            _run_prompts = 1 if mem_safe else n_prompts
            _run_tokens = 64 if mem_safe else max_tok

            with st.spinner(f"Benchmarking **{bench_model}**…"):
                result = br.run_benchmark(
                    model=bench_model,
                    prompts=_run_prompts,
                    max_tokens=_run_tokens,
                    is_mllm=is_mllm,
                    video=is_video,
                    output_callback=on_line,
                )

            if result.get("success", True):
                st.success("✅ Benchmark complete!")
                tps_val = _extract_tps(
                    result.get("tokens_per_second") or result.get("tps")
                )
                ttft_val = _extract_ttft(
                    result.get("ttft_ms") or result.get("time_to_first_token_ms")
                )
                if tps_val or ttft_val:
                    rc1, rc2, _ = st.columns(3)
                    if tps_val:
                        rc1.metric("Tokens / sec", f"{tps_val:.1f}")
                    if ttft_val:
                        rc2.metric("TTFT (ms)", f"{ttft_val:.0f}")
                st.json(result)
            elif result.get("error") == "out_of_memory":
                st.error(
                    "❌ **Out of GPU memory** — Python crashed with a Metal memory error.\n\n"
                    "**How to fix:**\n"
                    "1. Stop the inference server (if running) before benchmarking\n"
                    "2. Close other heavy apps (browsers, video apps, Xcode)\n"
                    "3. Restart your Mac to clear leaked GPU memory\n"
                    "4. Try a smaller or more heavily quantized version of this model\n"
                    "5. On the Server page, lower **GPU memory utilisation** to 0.80 before "
                    "starting the server, to leave more headroom for benchmarks"
                )
            else:
                st.error("Benchmark failed. See output above for details.")
                if result.get("raw_output"):
                    st.code(result["raw_output"], language=None)

    with tab_results:
        st.subheader("Benchmark history")
        hc1, hc2 = st.columns(2)
        with hc1:
            if st.button("🔄 Refresh"):
                st.rerun()
        with hc2:
            if st.button("🗑 Clear all results", type="secondary"):
                br.clear_all_results()
                st.rerun()

        results_all = br.load_results()
        if not results_all:
            st.info("No results yet. Run a benchmark to see history here.")
            return

        rows: list[dict] = []
        for i, r in enumerate(reversed(results_all)):
            row: dict[str, Any] = {
                "#": len(results_all) - i,
                "Model": (r.get("model") or "—").split("/")[-1],
                "Date": (r.get("timestamp") or "")[:16].replace("T", " "),
                "Prompts": r.get("prompts", "—"),
                "Max tokens": r.get("max_tokens", "—"),
            }
            tps_v = _extract_tps(r.get("tokens_per_second") or r.get("tps"))
            if tps_v is not None:
                row["tok/s"] = round(tps_v, 1)
            ttft_v = _extract_ttft(r.get("ttft_ms") or r.get("time_to_first_token_ms"))
            if ttft_v is not None:
                row["TTFT (ms)"] = round(ttft_v, 1)
            tpot = r.get("tpot_ms")
            if tpot is not None:
                tpot_v = tpot.get("mean") if isinstance(tpot, dict) else tpot
                if tpot_v is not None:
                    row["TPOT (ms)"] = round(float(tpot_v), 1)
            rows.append(row)

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        tps_data = [
            {
                "Model": (r.get("model") or "?").split("/")[-1],
                "tok/s": _extract_tps(r.get("tokens_per_second") or r.get("tps")) or 0,
            }
            for r in results_all
            if _extract_tps(r.get("tokens_per_second") or r.get("tps"))
        ]
        if tps_data:
            st.subheader("Throughput comparison (tokens / second)")
            fig = px.bar(
                pd.DataFrame(tps_data), x="Model", y="tok/s", color="Model",
                text="tok/s", color_discrete_sequence=px.colors.qualitative.Vivid,
            )
            fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
            st.plotly_chart(_plotly_defaults(fig, 320), width="stretch")

        ttft_data = [
            {
                "Model": (r.get("model") or "?").split("/")[-1],
                "TTFT (ms)": _extract_ttft(r.get("ttft_ms") or r.get("time_to_first_token_ms")) or 0,
            }
            for r in results_all
            if _extract_ttft(r.get("ttft_ms") or r.get("time_to_first_token_ms"))
        ]
        if ttft_data:
            st.subheader("Time to first token — lower is better")
            fig2 = px.bar(
                pd.DataFrame(ttft_data), x="Model", y="TTFT (ms)", color="Model",
                text="TTFT (ms)", color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig2.update_traces(texttemplate="%{text:.0f}", textposition="outside")
            st.plotly_chart(_plotly_defaults(fig2, 280), width="stretch")

        st.subheader("Detailed results")
        for i, r in enumerate(reversed(results_all)):
            short = (r.get("model") or "unknown").split("/")[-1]
            date_s = (r.get("timestamp") or "")[:16].replace("T", " ")
            with st.expander(f"#{len(results_all)-i} — {short}  ·  {date_s}"):
                d1, d2 = st.columns([4, 1])
                with d1:
                    st.json(r)
                with d2:
                    if st.button("🗑 Delete", key=f"del_bench_{i}"):
                        br.delete_result(len(results_all) - 1 - i)
                        st.rerun()


# ===========================================================================
# Chat history persistence helpers
# ===========================================================================
import uuid as _uuid

_CHATS_FILE = sm.STATE_DIR / "chats.json"


def _load_chats() -> dict:
    """Load persisted chat sessions from disk."""
    sm._ensure_state_dir()
    if _CHATS_FILE.exists():
        try:
            return json.loads(_CHATS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_chats(chats: dict) -> None:
    sm._ensure_state_dir()
    _CHATS_FILE.write_text(json.dumps(chats, indent=2))


def _new_chat_id() -> str:
    return str(_uuid.uuid4())[:8]


def _chat_title(messages: list) -> str:
    """Derive a short title from the first user message."""
    for m in messages:
        if m["role"] == "user":
            text = m["content"] if isinstance(m["content"], str) else ""
            return text[:40] + ("…" if len(text) > 40 else "")
    return "New chat"


# ===========================================================================
# Page: Chat
# ===========================================================================
def page_chat() -> None:
    st.title("💬 Chat")
    config = sm.load_config()
    status = sm.get_server_status()

    if not (status["running"] and status["healthy"]):
        st.warning("⚠️ The server is not running. Start it from the **Server** page first.")
        if st.button("→ Go to Server"):
            st.session_state.page = "🖥️ Server"
            st.rerun()
        return

    h = status.get("health", {})
    active_model = h.get("model_name", config.get("model", "default"))

    # Determine whether the loaded model supports vision/multimodal input.
    # Prefer the live health endpoint's model_type; fall back to the saved
    # config flag and model-ID pattern matching so the uploader shows even
    # when the health endpoint doesn't surface this field.
    _vision_patterns = {"-vl-", "-vision", "llava", "idefics", "pixtral", "qwen2-vl", "pali"}
    _is_vision = (
        h.get("model_type") == "mllm"
        or config.get("mllm", False)
        or any(p in active_model.lower() for p in _vision_patterns)
    )
    model_type = "mllm" if _is_vision else h.get("model_type", "llm")
    url = sm.get_server_url(config)

    # ── Load / init chat state ────────────────────────────────────────────────
    if "chats" not in st.session_state:
        st.session_state.chats = _load_chats()
    if "active_chat_id" not in st.session_state or \
            st.session_state.active_chat_id not in st.session_state.chats:
        new_id = _new_chat_id()
        st.session_state.chats[new_id] = {"title": "New chat", "messages": [], "model": active_model}
        st.session_state.active_chat_id = new_id
        _save_chats(st.session_state.chats)

    cid = st.session_state.active_chat_id
    chat = st.session_state.chats[cid]

    # ── Sidebar: chat list + parameters ──────────────────────────────────────
    with st.sidebar:
        st.subheader("💬 Chats")

        if st.button("➕ New chat", width="stretch", type="primary"):
            new_id = _new_chat_id()
            st.session_state.chats[new_id] = {
                "title": "New chat", "messages": [], "model": active_model, "starred": False,
            }
            st.session_state.active_chat_id = new_id
            _save_chats(st.session_state.chats)
            st.rerun()

        st.divider()

        # Sort: starred first, then most-recent (reversed insertion order)
        all_chats = list(st.session_state.chats.items())
        starred = [(cid2, cd) for cid2, cd in reversed(all_chats) if cd.get("starred")]
        unstarred = [(cid2, cd) for cid2, cd in reversed(all_chats) if not cd.get("starred")]

        def _render_chat_row(cid2: str, cd: dict) -> None:
            """Render a single chat row: [title button] [⭐] [✕]."""
            is_active = cid2 == st.session_state.active_chat_id
            is_starred = cd.get("starred", False)
            c_btn, c_star, c_del = st.columns([6, 1, 1])
            with c_btn:
                label = ("▶ " if is_active else "") + cd.get("title", "New chat")
                if st.button(label, key=f"_cbtn_{cid2}", width="stretch",
                             type="primary" if is_active else "secondary"):
                    st.session_state.active_chat_id = cid2
                    st.rerun()
            with c_star:
                star_icon = "⭐" if is_starred else "☆"
                if st.button(star_icon, key=f"_cstar_{cid2}",
                             help="Favourite / unfavourite this chat"):
                    st.session_state.chats[cid2]["starred"] = not is_starred
                    _save_chats(st.session_state.chats)
                    st.rerun()
            with c_del:
                if st.button("✕", key=f"_cdel_{cid2}", help="Delete this chat"):
                    del st.session_state.chats[cid2]
                    _save_chats(st.session_state.chats)
                    remaining = list(st.session_state.chats.keys())
                    if remaining:
                        st.session_state.active_chat_id = remaining[-1]
                    else:
                        new_id2 = _new_chat_id()
                        st.session_state.chats[new_id2] = {
                            "title": "New chat", "messages": [], "model": active_model, "starred": False,
                        }
                        st.session_state.active_chat_id = new_id2
                    _save_chats(st.session_state.chats)
                    st.rerun()

        if starred:
            st.caption("⭐ Favourites")
            for cid2, cd in starred:
                _render_chat_row(cid2, cd)
            if unstarred:
                st.caption("Recent")
        for cid2, cd in unstarred:
            _render_chat_row(cid2, cd)

        st.divider()
        st.subheader("⚙️ Parameters")

        # Model picker — allows switching model per chat
        cached_models = mm.get_cached_models()
        model_ids = [m["id"] for m in cached_models] or [active_model]
        chat_model = chat.get("model", active_model)
        if chat_model not in model_ids:
            model_ids = [chat_model] + model_ids
        sel_model = st.selectbox(
            "Model",
            model_ids,
            index=model_ids.index(chat_model) if chat_model in model_ids else 0,
            key="_chat_model_sel",
            help="The model used for this chat. Switching to a model not currently loaded "
                 "will trigger an automatic server restart.",
        )
        if sel_model != chat_model:
            chat["model"] = sel_model
            st.session_state.chats[cid] = chat
            _save_chats(st.session_state.chats)
            if sel_model != active_model:
                st.info(f"⚡ Will switch server to **{sel_model.split('/')[-1]}** on next send.")

        temperature = st.slider("Temperature", 0.0, 2.0, 0.7, 0.05, key="_chat_temp")
        max_tok = st.slider("Max tokens", 64, 8192, 512, 64, key="_chat_maxtok")
        top_p = st.slider("Top-p", 0.1, 1.0, 0.9, 0.05, key="_chat_topp")
        stream = st.checkbox("Stream response", value=True, key="_chat_stream")

        st.divider()
        # Rename current chat
        new_title = st.text_input(
            "Rename this chat",
            value=chat.get("title", ""),
            key="_chat_rename",
            max_chars=50,
        )
        if new_title and new_title != chat.get("title", ""):
            st.session_state.chats[cid]["title"] = new_title
            _save_chats(st.session_state.chats)

        if st.button("🗑 Clear messages", width="stretch", key="_chat_clear",
                     help="Clear all messages in this chat (keeps the chat entry)"):
            st.session_state.chats[cid]["messages"] = []
            _save_chats(st.session_state.chats)
            st.rerun()

    # ── If selected model differs from loaded model, offer to switch ──────────
    chat_model = chat.get("model", active_model)
    if chat_model != active_model:
        sw1, sw2 = st.columns([5, 1])
        with sw1:
            st.warning(
                f"This chat uses **{chat_model.split('/')[-1]}** but the server has "
                f"**{active_model.split('/')[-1]}** loaded."
            )
        with sw2:
            if st.button("⚡ Switch", type="primary", width="stretch", key="_chat_swbtn"):
                _swap_model(chat_model)

    st.caption(
        f"🔗 `{url}` &nbsp;·&nbsp; "
        f"Model: **{active_model}** &nbsp;·&nbsp; "
        f"Type: {model_type}"
    )

    # Text/code file types supported for all models
    _TEXT_EXTENSIONS = [
        "txt", "md", "py", "js", "ts", "jsx", "tsx", "html", "css",
        "json", "yaml", "yml", "toml", "xml", "csv", "sh", "bash",
        "c", "cpp", "h", "hpp", "java", "rs", "go", "rb", "php",
        "swift", "kt", "r", "sql", "graphql", "tf", "dockerfile",
        "ini", "cfg", "conf", "env", "log",
    ]

    sp_col, img_col = st.columns([3, 1])
    with sp_col:
        system_prompt = st.text_area(
            "System prompt (optional)",
            value=st.session_state.get("system_prompt", ""),
            height=68,
            placeholder="You are a helpful assistant.",
            key="_chat_sysprompt",
        )
        st.session_state.system_prompt = system_prompt

    uploaded_image = None
    uploaded_text_file = None

    with img_col:
        if model_type == "mllm":
            st.caption("📷 Vision model")
            uploaded_image = st.file_uploader(
                "Attach image",
                type=["jpg", "jpeg", "png", "webp", "gif"],
                help="Attach an image to your next message. The model will analyse it.",
                key="_chat_upload_img",
            )
        st.caption("📄 Attach file")
        uploaded_text_file = st.file_uploader(
            "Attach text/code file",
            type=_TEXT_EXTENSIONS,
            help="Attach a text or code file. Its content will be included in your message "
                 "as context. Files over 100 KB will be truncated.",
            key="_chat_upload_text",
        )

    messages_display = st.session_state.chats[cid].get("messages", [])
    for msg in messages_display:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"] if isinstance(msg["content"], str) else
                        next((c["text"] for c in msg["content"] if c.get("type") == "text"), ""))
            if msg.get("reasoning"):
                with st.expander("🧠 Reasoning trace"):
                    st.markdown(msg["reasoning"])
            if msg.get("usage"):
                u = msg["usage"]
                st.caption(
                    f"🔢 {u.get('prompt_tokens',0)} prompt + "
                    f"{u.get('completion_tokens',0)} completion tokens"
                )

    if prompt := st.chat_input("Type your message…"):
        # Auto-switch model if chat model differs from loaded model
        if chat_model != active_model:
            with st.spinner(f"Switching to {chat_model.split('/')[-1]}…"):
                _swap_model(chat_model)
            st.rerun()

        # Build the effective user prompt, prepending any attached text file
        effective_prompt = prompt
        if uploaded_text_file is not None:
            raw = uploaded_text_file.getvalue()
            _MAX_FILE_BYTES = 100_000
            if len(raw) > _MAX_FILE_BYTES:
                st.warning(
                    f"⚠️ **{uploaded_text_file.name}** is large ({len(raw)//1024} KB); "
                    "truncated to 100 KB."
                )
                raw = raw[:_MAX_FILE_BYTES]
            file_text = raw.decode("utf-8", errors="replace")
            fname = uploaded_text_file.name
            ext_hint = fname.rsplit(".", 1)[-1] if "." in fname else ""
            effective_prompt = (
                f"[File: {fname}]\n"
                f"```{ext_hint}\n{file_text}\n```\n\n"
                f"{prompt}"
            )

        with st.chat_message("user"):
            st.markdown(prompt)  # Show only the user's typed text in the chat bubble
            if uploaded_text_file is not None:
                st.caption(f"📄 {uploaded_text_file.name} attached")

        user_msg: Any = {"role": "user", "content": effective_prompt}
        if uploaded_image is not None:
            img_bytes = uploaded_image.getvalue()
            b64_img = base64.b64encode(img_bytes).decode()
            ext = uploaded_image.name.rsplit(".", 1)[-1].lower()
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": effective_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64_img}"}},
                ],
            }

        st.session_state.chats[cid]["messages"].append(user_msg)

        # Auto-derive title from first user message
        if len(st.session_state.chats[cid]["messages"]) == 1:
            st.session_state.chats[cid]["title"] = _chat_title([user_msg])

        api_messages: list[dict] = []
        if system_prompt.strip():
            api_messages.append({"role": "system", "content": system_prompt.strip()})
        for m in st.session_state.chats[cid]["messages"][-128:]:
            api_messages.append({"role": m["role"], "content": m["content"]})

        payload = {
            "model": active_model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tok,
            "top_p": top_p,
            "stream": stream,
        }
        headers = {"Content-Type": "application/json", **_api_headers(config)}

        with st.chat_message("assistant"):
            response_ph = st.empty()
            reasoning_ph = st.empty()
            full_response = ""
            reasoning_text = ""
            usage = None

            try:
                if stream:
                    with requests.post(
                        f"{url}/v1/chat/completions",
                        json=payload, headers=headers,
                        stream=True, timeout=120,
                    ) as resp:
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            line_str = line.decode() if isinstance(line, bytes) else line
                            if not line_str.startswith("data: "):
                                continue
                            data_s = line_str[6:]
                            if data_s == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_s)
                                delta = chunk["choices"][0].get("delta", {})
                                if delta.get("content"):
                                    full_response += delta["content"]
                                    response_ph.markdown(full_response + "▊")
                                if delta.get("reasoning"):
                                    reasoning_text += delta["reasoning"]
                            except (json.JSONDecodeError, KeyError):
                                pass
                    response_ph.markdown(full_response)
                else:
                    resp = requests.post(
                        f"{url}/v1/chat/completions",
                        json=payload, headers=headers, timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    full_response = data["choices"][0]["message"].get("content", "")
                    reasoning_text = data["choices"][0]["message"].get("reasoning", "")
                    usage = data.get("usage")
                    response_ph.markdown(full_response)

                if reasoning_text:
                    with reasoning_ph.expander("🧠 Reasoning trace"):
                        st.markdown(reasoning_text)

                if usage:
                    st.caption(
                        f"🔢 {usage.get('prompt_tokens',0)} prompt + "
                        f"{usage.get('completion_tokens',0)} completion tokens"
                    )

            except Exception as exc:
                full_response = f"❌ Error: {exc}"
                response_ph.error(full_response)

        st.session_state.chats[cid]["messages"].append(
            {
                "role": "assistant",
                "content": full_response,
                "reasoning": reasoning_text,
                "usage": usage,
            }
        )
        _save_chats(st.session_state.chats)
        st.rerun()


# ===========================================================================
# Page: Settings
# ===========================================================================
def page_settings() -> None:
    st.title("⚙️ Settings")

    # ── Updates (top — most important action) ────────────────────────────────
    from vllm_mlx.dashboard import update_checker as uc

    _method = uc._detect_install_method()
    _method_label = {"homebrew": "Homebrew", "pip": "pip"}.get(_method, "unknown")
    st.subheader("🔄 Updates")
    st.caption(f"Install method: **{_method_label}** · Updates checked automatically on startup (hourly)")

    col_force, _ = st.columns([1, 3])
    with col_force:
        if st.button("↺ Re-check now", width="stretch",
                     help="Bypass 1-hour cache and check for updates now"):
            with st.spinner("Checking…"):
                _pkgs = uc.check_updates(force=True)
            st.rerun()

    _pkgs = uc._cache.get("results", [])
    if _pkgs:
        _any_update = any(p.update_available for p in _pkgs)
        if _any_update:
            st.warning(f"🔔 **{sum(p.update_available for p in _pkgs)} update(s) available**")
        else:
            st.success("✅ Everything is up to date")

        for pkg in _pkgs:
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            c1.markdown(f"**{pkg.name}**")
            c2.markdown(f"`{pkg.installed}`")
            if pkg.update_available:
                c3.markdown(f"⬆️ `{pkg.latest}`")
                c4.markdown(f"[Notes]({pkg.url})")
            elif pkg.latest not in ("unknown", ""):
                c3.markdown(f"✓ `{pkg.latest}`")
                c4.markdown(f"[Notes]({pkg.url})")
            else:
                c3.markdown("—")
                c4.markdown("")

        if _any_update or st.session_state.get("_trigger_upgrade"):
            _cmd = uc.upgrade_command()
            # For sh -c wrappers show the inner command; for plain lists join normally
            _display_cmd = _cmd[2] if (len(_cmd) == 3 and _cmd[:2] == ["sh", "-c"]) else " ".join(_cmd)
            st.code(_display_cmd, language="bash")
            st.caption("Updates the dashboard, inference engine, and all dependencies, then relaunches automatically.")

            # Auto-trigger if coming from sidebar button
            _auto_run = st.session_state.pop("_trigger_upgrade", False)
            if st.button("⬆️ Update Now & Restart", type="primary",
                         width="content", key="_do_upgrade_btn") or _auto_run:
                _out_area = st.empty()
                _buf: list[str] = []
                with st.spinner("Upgrading — this takes 1–3 minutes…"):
                    proc = subprocess.Popen(
                        _cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    assert proc.stdout
                    for line in proc.stdout:
                        _buf.append(line)
                        _out_area.code("".join(_buf[-30:]), language=None)
                    proc.wait()

                if proc.returncode == 0:
                    st.success("✅ Update complete! Relaunching in 20 seconds…")
                    st.markdown(
                        '<meta http-equiv="refresh" content="22">',
                        unsafe_allow_html=True,
                    )
                    st.caption("If the page doesn't reload automatically, "
                               "wait a moment then refresh your browser manually.")
                    uc.relaunch()
                else:
                    full_output = "".join(_buf)
                    _linkage_warn = "Failed to fix install linkage" in full_output
                    _installed = any(
                        ("🍺" in ln or "HEAD-" in ln) and "built in" in ln
                        for ln in _buf
                    )
                    if _linkage_warn and _installed:
                        st.success(
                            "✅ Update complete (dylib relinking warning is cosmetic — "
                            "the app is fine). Relaunching in 20 seconds…"
                        )
                        st.markdown(
                            '<meta http-equiv="refresh" content="22">',
                            unsafe_allow_html=True,
                        )
                        st.caption("If the page doesn't reload automatically, "
                                   "wait a moment then refresh your browser manually.")
                        uc.relaunch()
                    else:
                        st.error(f"❌ Update failed (exit {proc.returncode}). See output above.")
    else:
        st.info("Update check is running in the background — results will appear shortly. "
                "Reload the page or click Re-check now.")

    st.divider()
    st.subheader("🔑 HuggingFace")
    hf_token = st.text_input(
        "HuggingFace token",
        value=st.session_state.get("hf_token", ""),
        type="password",
        help="Required to download gated or private models. Get yours at huggingface.co/settings/tokens",
    )
    if st.button("Save token"):
        st.session_state["hf_token"] = hf_token
        if hf_token:
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token
        else:
            os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
        st.success("Token saved for this session.")

    st.divider()
    st.subheader("📊 Dashboard")
    new_rate = st.slider(
        "Overview auto-refresh interval (seconds)",
        min_value=2, max_value=60,
        value=st.session_state.get("refresh_rate", 5),
        help="How often the Overview page polls the server for live metrics.",
    )
    if new_rate != st.session_state.get("refresh_rate", 5):
        st.session_state["refresh_rate"] = new_rate
        st.success(f"Refresh interval set to {new_rate}s.")

    st.divider()
    st.subheader("🖥️ Server Startup")
    _startup_cfg = sm.load_config()
    _startup_behavior_options = {
        "auto": "🔄 Auto-load last model (start server immediately with last used model)",
        "ask": "❓ Ask me each time (show a model picker before starting the server)",
        "none": "⏸ Manual (don't auto-start — I'll start the server when ready)",
    }
    _current_behavior = _startup_cfg.get("startup_model_behavior", "auto")
    _behavior_sel = st.radio(
        "When the app restarts, what should happen?",
        list(_startup_behavior_options.keys()),
        index=list(_startup_behavior_options.keys()).index(_current_behavior),
        format_func=lambda k: _startup_behavior_options[k],
        key="_startup_behavior_radio",
    )
    if _behavior_sel != _current_behavior:
        _startup_cfg["startup_model_behavior"] = _behavior_sel
        sm.save_config(_startup_cfg)
        st.success("Startup behavior saved. Takes effect on next restart.")

    st.divider()
    st.subheader("📁 Storage")
    state_dir = sm.STATE_DIR
    results_file = br.RESULTS_FILE
    st.markdown(
        f"| | Path |\n|---|---|\n"
        f"| Config & logs | `{state_dir}` |\n"
        f"| Benchmark results | `{results_file}` |\n"
        f"| HuggingFace cache | `{mm.get_hf_cache_dir()}` |"
    )

    try:
        total_hf = mm.get_cache_total_size()
        st.metric("HuggingFace cache total size", f"{total_hf:.2f} GB")
    except Exception:
        pass

    st.divider()
    st.subheader("🌐 Remote Access")
    st.caption(
        "Control whether the vllm-mlx dashboard itself is reachable from other "
        "devices on your network. The **inference server** has its own network "
        "setting on the Server page."
    )

    _cfg_net = sm.load_config()
    ui_host_cur = _cfg_net.get("ui_host", "127.0.0.1")
    ui_port_cur = int(_cfg_net.get("ui_port", 8501))
    mgmt_port_cur = int(_cfg_net.get("mgmt_port", 8502))

    ra1, ra2, ra3 = st.columns(3)
    with ra1:
        ui_host_sel = st.selectbox(
            "Dashboard accessible from",
            [
                "127.0.0.1 — this Mac only (recommended)",
                "0.0.0.0 — anyone on my local network",
            ],
            index=0 if ui_host_cur == "127.0.0.1" else 1,
            help="Choose '0.0.0.0' to open the dashboard to other devices on the same Wi-Fi "
                 "or Ethernet network. Do not use this on public networks.",
        )
        ui_host_val = "127.0.0.1" if ui_host_sel.startswith("127") else "0.0.0.0"
    with ra2:
        ui_port_sel = st.number_input(
            "Dashboard port",
            value=ui_port_cur,
            min_value=1024,
            max_value=65535,
            help="Port the Streamlit browser dashboard runs on. Default is 8501.",
        )
    with ra3:
        mgmt_port_sel = st.number_input(
            "Management API port",
            value=mgmt_port_cur,
            min_value=1024,
            max_value=65535,
            help=(
                "Port the management API runs on. Default is **8502**. "
                "This is the port remote clients enter in Settings → Remote Server. "
                "Must be different from the Dashboard port."
            ),
        )

    if int(ui_port_sel) == int(mgmt_port_sel):
        st.error("❌ Dashboard port and Management API port must be different.")
    else:
        _net_changed = (
            ui_host_val != ui_host_cur
            or int(ui_port_sel) != ui_port_cur
            or int(mgmt_port_sel) != mgmt_port_cur
        )

        if st.button("💾 Save & show connection info", type="primary"):
            _cfg_net["ui_host"] = ui_host_val
            _cfg_net["ui_port"] = int(ui_port_sel)
            _cfg_net["mgmt_port"] = int(mgmt_port_sel)
            sm.save_config(_cfg_net)
            if _net_changed:
                st.session_state["_net_restart_pending"] = True
            else:
                st.session_state.pop("_net_restart_pending", None)
                st.success("✅ Saved — no restart needed, settings are already applied.")

        if st.session_state.get("_net_restart_pending"):
            st.warning(
                "⚠️ **Settings saved.** The dashboard must restart to bind to the new "
                "address/port. **Do you want to restart now?**"
            )
            _rn1, _rn2, _ = st.columns([1, 1, 3])
            with _rn1:
                if st.button("🔄 Restart Now", type="primary", key="_net_restart_yes"):
                    st.session_state.pop("_net_restart_pending", None)
                    from vllm_mlx.dashboard import update_checker as _uc_net
                    st.info("Restarting dashboard… your browser will reconnect shortly.")
                    _uc_net.relaunch()
            with _rn2:
                if st.button("Later", key="_net_restart_no"):
                    st.session_state.pop("_net_restart_pending", None)
                    st.info("Settings saved. Restart vllm-mlx-ui manually when ready.")
                    st.rerun()

        if ui_host_val == "0.0.0.0":
            st.markdown("🌐 **This Mac will be reachable at these addresses:**")
            _dash_addrs = _get_all_local_addresses()
            rows = [
                f"| `{a['label']}` | `http://{a['ip']}:{int(ui_port_sel)}` | `http://{a['ip']}:{int(mgmt_port_sel)}` |"
                for a in _dash_addrs
            ]
            st.markdown(
                "| Interface | Dashboard (browser) | Management API (remote clients) |\n"
                "|-----------|--------------------|---------------------------------|\n"
                + "\n".join(rows)
            )
            st.caption(
                f"Remote clients should enter the **Management API** URL (port **{int(mgmt_port_sel)}**) "
                "in Settings → Remote Server. Use the Wi-Fi/Ethernet or Thunderbolt Bridge address."
            )
        else:
            st.info(
                f"🔒 Dashboard: **http://127.0.0.1:{int(ui_port_sel)}** (this Mac only)  \n"
                f"🔒 Management API: **http://127.0.0.1:{int(mgmt_port_sel)}** (this Mac only)"
            )

    st.divider()
    st.subheader("🔗 Remote Server")
    st.caption(
        "Configure the address of a vllm-mlx server running on **another machine**. "
        "Once saved, use the **Local / Remote toggle in the sidebar** to switch between "
        "controlling this machine or the remote one. All operations (start/stop, model "
        "downloads, logs) route to whichever target is active."
    )

    # Show current effective mode
    _cur_mode = st.session_state.get("connection_mode", "local")
    _cfg_rs = sm._load_local_config()
    _has_remote = bool(_cfg_rs.get("remote_mgmt_url", "").strip())
    if _has_remote:
        if _cur_mode == "remote":
            st.success("🌐 **Currently in REMOTE mode** — operations target the remote server. "
                       "Use the sidebar toggle to switch to Local.")
        else:
            st.info("🖥 **Currently in LOCAL mode** — operations target this machine. "
                    "Use the sidebar toggle to switch to Remote.")
    else:
        st.warning("No remote server configured yet. Fill in the fields below and save to enable the toggle.")
    # ── Parse existing saved URLs back to host + ports for pre-filling ──────────
    def _parse_host_port(url: str, default_port: int) -> tuple[str, int]:
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", url.strip())
        if m:
            return m.group(1), int(m.group(2) or default_port)
        return "", default_port

    _saved_infer_url = _cfg_rs.get("remote_server_url", "")
    _saved_mgmt_url  = _cfg_rs.get("remote_mgmt_url", "")
    _saved_host, _saved_infer_port = _parse_host_port(_saved_infer_url, 8000)
    _saved_host2, _saved_mgmt_port = _parse_host_port(_saved_mgmt_url, 8502)
    _prefill_host = _saved_host or _saved_host2

    # Pre-initialize with saved values so they are always defined before and
    # after the form block (form widgets ARE accessible outside the form since
    # the form is a submit boundary not a Python scope, but initializing here
    # ensures correct values even when the form has never been rendered).
    infer_port = _saved_infer_port
    mgmt_port_input = _saved_mgmt_port

    with st.form("remote_server_form"):
        server_addr = st.text_input(
            "Server address (IP or hostname)",
            value=_prefill_host,
            placeholder="192.168.200.1",
            help=(
                "Enter just the **IP address** of the remote Mac running vllm-mlx-ui — "
                "no `http://`, no port number.  \n"
                "Find it on the server: Settings → 📡 Connection Info.  \n"
                "A static IP (e.g. Thunderbolt Bridge `192.168.200.1`) is the most reliable."
            ),
        )

        with st.expander("⚙️ Advanced — custom ports"):
            _adv_c1, _adv_c2 = st.columns(2)
            with _adv_c1:
                infer_port = st.number_input(
                    "Inference server port", min_value=1, max_value=65535,
                    value=_saved_infer_port,
                    help="Default is 8000. Change only if the server uses a different port.",
                )
            with _adv_c2:
                mgmt_port_input = st.number_input(
                    "Management API port", min_value=1, max_value=65535,
                    value=_saved_mgmt_port,
                    help="Default is 8502. Change only if the server uses a different port.",
                )

        mgmt_api_key = st.text_input(
            "Management API key (optional)",
            value=_cfg_rs.get("mgmt_api_key", ""),
            type="password",
            help="Set this to protect the management API. Must match the key on the server.",
        )
        rs_saved = st.form_submit_button("💾 Save & test connection", type="primary")

    # Show live URL preview as the user types (re-renders on form interaction)
    _preview_host = server_addr.strip() if server_addr.strip() else _prefill_host
    if _preview_host:
        _prev_infer = f"http://{_preview_host}:{int(infer_port)}/v1"
        _prev_mgmt  = f"http://{_preview_host}:{int(mgmt_port_input)}"
        with st.container(border=True):
            st.caption("📋 URLs that will be saved:")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Inference server URL**")
                st.code(_prev_infer, language="text")
            with c2:
                st.markdown("**Management API URL**")
                st.code(_prev_mgmt, language="text")

    if rs_saved:
        _host_rs = server_addr.strip()
        if not _host_rs:
            st.error("❌ Please enter a server address.")
        else:
            from vllm_mlx.dashboard.server_manager import _force_ipv4_url, _http as _sm_http, CONFIG_FILE, _ensure_state_dir

            _infer_url_save = f"http://{_host_rs}:{int(infer_port)}"
            _mgmt_url_save  = f"http://{_host_rs}:{int(mgmt_port_input)}"

            # Auto-resolve .local hostnames to IPv4
            _resolved_mgmt = _force_ipv4_url(_mgmt_url_save)
            if _resolved_mgmt != _mgmt_url_save:
                _resolved_ip = _resolved_mgmt.split("//")[-1].split(":")[0]
                st.info(f"🔍 Hostname resolved to IPv4 `{_resolved_ip}` — saving IP directly for speed.")
                _infer_url_save = f"http://{_resolved_ip}:{int(infer_port)}"
                _mgmt_url_save  = f"http://{_resolved_ip}:{int(mgmt_port_input)}"

            _cfg_rs["remote_server_url"] = _infer_url_save
            _cfg_rs["remote_mgmt_url"]   = _mgmt_url_save
            _cfg_rs["mgmt_api_key"]      = mgmt_api_key.strip()
            _ensure_state_dir()
            CONFIG_FILE.write_text(json.dumps(_cfg_rs, indent=2))
            try:
                st.session_state.pop("_cfg_cache", None)
                st.session_state.pop("_cfg_ts", None)
            except Exception:
                pass
            st.success("✅ Saved.")

            # Test both connections and report per-URL status
            _test_results = []
            for _label, _url, _path, _expect_json in [
                ("Management API", _mgmt_url_save, "/health", True),
                ("Inference server", _infer_url_save, "/health", False),
            ]:
                try:
                    _r = _sm_http.get(f"{_url.rstrip('/')}{_path}", timeout=3)
                    if _r.status_code == 200:
                        if _expect_json:
                            _ct = _r.headers.get("content-type", "")
                            if _ct.startswith("application/json") and _r.json().get("ok"):
                                _test_results.append(("✅", _label, f"Reachable at `{_url}`"))
                            else:
                                _test_results.append(("⚠️", _label,
                                    f"Wrong service on port {int(mgmt_port_input)} — got `{_ct}`. "
                                    "This may be the Streamlit UI (port 8501), not the mgmt API."))
                        else:
                            _test_results.append(("✅", _label, f"Reachable at `{_url}`"))
                    else:
                        _test_results.append(("⚠️", _label, f"HTTP {_r.status_code}"))
                except Exception as _te:
                    _terr = str(_te)
                    if "Connection refused" in _terr:
                        if _label == "Inference server":
                            _test_results.append(("⚠️", _label,
                                "Not started — go to the **Server page** on the remote Mac and start a model. "
                                "The inference server only runs when a model is active."))
                        else:
                            _test_results.append(("❌", _label,
                                "Connection refused — is vllm-mlx-ui running on the server? "
                                "Check the firewall fix below."))
                    elif "timed out" in _terr.lower() or "timeout" in _terr.lower():
                        _test_results.append(("❌", _label, "Timed out — address unreachable. Check firewall (see below)."))
                    elif "nodename nor servname" in _terr or "Name or service" in _terr:
                        _test_results.append(("❌", _label, "Hostname not found — try using an IP address instead."))
                    else:
                        _test_results.append(("❌", _label, f"Error: `{_terr[:120]}`"))

            for _icon, _lbl, _msg in _test_results:
                if _icon == "✅":
                    st.success(f"{_icon} **{_lbl}:** {_msg}")
                elif _icon == "⚠️":
                    st.warning(f"{_icon} **{_lbl}:** {_msg}")
                else:
                    st.error(f"{_icon} **{_lbl}:** {_msg}")

            _any_failed = any(r[0] == "❌" for r in _test_results)
            if _any_failed:
                import shutil as _shutil_fw
                _bin_fw = _shutil_fw.which("vllm-mlx-ui") or "/opt/homebrew/bin/vllm-mlx-ui"
                st.markdown(
                    "**🔒 Firewall fix — run this on the server Mac:**\n"
                    "```bash\n"
                    f"sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add {_bin_fw}\n"
                    f"sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp {_bin_fw}\n"
                    "```\n"
                    f"Binary location: `{_bin_fw}`  \n\n"
                    "Or: **System Settings → Network → Firewall → Options → + → "
                    f"select `{_bin_fw}` → Allow incoming connections**"
                )

    elif _prefill_host:
        # Show last saved test result passively if we have a configured remote
        from vllm_mlx.dashboard.server_manager import _http as _sm_http
        _passive_mgmt = _cfg_rs.get("remote_mgmt_url", "")
        if _passive_mgmt:
            try:
                _r2 = _sm_http.get(f"{_passive_mgmt.rstrip('/')}/health", timeout=2)
                if _r2.status_code == 200 and _r2.headers.get("content-type","").startswith("application/json") and _r2.json().get("ok"):
                    st.success(f"✅ Management API reachable at `{_passive_mgmt}`")
                else:
                    st.warning(f"⚠️ Management API at `{_passive_mgmt}` returned HTTP {_r2.status_code}")
            except Exception:
                st.warning(f"⚠️ Cannot reach management API at `{_passive_mgmt}` — check server is running and firewall allows connections.")

    st.divider()
    st.subheader("🔒 Firewall — Allow Remote Connections")
    import shutil as _shutil_fw2
    _bin_path_fw = _shutil_fw2.which("vllm-mlx-ui") or "/opt/homebrew/bin/vllm-mlx-ui"
    _cfg_fw = sm._load_local_config()
    _fw_done = _cfg_fw.get("_firewall_configured", False)

    if _fw_done:
        st.success(
            "✅ Firewall exception was previously configured for this app.  \n"
            "If remote connections still fail, click **Re-apply** below."
        )
    else:
        st.info(
            "To let another Mac connect to this one, macOS firewall must allow "
            f"**{_bin_path_fw}** to accept incoming connections.  \n"
            "Click the button below — you'll be prompted for your Mac password once."
        )

    _fw_c1, _fw_c2, _ = st.columns([1, 1, 3])
    with _fw_c1:
        _fw_label = "✅ Re-apply Firewall Rule" if _fw_done else "🔒 Fix Firewall (one-time)"
        if st.button(_fw_label, type="primary" if not _fw_done else "secondary", key="_fw_btn"):
            from vllm_mlx.dashboard.server_manager import CONFIG_FILE, _ensure_state_dir
            try:
                _res = subprocess.run([
                    "osascript", "-e",
                    f'do shell script "/usr/libexec/ApplicationFirewall/socketfilterfw --add {_bin_path_fw!r} '
                    f'&& /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp {_bin_path_fw!r}" '
                    f'with administrator privileges'
                ], capture_output=True, text=True, timeout=60)
                if _res.returncode == 0:
                    _cfg_fw["_firewall_configured"] = True
                    _ensure_state_dir()
                    CONFIG_FILE.write_text(json.dumps(_cfg_fw, indent=2))
                    # Invalidate cache so the next load_config() sees the updated flag.
                    try:
                        st.session_state.pop("_cfg_cache", None)
                        st.session_state.pop("_cfg_ts", None)
                    except Exception:
                        pass
                    st.success("✅ Firewall rule applied! Remote clients can now connect.")
                    st.rerun()
                else:
                    _errmsg = _res.stderr.strip() or _res.stdout.strip()
                    if "User canceled" in _errmsg or "(-128)" in _errmsg:
                        st.warning("⚠️ Cancelled — no changes made. Run manually (see below).")
                    else:
                        st.error(f"❌ Could not apply rule: `{_errmsg[:200]}`")
            except Exception as _fw_err:
                st.error(f"❌ Failed: `{str(_fw_err)[:200]}`")

    with _fw_c2:
        with st.expander("📋 Manual steps"):
            st.markdown(
                "Run this in Terminal on **this Mac**:\n"
                "```bash\n"
                f"sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add {_bin_path_fw}\n"
                f"sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp {_bin_path_fw}\n"
                "```\n"
                "Or: **System Settings → Network → Firewall → Options → + →** "
                f"navigate to `{_bin_path_fw}` → **Allow incoming connections**  \n\n"
                f"App binary: `{_bin_path_fw}`"
            )

    st.divider()
    st.subheader("🔒 Security")
    _cfg_sec = sm._load_local_config()
    _mgmt_key = _cfg_sec.get("mgmt_api_key", "").strip()
    _inf_key  = _cfg_sec.get("api_key", "").strip()
    _ui_host  = _cfg_sec.get("ui_host", "127.0.0.1")
    _inf_host = _cfg_sec.get("host", "127.0.0.1")

    # The management API always binds to 0.0.0.0 regardless of ui_host, so
    # warn whenever there is no key — not only when ui_host is 0.0.0.0.
    if not _mgmt_key:
        st.warning(
            "⚠️ **The management API has no key set** and is accessible "
            "to anyone on your network.  Anyone on your Wi-Fi could start/stop the server "
            "or manage models.  Set a **Management API key** in the Remote Server section "
            "below to protect it."
        )
    if not _inf_key and _inf_host == "0.0.0.0":
        st.warning(
            "⚠️ **The inference server has no API key** and is bound to all interfaces. "
            "Anyone on your network can send chat requests.  Add an **API key** on the "
            "Server page to require authentication."
        )
    if _mgmt_key and _inf_key and _inf_host == "0.0.0.0":
        st.success("✅ Both the inference server and management API are protected by API keys.")
    elif _mgmt_key and _inf_host == "127.0.0.1":
        st.success("✅ Management API is protected. Inference server is localhost-only.")
    elif _mgmt_key:
        st.info("ℹ️ Management API is protected by an API key.")

    st.divider()
    st.subheader("🔄 Auto Model Switch (Proxy)")
    _cfg_ams = sm.load_config()
    ams_enabled = _cfg_ams.get("auto_model_switch", False)
    st.caption(
        "When enabled, the management API (port 8502) acts as an OpenAI-compatible proxy. "
        "If your chat client requests a model that differs from the currently loaded one, "
        "the server automatically restarts with the new model before responding. "
        "Point your client at **http://\\<this-mac\\>:8502/v1/chat/completions** instead of the usual port."
    )
    ams_new = st.toggle("Enable Auto Model Switch proxy", value=ams_enabled)
    if ams_new != ams_enabled:
        _cfg_ams["auto_model_switch"] = ams_new
        sm.save_config(_cfg_ams)
        if ams_new:
            st.success("✅ Auto Switch enabled. Point clients at port 8502.")
        else:
            st.info("Auto Switch disabled.")

    if _cfg_ams.get("auto_model_switch", False):
        _proxy_port = _cfg_ams.get("mgmt_port", 8502)
        _proxy_addrs = _get_all_local_addresses()
        st.markdown("**Proxy URLs** (use one of these as your OpenAI base URL):")
        rows = [f"| `{a['label']}` | `http://{a['ip']}:{_proxy_port}/v1` |" for a in _proxy_addrs]
        st.markdown(
            "| Interface | Proxy base URL |\n"
            "|-----------|----------------|\n"
            + "\n".join(rows)
        )
        st.caption("The model field in your client determines which model gets loaded. The proxy handles the switch automatically.")

    st.divider()
    st.subheader("🔌 Built-in Gradio Chat & Extensions")
    st.markdown(
        "**vllm-mlx** ships with its own minimal Gradio chat UI** separate from this dashboard. "
        "You can launch it in a new terminal tab with:\n"
        "```bash\nvllm-mlx-chat --model mlx-community/Llama-3.2-3B-Instruct-4bit\n```"
        "\nIt will open at `http://127.0.0.1:7860`.\n\n"
        "**Extending this dashboard:** The dashboard is pure Python/Streamlit. "
        "Advanced users can edit `vllm_mlx/dashboard/_ui.py` to add new pages or widgets. "
        "Streamlit components let you embed any web content — "
        "see [Streamlit Components](https://streamlit.io/components) for the gallery."
    )

    st.divider()
    st.subheader("ℹ️ About")
    from vllm_mlx.dashboard import __version__ as _ui_ver
    try:
        ver = importlib.metadata.version("vllm-mlx")
        st.write(f"**vllm-mlx version:** {ver}")
    except Exception:
        pass
    st.write(f"**Dashboard UI version:** {_ui_ver}")
    st.write(f"**Python:** {platform.python_version()}")
    st.write(f"**Platform:** {platform.mac_ver()[0] or platform.platform()}")

    try:
        import mlx.core as mx
        st.write(f"**MLX device:** {mx.default_device()}")
    except ImportError:
        pass

    st.markdown(
        "📋 [Changelog](https://github.com/clickbrain/vllm-mlx-ui/blob/main/CHANGELOG.md) &nbsp;·&nbsp; "
        "🔒 [Security Guide](https://github.com/clickbrain/vllm-mlx-ui/blob/main/docs/SECURITY.md) &nbsp;·&nbsp; "
        "📖 [README](https://github.com/clickbrain/vllm-mlx-ui/blob/main/README_UI.md)"
    )


# ===========================================================================
# Sidebar navigation
# ===========================================================================
PAGES = {
    "📊 Overview": page_overview,
    "🖥️ Server": page_server,
    "📦 Models": page_models,
    "⚡ Benchmarks": page_benchmarks,
    "💬 Chat": page_chat,
    "⚙️ Settings": page_settings,
}

with st.sidebar:
    # ── Branding ─────────────────────────────────────────────────────────────
    _is_rem = _is_remote()
    _badge_cls = "mode-badge-remote" if _is_rem else "mode-badge-local"
    _badge_label = "🌐 REMOTE" if _is_rem else "🖥 LOCAL"
    st.markdown(
        f"<h2 style='margin:0;padding:0'>🚀 vllm-mlx</h2>"
        f"<p style='color:#8e8e93;margin:0;font-size:.85rem'>Apple Silicon Inference</p>"
        f"<div style='margin-top:.5rem'>"
        f"<span class='mode-badge {_badge_cls}'>{_badge_label}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Local / Remote toggle (only when a remote URL is configured) ──────────
    _local_cfg = sm._load_local_config()
    _has_remote_cfg = bool(_local_cfg.get("remote_mgmt_url", "").strip())

    if _has_remote_cfg:
        _remote_host = _local_cfg["remote_mgmt_url"].split("//")[-1].split(":")[0]
        st.markdown(
            "<p style='color:#8e8e93;font-size:.78rem;margin:0.4rem 0 0.1rem'>Connection target</p>",
            unsafe_allow_html=True,
        )
        _mode_choice = st.radio(
            "connection_target",
            ["🖥  Local machine", f"🌐  {_remote_host}"],
            index=1 if _is_rem else 0,
            label_visibility="collapsed",
            key="_mode_radio",
        )
        _new_mode = "remote" if _mode_choice.startswith("🌐") else "local"
        if _new_mode != st.session_state.connection_mode:
            st.session_state.connection_mode = _new_mode
            # Persist so the choice survives browser refreshes and app restarts.
            try:
                _mode_cfg = sm._load_local_config()
                _mode_cfg["connection_mode"] = _new_mode
                sm.CONFIG_FILE.write_text(json.dumps(_mode_cfg, indent=2))
                st.session_state.pop("_cfg_cache", None)
                st.session_state.pop("_cfg_ts", None)
            except Exception:
                pass
            st.rerun()
    else:
        st.markdown(
            "<p style='color:#8e8e93;font-size:.75rem;margin:.3rem 0 0'>"
            "Add a remote server in ⚙️ Settings to enable remote mode."
            "</p>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Live server status pill + quick start/stop ────────────────────────────
    _status = sm.get_server_status()
    if _status["running"] and _status["healthy"]:
        st.success("● Server running")
        if st.button("⏹ Stop Server", width="stretch", key="_sb_stop_btn"):
            with st.spinner("Stopping…"):
                sm.stop_server()
            st.rerun()
    elif _status["running"]:
        st.warning("● Starting…")
    else:
        st.error("● Server stopped")
        _sb_cfg = sm.load_config()
        if _sb_cfg.get("model", "").strip():
            if st.button("▶ Start Server", width="stretch",
                         type="primary", key="_sb_start_btn"):
                with st.spinner("Starting…"):
                    ok, msg = sm.start_server(_sb_cfg)
                if not ok:
                    st.error(msg)
                st.rerun()
        else:
            st.caption("Select a model on the Server page to start.")

    # Quick model switcher
    _sb_cached = mm.get_cached_models()
    _sb_model_ids = [m["id"] for m in _sb_cached]
    if _sb_model_ids:
        st.divider()
        _sb_config = sm.load_config()
        _sb_active = _sb_config.get("model", "")
        if _status["running"] and _status["healthy"]:
            _sb_active = _status["health"].get("model_name", _sb_active)
        _sb_options = _sb_model_ids
        _sb_cur_idx = _sb_options.index(_sb_active) if _sb_active in _sb_options else 0
        # Pre-populate session state to avoid default-value/session-state conflict warning
        if "_sidebar_model" not in st.session_state or st.session_state["_sidebar_model"] not in _sb_options:
            st.session_state["_sidebar_model"] = _sb_options[_sb_cur_idx]
        _sb_sel = st.selectbox(
            "⚡ Quick switch model",
            _sb_options,
            key="_sidebar_model",
            label_visibility="visible",
            format_func=lambda x: x.split("/")[-1] if "/" in x else x,
        )
        if _sb_sel != _sb_active:
            if st.button("Switch now", key="_sidebar_swap_btn", type="primary",
                         width="stretch"):
                st.session_state["_swap_confirm"] = None
                _swap_model(_sb_sel)

    st.divider()

    for page_name in PAGES:
        if st.button(
            page_name,
            width="stretch",
            type="primary" if st.session_state.page == page_name else "secondary",
            key=f"nav_{page_name}",
        ):
            st.session_state.page = page_name
            st.rerun()

    # ── Update available banner (shown at bottom of sidebar) ─────────────────
    # Only flag updates that 'brew upgrade --fetch-HEAD vllm-mlx-ui' can fix.
    # pip-level dependency updates (mlx-lm, huggingface-hub) are shown in
    # Settings detail only — brew doesn't upgrade them so the banner would
    # show "update available" permanently after every brew upgrade.
    # Only the dashboard SHA check is meaningful here — vllm-mlx is part of the
    # same formula and its version tag tracks upstream (waybarrios), not our fork,
    # so it would always appear outdated even after a brew upgrade.
    _BREW_PACKAGES = {"vllm-mlx-ui (dashboard)"}
    try:
        from vllm_mlx.dashboard import update_checker as _uc_mod
        _upd_results = _uc_mod._cache.get("results", [])
    except Exception:
        _upd_results = []
    _upd_outdated = [p for p in _upd_results if p.update_available and p.name in _BREW_PACKAGES]
    if _upd_outdated:
        st.divider()
        _n = len(_upd_outdated)
        st.warning(f"⬆️ **{_n} update{'s' if _n > 1 else ''} available**")
        if st.button("Update Now & Restart", type="primary",
                     width="stretch", key="_sidebar_upgrade_btn"):
            st.session_state["_trigger_upgrade"] = True
            st.session_state.page = "⚙️ Settings"
            st.rerun()

    # ── Shutdown button (always at bottom of sidebar) ─────────────────────────
    st.divider()
    if st.button("⏹ Shutdown", width="stretch", key="_sidebar_shutdown_btn",
                 help="Stop the inference server and exit the dashboard"):
        st.session_state["_shutdown_confirm"] = True
        st.rerun()

    if st.session_state.get("_shutdown_confirm"):
        st.warning("Stop inference server and exit?")
        c1, c2 = st.columns(2)
        if c1.button("Yes, shutdown", type="primary", key="_shutdown_yes"):
            try:
                _srv_st = sm.get_server_status()
                if _srv_st.get("running"):
                    sm.stop_server()
            except Exception:
                pass
            st.success("Shutting down…")
            import time as _st_time
            _st_time.sleep(1)
            # Send SIGTERM to the app.py parent process (which owns the ports).
            # This triggers its signal handler which calls sys.exit(0), releasing
            # ports 8501 and 8502 cleanly. Fall back to os._exit if PID unknown.
            try:
                from vllm_mlx.dashboard.server_manager import UI_PID_FILE
                _ui_pid = int(UI_PID_FILE.read_text().strip())
                os.kill(_ui_pid, signal.SIGTERM)
            except Exception:
                os._exit(0)
        if c2.button("Cancel", key="_shutdown_cancel"):
            del st.session_state["_shutdown_confirm"]
            st.rerun()

# Render the selected page
PAGES[st.session_state.page]()
