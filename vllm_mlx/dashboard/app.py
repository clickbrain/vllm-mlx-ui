# SPDX-License-Identifier: Apache-2.0
"""CLI entry point — launches the Streamlit dashboard and management API server."""

import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

# Suppress any residual "missing ScriptRunContext" warnings.
# Root cause fix is in server_manager._in_streamlit() which short-circuits
# before touching Streamlit internals when called from AnyIO worker threads.
# This Filter is belt-and-suspenders: unlike setLevel(), a Filter is never
# overridden by Streamlit's own logging initialization at import time.
class _NoScriptRunCtxWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "missing ScriptRunContext" not in record.getMessage()

logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).addFilter(_NoScriptRunCtxWarning())


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


def _find_vllm_ui_pids() -> list[int]:
    """Find all running vllm-mlx-ui processes (by name and port), excluding self."""
    import subprocess as _sp
    own = os.getpid()
    pids: list[int] = []

    # Strategy 1: find by process name via pgrep
    try:
        out = _sp.check_output(
            ["pgrep", "-f", "vllm_mlx/dashboard|vllm-mlx-ui"],
            text=True, stderr=_sp.DEVNULL
        ).strip()
        for tok in out.split():
            try:
                pid = int(tok)
                if pid != own and pid not in pids:
                    pids.append(pid)
            except ValueError:
                pass
    except Exception:
        pass

    # Strategy 2: find by ports 8501/8502
    for port in [8501, 8502]:
        for fmt in [f"tcp:{port}", f":{port}"]:
            try:
                out = _sp.check_output(
                    ["lsof", "-t", "-i", fmt, "-n", "-P"],
                    text=True, stderr=_sp.DEVNULL
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

    return pids


def stop_all() -> None:
    """Terminate all running vllm-mlx-ui instances. Used by --stop flag."""
    import time as _t
    pids = _find_vllm_ui_pids()
    if not pids:
        print("No running vllm-mlx-ui instances found.")
        return
    print(f"Stopping {len(pids)} vllm-mlx-ui process(es): {pids}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    _t.sleep(2.0)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    _t.sleep(1.0)
    # Clean up PID file
    try:
        from vllm_mlx.dashboard.server_manager import UI_PID_FILE
        UI_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    print("✅ Stopped.")


def _kill_stale_ui(ui_pid_file: Path) -> bool:
    """Kill a previously running vllm-mlx-ui process recorded in ui_pid_file."""
    try:
        old_pid = int(ui_pid_file.read_text().strip())
        os.kill(old_pid, signal.SIGTERM)
        import time as _t
        _t.sleep(1.5)
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



def main() -> None:
    # Handle --stop flag before anything else
    if "--stop" in sys.argv:
        stop_all()
        sys.exit(0)

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
        cfg = _load_local_config()  # server_manager._load_local_config: reads ~/.vllm_mlx_ui/server_config.json without contacting the remote mgmt API (safe to call before Streamlit starts).
        ui_host = cfg.get("ui_host", "127.0.0.1")
        ui_port_pref = int(cfg.get("ui_port", 8501))
        mgmt_port_pref = int(cfg.get("mgmt_port", 8502))
    except Exception:
        # Graceful degradation: corrupted or missing config falls back to hardcoded
        # defaults so the app still starts. A broken config file should never prevent
        # the dashboard from launching.
        from pathlib import Path as _Path
        UI_PID_FILE = _Path.home() / ".vllm_mlx_ui" / "ui.pid"
        ui_host = "127.0.0.1"
        ui_port_pref = 8501
        mgmt_port_pref = 8502

    # Prevent port conflicts: terminate any previously-running instance before binding.
    # macOS does not immediately release sockets after SIGKILL; killing first prevents
    # "address already in use" errors on the mgmt API port.
    # Stop any existing vllm-mlx-ui instances (by name + port) before starting.
    import time as _time

    _stale_pids = _find_vllm_ui_pids()
    if _stale_pids:
        print(f"[vllm-mlx] Stopping previous instance(s): {_stale_pids}", file=sys.stderr)
        for _pid in _stale_pids:
            try:
                os.kill(_pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        _time.sleep(2.0)
        for _pid in _stale_pids:
            try:
                os.kill(_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        _time.sleep(0.5)  # brief wait for OS to release sockets after SIGKILL

    if UI_PID_FILE.exists():
        UI_PID_FILE.unlink(missing_ok=True)

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
        # If a relaunch was requested (e.g., by POST /restart or update install), start a new process
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

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # Start the management API server in a daemon thread.
    # NOTE: The management API always binds to 0.0.0.0 (all interfaces) regardless
    # of the ui_host setting. This is intentional — remote clients need to reach it
    # over the network. Access control is provided by the X-Api-Key header.
    # Users who set ui_host=127.0.0.1 restrict the Streamlit UI only, not the mgmt API.
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
        # Warn when no auth key is set — the API is accessible to any LAN host
        try:
            from vllm_mlx.dashboard.server_manager import _load_local_config
            if not _load_local_config().get("mgmt_api_key", "").strip():
                print(
                    f"[vllm-mlx] ⚠️  No mgmt_api_key set — management API on port {mgmt_port} "
                    "is open to any host on your network. Set a key in Settings → Remote Server.",
                    file=sys.stderr,
                )
        except Exception:
            pass
    else:
        print("[vllm-mlx] ⚠️  Management API did NOT start — check stderr for details",
              file=sys.stderr)

    # Auto-start inference server after a post-upgrade relaunch
    try:
        from vllm_mlx.dashboard.server_manager import (
            AUTO_START_FLAG, load_config, start_server,
        )
        # Two-path auto-start:
        # 1. AUTO_START_FLAG file: set by update_checker.relaunch() for post-upgrade
        #    one-time auto-start. Consumed (deleted) here so it only fires once.
        # 2. startup_model_behavior setting: user preference for normal restarts.
        #    "auto" = start immediately, "ask" = prompt, "none" = do nothing.
        # The flag takes priority so upgrades always auto-start regardless of preference.
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
        else:
            # Normal startup — honour startup_model_behavior setting
            _cfg = load_config()
            _behavior = _cfg.get("startup_model_behavior", "auto")
            if _behavior == "auto" and _cfg.get("model", "").strip():
                print(f"[vllm-mlx] 🔄 startup_model_behavior=auto — starting: {_cfg['model']}")
                _time.sleep(1.0)
                _ok, _msg = start_server(_cfg)
                print(f"[vllm-mlx] {'✅' if _ok else '⚠️ '} {_msg}")
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
    )

    # Record the Streamlit subprocess PID so force_release_memory() can protect
    # it from being treated as an orphaned vllm process (its cmdline contains
    # vllm_mlx path and would otherwise match the orphan-detection heuristic).
    try:
        from vllm_mlx.dashboard.server_manager import STREAMLIT_PID_FILE
        STREAMLIT_PID_FILE.write_text(str(streamlit_proc.pid))
    except Exception:
        pass

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
        try:
            from vllm_mlx.dashboard.server_manager import STREAMLIT_PID_FILE as _SPID
            _SPID.unlink(missing_ok=True)
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

