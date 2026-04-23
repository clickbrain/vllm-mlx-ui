# SPDX-License-Identifier: Apache-2.0
"""CLI entry point — launches the Streamlit dashboard and management API server."""

import logging
import os
import signal
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


def _kill_stale_ui(ui_pid_file: Path) -> bool:
    """Kill a previously running vllm-mlx-ui process recorded in ui_pid_file."""
    try:
        old_pid = int(ui_pid_file.read_text().strip())
        os.kill(old_pid, signal.SIGTERM)
        import time as _t
        _t.sleep(1.5)
        # If still alive, escalate
        try:
            os.kill(old_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        ui_pid_file.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError, FileNotFoundError):
        ui_pid_file.unlink(missing_ok=True)
        return False
    except Exception:
        return False


def _kill_process_on_port(port: int) -> bool:
    """
    Find and terminate whatever process is listening on *port*.
    Tries psutil first (fast, no subprocess), then falls back to lsof.
    Returns True if a process was found and signalled.
    """
    import time as _t

    pids: list[int] = []

    # Strategy 1: psutil (most reliable)
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                if conn.pid and conn.pid != os.getpid():
                    pids.append(conn.pid)
    except Exception:
        pass

    # Strategy 2: lsof fallback
    if not pids:
        try:
            import subprocess as _sp
            out = _sp.check_output(
                ["lsof", "-ti", f"tcp:{port}"], text=True, stderr=_sp.DEVNULL
            ).strip()
            for p in out.split():
                pid = int(p)
                if pid != os.getpid():
                    pids.append(pid)
        except Exception:
            pass

    if not pids:
        return False

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    _t.sleep(1.5)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    return True


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
        from vllm_mlx.dashboard.server_manager import _load_local_config, UI_PID_FILE, STATE_DIR
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        cfg = _load_local_config()
        ui_host = cfg.get("ui_host", "127.0.0.1")
        ui_port = str(cfg.get("ui_port", 8501))
        mgmt_port = int(cfg.get("mgmt_port", 8502))
    except Exception:
        from pathlib import Path as _Path
        UI_PID_FILE = _Path.home() / ".vllm_mlx_ui" / "ui.pid"
        ui_host = "127.0.0.1"
        ui_port = "8501"
        mgmt_port = 8502

    # Clear any stale previous UI instance BEFORE writing our own PID.
    # (If we write first, the retry logic in _start_mgmt would read our
    # own PID and signal ourselves.)
    if UI_PID_FILE.exists():
        _kill_stale_ui(UI_PID_FILE)

    # Write our PID so the Shutdown button and future startups can find us
    try:
        UI_PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass

    # SIGTERM handler — clean exit that frees ports (daemon threads die with us)
    def _handle_sigterm(signum, frame):
        try:
            UI_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # Start the management API server in a daemon thread.
    # If the port is already in use, find and clear the process holding it.
    def _start_mgmt() -> None:
        try:
            from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
            start_mgmt_server(host="0.0.0.0", port=mgmt_port)
        except OSError as exc:
            if "address already in use" in str(exc).lower() or exc.errno == 48:
                print(
                    f"[vllm-mlx] Port {mgmt_port} in use — clearing stale process…",
                    file=sys.stderr,
                )
                if _kill_process_on_port(mgmt_port):
                    import time as _t
                    _t.sleep(1.0)
                    try:
                        from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
                        start_mgmt_server(host="0.0.0.0", port=mgmt_port)
                        return
                    except Exception as retry_exc:
                        print(
                            f"[vllm-mlx] Retry failed: {retry_exc}",
                            file=sys.stderr,
                        )
            print(
                f"[vllm-mlx] Management API failed to bind port {mgmt_port}: {exc}\n"
                f"           Try: lsof -ti tcp:{mgmt_port} | xargs kill",
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
        try:
            streamlit_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            streamlit_proc.kill()
    finally:
        try:
            UI_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        # Relaunch after upgrade
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

