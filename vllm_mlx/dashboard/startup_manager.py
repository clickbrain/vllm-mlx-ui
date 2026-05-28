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
    """Return the absolute path of the vllm-mlx-ui binary, or None."""
    path = shutil.which("vllm-mlx-ui")
    if path:
        return os.path.realpath(path)
    # Homebrew standard location as a fallback
    hb = "/opt/homebrew/bin/vllm-mlx-ui"
    if os.path.isfile(hb):
        return hb
    return None


def is_enabled() -> bool:
    """Return True if the LaunchAgent plist exists (regardless of load state)."""
    return os.path.isfile(_PLIST_PATH)


def enable() -> dict:
    """Install the LaunchAgent and load it immediately.

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
        # RunAtLoad intentionally omitted (defaults False) so enabling this
        # setting does NOT immediately spawn a second instance that would kill
        # the currently-running session.  The agent will start at next login.
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

    # Load the agent so it takes effect without a logout/login cycle
    try:
        result = subprocess.run(
            ["launchctl", "load", "-w", _PLIST_PATH],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning("launchctl load returned %d: %s", result.returncode, result.stderr)
    except Exception as exc:
        logger.warning("launchctl load failed: %s", exc)

    return {"ok": True, "message": "vllm-mlx-ui will now start at login."}


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
