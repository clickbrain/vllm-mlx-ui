# SPDX-License-Identifier: Apache-2.0
"""CLI entry point — launches the Vue dashboard (mgmt API + static UI)."""

import os
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path


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
    """CLI entry point for ``vllm-mlx-ui``.

    Handles ``--stop`` to terminate running instances, kills any stale previous
    instance that is holding our ports, writes a PID file, optionally auto-starts
    the inference server, opens the browser, then blocks serving the management
    API + Vue UI until Ctrl-C or SIGTERM.

    On SIGTERM or KeyboardInterrupt checks for a RELAUNCH_FLAG (written by the
    upgrade workflow) and spawns a fresh process before exiting.
    """
    # Handle --stop flag before anything else
    if "--stop" in sys.argv:
        stop_all()
        sys.exit(0)

    import time as _time

    # Read network settings from persisted config (if present)
    try:
        from vllm_mlx.dashboard.server_manager import _load_local_config, UI_PID_FILE, STATE_DIR
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        cfg = _load_local_config()
        ui_host = cfg.get("ui_host", "127.0.0.1")
        mgmt_port = int(cfg.get("mgmt_port", 8502))
    except Exception:
        from pathlib import Path as _Path
        UI_PID_FILE = _Path.home() / ".vllm_mlx_ui" / "ui.pid"
        ui_host = "127.0.0.1"
        mgmt_port = 8502

    # Kill any previous instance that might be holding our port
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
        _time.sleep(0.5)

    if UI_PID_FILE.exists():
        UI_PID_FILE.unlink(missing_ok=True)

    # Write our PID so the Shutdown button and future startups can find us
    try:
        UI_PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass

    # SIGTERM handler — clean exit; relaunches if RELAUNCH_FLAG is set
    def _handle_sigterm(signum, frame):
        try:
            UI_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            from vllm_mlx.dashboard.server_manager import RELAUNCH_FLAG
            if RELAUNCH_FLAG.exists():
                RELAUNCH_FLAG.unlink(missing_ok=True)
                subprocess.Popen(
                    _find_binary(),
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # Warn when no auth key is configured
    try:
        from vllm_mlx.dashboard.server_manager import _load_local_config as _lc
        if not _lc().get("mgmt_api_key", "").strip():
            print(
                f"[vllm-mlx] ⚠️  No mgmt_api_key set — management API on port {mgmt_port} "
                "is open to any host on your network. Set a key in Settings → Remote Server.",
                file=sys.stderr,
            )
    except Exception:
        pass

    # Auto-start inference server if configured
    try:
        from vllm_mlx.dashboard.server_manager import (
            AUTO_START_FLAG, load_config, start_server,
        )
        if AUTO_START_FLAG.exists():
            AUTO_START_FLAG.unlink(missing_ok=True)
            _cfg = load_config()
            if _cfg.get("model"):
                print(f"[vllm-mlx] 🔄 Auto-starting inference server: {_cfg['model']}")
                _time.sleep(0.5)
                _ok, _msg = start_server(_cfg)
                print(f"[vllm-mlx] {'✅' if _ok else '⚠️ '} {_msg}")
        else:
            _cfg = load_config()
            if _cfg.get("startup_model_behavior", "auto") == "auto" and _cfg.get("model", "").strip():
                print(f"[vllm-mlx] 🔄 startup_model_behavior=auto — starting: {_cfg['model']}")
                _time.sleep(0.5)
                _ok, _msg = start_server(_cfg)
                print(f"[vllm-mlx] {'✅' if _ok else '⚠️ '} {_msg}")
    except Exception as _exc:
        print(f"[vllm-mlx] ⚠️  Auto-start check failed: {_exc}", file=sys.stderr)

    # Open the browser after a short delay so uvicorn has time to bind
    _ui_url = f"http://{ui_host}:{mgmt_port}/"
    if ui_host in ("0.0.0.0", ""):
        _ui_url = f"http://127.0.0.1:{mgmt_port}/"

    def _open_browser():
        _time.sleep(1.2)
        webbrowser.open(_ui_url)

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"[vllm-mlx] ✅ Dashboard → {_ui_url}  (Ctrl+C to quit)")

    # Run the management API + Vue UI server in the foreground (blocking)
    try:
        from vllm_mlx.dashboard.mgmt_server import start_mgmt_server
        start_mgmt_server(host="0.0.0.0", port=mgmt_port)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            UI_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        # Relaunch after upgrade or restart request
        try:
            from vllm_mlx.dashboard.server_manager import RELAUNCH_FLAG, STATE_DIR
            if RELAUNCH_FLAG.exists():
                RELAUNCH_FLAG.unlink(missing_ok=True)
                binary_parts = _find_binary()
                cmd_str = " ".join(
                    f'"{p}"' if " " in p else p for p in binary_parts
                )
                log_path = STATE_DIR / "mgmt.log"
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                # Delay ensures this process fully exits and port 8502 is free
                # before the new process attempts to bind.
                with open(log_path, "a") as _lf:
                    subprocess.Popen(
                        ["sh", "-c", f"sleep 2 && {cmd_str}"],
                        start_new_session=True,
                        stdin=subprocess.DEVNULL,
                        stdout=_lf,
                        stderr=_lf,
                    )
        except Exception:
            pass

    sys.exit(0)

