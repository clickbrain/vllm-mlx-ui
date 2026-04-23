# SPDX-License-Identifier: Apache-2.0
"""CLI entry point — launches the Streamlit dashboard and management API server."""

import logging
import subprocess
import sys
import threading
from pathlib import Path

# Suppress the noisy "missing ScriptRunContext" warnings that fire on AnyIO
# worker threads (FastAPI/uvicorn runs in the same process as Streamlit).
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(
    logging.ERROR
)


def _find_binary() -> list[str]:
    """
    Return the command to launch vllm-mlx-ui as a list.
    Tries multiple strategies so the binary is found even with a stripped PATH.
    """
    import shutil
    found = shutil.which("vllm-mlx-ui")
    if found:
        return [found]
    for candidate in ["/opt/homebrew/bin/vllm-mlx-ui", "/usr/local/bin/vllm-mlx-ui"]:
        p = Path(candidate)
        if p.exists() and p.stat().st_mode & 0o111:
            return [str(p)]
    sibling = Path(sys.executable).parent / "vllm-mlx-ui"
    if sibling.exists():
        return [str(sibling)]
    return [sys.executable, "-m", "vllm_mlx.dashboard.app"]


def main() -> None:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "\033[91m✗ Streamlit is not installed.\033[0m\n\n"
            "Install the UI dependencies and try again:\n\n"
            "    pip install 'vllm-mlx[ui]'\n"
        )
        sys.exit(1)

    # Read network settings from persisted config (if present)
    try:
        from vllm_mlx.dashboard.server_manager import _load_local_config
        cfg = _load_local_config()
        ui_host = cfg.get("ui_host", "127.0.0.1")
        ui_port = str(cfg.get("ui_port", 8501))
        mgmt_port = int(cfg.get("mgmt_port", 8502))
    except Exception:
        ui_host = "127.0.0.1"
        ui_port = "8501"
        mgmt_port = 8502

    # Start the management API server in a daemon thread
    def _start_mgmt() -> None:
        try:
            from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
            start_mgmt_server(host="0.0.0.0", port=mgmt_port)
        except OSError as exc:
            print(
                f"[vllm-mlx] Management API failed to bind port {mgmt_port}: {exc}\n"
                f"           Another process may already be using port {mgmt_port}. "
                f"Try: lsof -i :{mgmt_port}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"[vllm-mlx] Management API failed to start: {exc}", file=sys.stderr)

    mgmt_thread = threading.Thread(target=_start_mgmt, daemon=True)
    mgmt_thread.start()

    import time as _time
    _time.sleep(1.0)
    if mgmt_thread.is_alive():
        print(f"[vllm-mlx] ✅ Management API listening on 0.0.0.0:{mgmt_port}")
    else:
        print(f"[vllm-mlx] ⚠️  Management API did NOT start — check stderr for details",
              file=sys.stderr)

    # Auto-start inference server after a post-upgrade relaunch
    try:
        from vllm_mlx.dashboard.server_manager import (
            AUTO_START_FLAG, load_config, start_server, get_server_status,
        )
        if AUTO_START_FLAG.exists():
            AUTO_START_FLAG.unlink(missing_ok=True)
            _cfg = load_config()
            if _cfg.get("model"):
                print(f"[vllm-mlx] 🔄 Auto-starting inference server: {_cfg['model']}")
                _time.sleep(1.0)
                _ok, _msg = start_server(_cfg)
                print(f"[vllm-mlx] {'✅' if _ok else '⚠️ '} {_msg}")
            else:
                print("[vllm-mlx] ℹ️  Post-upgrade relaunch: no model configured.")
    except Exception as _exc:
        print(f"[vllm-mlx] ⚠️  Auto-start check failed: {_exc}", file=sys.stderr)

    ui_file = Path(__file__).parent / "_ui.py"
    streamlit_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(ui_file),
            "--server.headless=false",
            f"--server.address={ui_host}",
            f"--server.port={ui_port}",
            "--browser.gatherUsageStats=false",
            "--theme.base=dark",
            "--theme.primaryColor=#7C3AED",
            "--theme.backgroundColor=#0F0F0F",
            "--theme.secondaryBackgroundColor=#1C1C1E",
            "--theme.textColor=#F5F5F7",
        ]
        + sys.argv[1:],
    )

    try:
        streamlit_proc.wait()
    except KeyboardInterrupt:
        # Ctrl+C goes to the whole process group — Streamlit handles its own
        # SIGINT; just wait for it to finish.
        try:
            streamlit_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            streamlit_proc.kill()
    finally:
        # ── Relaunch after upgrade ────────────────────────────────────────────
        # _ui.py writes RELAUNCH_FLAG before os._exit(0).  We pick it up here
        # and start a fresh process.  The inference server is left running
        # (AUTO_START_FLAG tells the new process to reconnect to it).
        # In ALL other cases (Ctrl+C, crash, explicit Shutdown button) we do
        # NOT touch the inference server — it runs independently and is stopped
        # only by the explicit Shutdown button in the UI.
        try:
            from vllm_mlx.dashboard.server_manager import RELAUNCH_FLAG
            if RELAUNCH_FLAG.exists():
                RELAUNCH_FLAG.unlink(missing_ok=True)
                cmd = _find_binary()
                subprocess.Popen(
                    cmd,
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    sys.exit(0)

