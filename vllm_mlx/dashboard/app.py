# SPDX-License-Identifier: Apache-2.0
"""CLI entry point — launches the Streamlit dashboard and management API server."""

import subprocess
import sys
import threading
from pathlib import Path


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

    # Start the management API server in a daemon thread so remote dashboards
    # can start/stop the inference server, manage models, etc.
    def _start_mgmt() -> None:
        try:
            from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
            # Always bind on all interfaces so remote dashboards can reach it.
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

    # Give the server a moment to bind before announcing it's ready
    import time as _time
    _time.sleep(1.0)
    if mgmt_thread.is_alive():
        print(f"[vllm-mlx] ✅ Management API listening on 0.0.0.0:{mgmt_port}")
    else:
        print(f"[vllm-mlx] ⚠️  Management API did NOT start — check stderr for details", file=sys.stderr)

    ui_file = Path(__file__).parent / "_ui.py"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ui_file),
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
    sys.exit(result.returncode)
