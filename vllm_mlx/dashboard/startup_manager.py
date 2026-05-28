# SPDX-License-Identifier: Apache-2.0
"""startup_manager — macOS LaunchAgent helper for run-at-login support.

Creates / removes a LaunchAgent plist in ~/Library/LaunchAgents/ so that
vllm-mlx-ui launches automatically when the user logs in.

The plist runs the same ``vllm-mlx-ui`` binary the user already has on PATH
(resolved at enable-time so the path is baked in, not evaluated lazily).
``RunAtLoad = true`` launches it immediately when the plist is loaded;
``KeepAlive = false`` means macOS will not auto-restart after a crash.
``StandardOutPath`` / ``StandardErrorPath`` direct output to a log file in
the same state directory used by the rest of the dashboard.
"""

from __future__ import annotations

import logging
import os
import plistlib
import shutil
import subprocess

logger = logging.getLogger(__name__)

_PLIST_LABEL = "com.clickbrain.vllm-mlx-ui"
_PLIST_PATH = os.path.expanduser(
    f"~/Library/LaunchAgents/{_PLIST_LABEL}.plist"
)
_LOG_PATH = os.path.expanduser("~/.vllm_mlx_ui/startup.log")


def _resolve_binary() -> str | None:
    """Return the stable path of the vllm-mlx-ui binary, or None.

    We intentionally do NOT call os.path.realpath() here.  On Homebrew
    installs the symlink ``/opt/homebrew/bin/vllm-mlx-ui`` always points to
    the currently-installed version, while its realpath resolves to a
    versioned Cellar directory (e.g. ``.../0.8.35/bin/vllm-mlx-ui``).
    Baking in the realpath means the LaunchAgent plist silently breaks after
    every ``brew upgrade``.
    """
    # Prefer the Homebrew symlink so the plist survives upgrades
    hb = "/opt/homebrew/bin/vllm-mlx-ui"
    if os.path.isfile(hb):
        return hb
    path = shutil.which("vllm-mlx-ui")
    return path or None


def is_enabled() -> bool:
    """Return True if the LaunchAgent plist exists (regardless of load state)."""
    return os.path.isfile(_PLIST_PATH)


def enable() -> dict:
    """Write the LaunchAgent plist so the app starts automatically at login.

    Does NOT call ``launchctl load`` — that would immediately spawn a second
    instance that would kill the currently-running session.  macOS reads
    ``~/Library/LaunchAgents/`` at login and starts everything with
    ``RunAtLoad = true`` on its own.

    Returns a dict with ``ok`` (bool) and ``message`` (str).
    """
    binary = _resolve_binary()
    if not binary:
        return {"ok": False, "message": "vllm-mlx-ui binary not found on PATH."}

    os.makedirs(os.path.dirname(_PLIST_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)

    # Build a PATH that includes Homebrew locations so engines installed via
    # brew (e.g. apfel) are discoverable when the agent starts at login.
    brew_path = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin"
    env_path = f"{brew_path}:/usr/bin:/bin:/usr/sbin:/sbin"

    plist: dict = {
        "Label": _PLIST_LABEL,
        "ProgramArguments": [binary],
        # RunAtLoad = True is required for macOS to actually start the program
        # at login.  Without it the LaunchAgent is registered but never runs.
        # We do NOT call `launchctl load` after writing the plist (which would
        # start a second instance immediately); macOS picks the plist up at
        # next login automatically.
        "RunAtLoad": True,
        "KeepAlive": False,
        "EnvironmentVariables": {"PATH": env_path},
        "StandardOutPath": _LOG_PATH,
        "StandardErrorPath": _LOG_PATH,
    }

    try:
        with open(_PLIST_PATH, "wb") as f:
            plistlib.dump(plist, f)
    except OSError as exc:
        return {"ok": False, "message": f"Could not write plist: {exc}"}

    return {"ok": True, "message": "vllm-mlx-ui will start automatically at your next login."}


def disable() -> dict:
    """Unload the LaunchAgent and remove the plist.

    Returns a dict with ``ok`` (bool) and ``message`` (str).
    """
    if not os.path.isfile(_PLIST_PATH):
        return {"ok": True, "message": "Startup at login was not enabled."}

    # Unload first so macOS stops tracking it
    try:
        subprocess.run(
            ["launchctl", "unload", "-w", _PLIST_PATH],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        logger.warning("launchctl unload failed: %s", exc)

    try:
        os.remove(_PLIST_PATH)
    except OSError as exc:
        return {"ok": False, "message": f"Could not remove plist: {exc}"}

    return {"ok": True, "message": "vllm-mlx-ui will no longer start at login."}
