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

    Uses lsof as primary strategy (always reliable on macOS, no special
    permissions needed), psutil as fallback.  Waits for the OS to actually
    release the port before returning.
    """
    import subprocess as _sp
    import time as _t

    pids: list[int] = []
    own = os.getpid()

    # Strategy 1: lsof (primary — most reliable on macOS)
    # Try both "tcp:<port>" and ":<port>" formats; add -n/-P to skip slow
    # DNS and service-name lookups.
    for fmt in [f"tcp:{port}", f":{port}"]:
        try:
            out = _sp.check_output(
                ["lsof", "-t", "-i", fmt, "-n", "-P"],
                text=True,
                stderr=_sp.DEVNULL,
            ).strip()
            for tok in out.split():
                try:
                    pid = int(tok)
                    if pid != own and pid not in pids:
                        pids.append(pid)
                except ValueError:
                    pass
            if pids:
                break
        except Exception:
            pass

    # Strategy 2: psutil fallback
    if not pids:
        try:
            import psutil
            # Accept both string and constant forms of LISTEN status
            _listen = {"LISTEN", getattr(psutil, "CONN_LISTEN", "LISTEN")}
            for conn in psutil.net_connections(kind="tcp"):
                try:
                    if (conn.laddr.port == port
                            and conn.status in _listen
                            and conn.pid
                            and conn.pid != own):
                        pids.append(conn.pid)
                except Exception:
                    pass
        except Exception:
            pass

    if not pids:
        return False

    # SIGTERM — ask politely first
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    _t.sleep(2.0)  # wait for graceful exit and socket close

    # SIGKILL any survivors
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    _t.sleep(1.0)  # wait for SIGKILL + OS to reclaim the port

    return True


def _find_free_port(preferred: int, exclude: set[int] | None = None, max_attempts: int = 20) -> int:
    """Return preferred port if free (and not in exclude), otherwise the next free port above it."""
    import socket as _socket
    exclude = exclude or set()
    for port in range(preferred, preferred + max_attempts):
        if port in exclude:
            continue
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return preferred  # fallback — let the OS error surface normally


def _request_firewall_exception(binary_path: str) -> None:
    """
    Ask macOS firewall to allow incoming connections for the vllm-mlx-ui binary.
    Uses socketfilterfw directly (no admin prompt if already allowed).
    Silently no-ops on failure — the user can always allow it manually.
    """
    import subprocess as _sp
    try:
        # First check if already allowed
        result = _sp.run(
            ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getappinfo", binary_path],
            capture_output=True, text=True, timeout=3
        )
        if "ALLOW" in result.stdout.upper():
            return  # Already allowed — nothing to do
    except Exception:
        pass

    try:
        # socketfilterfw --add requires root on newer macOS; use osascript to prompt
        _sp.run([
            "osascript", "-e",
            f'do shell script "/usr/libexec/ApplicationFirewall/socketfilterfw --add {binary_path!r} '
            f'&& /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp {binary_path!r}" '
            f'with administrator privileges'
        ], timeout=60, capture_output=True)
    except Exception:
        pass  # User declined or osascript not available — silently ignore


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
        ui_port_pref = int(cfg.get("ui_port", 8501))
        mgmt_port_pref = int(cfg.get("mgmt_port", 8502))
    except Exception:
        from pathlib import Path as _Path
        UI_PID_FILE = _Path.home() / ".vllm_mlx_ui" / "ui.pid"
        ui_host = "127.0.0.1"
        ui_port_pref = 8501
        mgmt_port_pref = 8502

    # Clear any stale previous UI instance BEFORE writing our own PID.
    # uvicorn.run() swallows OSError on bind failure — we MUST clear ports proactively.
    import time as _time

    if UI_PID_FILE.exists():
        _kill_stale_ui(UI_PID_FILE)

    # Always sweep both ports regardless of PID file.
    _port_cleared = False
    if _kill_process_on_port(mgmt_port_pref):
        _port_cleared = True
        print(f"[vllm-mlx] Cleared stale process on port {mgmt_port_pref}", file=sys.stderr)
    if _kill_process_on_port(ui_port_pref):
        _port_cleared = True
        print(f"[vllm-mlx] Cleared stale process on port {ui_port_pref}", file=sys.stderr)

    # Wait up to 5 seconds for the OS to release the sockets (handles TIME_WAIT)
    if _port_cleared:
        for _wait_attempt in range(5):
            _time.sleep(1.0)
            if not _find_free_port(ui_port_pref, exclude={mgmt_port_pref}) != ui_port_pref \
               and not _find_free_port(mgmt_port_pref, exclude={ui_port_pref}) != mgmt_port_pref:
                break  # both ports now free

    mgmt_port = mgmt_port_pref
    ui_port = str(ui_port_pref)
    ui_port_int = ui_port_pref

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

    # Request firewall exception for this binary (first run only, prompts for admin).
    # We do this before the mgmt API starts so the port is open when it binds.
    _binary_path = _find_binary()[0] if _find_binary()[0] != sys.executable else None
    if _binary_path and ui_host == "0.0.0.0":
        try:
            from vllm_mlx.dashboard.server_manager import _load_local_config, CONFIG_FILE
            import json as _json
            _fw_cfg = _load_local_config()
            if not _fw_cfg.get("_firewall_requested"):
                print("[vllm-mlx] 🔒 Requesting macOS firewall exception (one-time setup)…")
                _request_firewall_exception(_binary_path)
                _fw_cfg["_firewall_requested"] = True
                CONFIG_FILE.write_text(_json.dumps(_fw_cfg, indent=2))
        except Exception:
            pass

    # Start the management API server in a daemon thread.
    def _start_mgmt() -> None:
        try:
            from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
            start_mgmt_server(host="0.0.0.0", port=mgmt_port)
        except Exception as exc:
            print(f"[vllm-mlx] Management API failed to start: {exc}", file=sys.stderr)

    mgmt_thread = threading.Thread(target=_start_mgmt, daemon=True)
    mgmt_thread.start()

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

