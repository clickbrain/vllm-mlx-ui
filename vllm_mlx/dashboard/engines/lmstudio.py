# SPDX-License-Identifier: Apache-2.0
"""LmStudioEngine — adapter for LM Studio's local inference server.

LM Studio (lmstudio.ai) is a desktop GUI application for macOS/Windows/Linux
that can host a local OpenAI-compatible API server.  It also ships a CLI tool
``lms`` (installable from within the app: LM Studio → Settings → CLI).

Server management:
  Use ``lms server start --port <p>`` to start the server.
  The model must be loaded in LM Studio before or after starting the server.
  Use ``lms load <model>`` to load a specific model programmatically.

Health endpoint:
  LM Studio exposes ``/v1/models`` (not ``/health``).  The engine declares
  ``health_path = "/v1/models"`` so ``check_health()`` uses the right endpoint.

Model naming:
  LM Studio uses its own model identifiers as shown in its model library
  (e.g. ``meta-llama/Meta-Llama-3.1-8B-Instruct``).  The ``launch_model``
  engine setting specifies which model to load via ``lms load``.
  If ``launch_model`` is empty, the server starts without loading a new model
  (useful if LM Studio already has a model loaded).

Install:
  https://lmstudio.ai — download the app, then enable the CLI via Settings → CLI.
"""
from __future__ import annotations

import os
import subprocess
import time as _time
from typing import Any, ClassVar

from .base import BaseEngine

# LM Studio installs the CLI to /usr/local/bin on macOS by default.
# shutil.which() may miss this if the Python process PATH is stripped.
_KNOWN_LMS_PATHS: list[str] = [
    "/usr/local/bin/lms",
    os.path.expanduser("~/.lmstudio/bin/lms"),
]

# TTL cache for _is_daemon_running() — lms server status is a slow subprocess call.
# Caching for 5 seconds avoids repeated calls from is_installed() + check_requirements()
# firing in the same list_engines() pass.
_daemon_cache: tuple[float, bool] | None = None
_DAEMON_CACHE_TTL = 5.0  # seconds


class LmStudioEngine(BaseEngine):
    """Adapter for LM Studio's local OpenAI-compatible inference server."""

    id: ClassVar[str] = "lm-studio"
    name: ClassVar[str] = "LM Studio"
    description: ClassVar[str] = (
        "LM Studio is a desktop app (lmstudio.ai) that hosts a local OpenAI-compatible server. "
        "Install LM Studio, enable the `lms` CLI from Settings → CLI, "
        "then configure a model below. Requires LM Studio to be running."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "continuous_batching",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    homepage_url: ClassVar[str] = "https://lmstudio.ai"
    release_url: ClassVar[str] = "https://lmstudio.ai/download"

    # LM Studio is a desktop app — no headless installer.
    # The install_command raises NotImplementedError so the UI shows a proper
    # "Download from website" message instead of trying to run a command.
    def install_command(self) -> list[str]:
        raise NotImplementedError(
            "LM Studio must be downloaded and installed from https://lmstudio.ai/download. "
            "After installing, enable the CLI via LM Studio → Settings → CLI."
        )

    #: LM Studio uses /v1/models instead of /health
    health_path: ClassVar[str] = "/v1/models"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def _find_lms(self) -> str | None:
        """Find the lms binary on PATH or in known LM Studio install locations."""
        found = self._which("lms")
        if found:
            return found
        for path in _KNOWN_LMS_PATHS:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Start (or restart) the LM Studio local server.

        If a ``launch_model`` is set in engine settings, loads it via
        ``lms load`` before starting the server, using a shell wrapper so
        both steps happen in one Popen call.
        """
        lms_bin = self._find_lms() or "lms"
        port = int(config.get("port", 1234))
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        launch_model = engine_settings.get("launch_model", "").strip()

        if launch_model:
            # Load model then start the server.  We use a shell wrapper so both
            # steps happen in one Popen call.  The final command uses `exec` so
            # the shell is replaced by the lms process — the stored PID then
            # points to lms itself, not to sh, making SIGTERM work correctly.
            # Both lms_bin and launch_model are shell-quoted to handle paths with spaces.
            import shutil
            sh = shutil.which("sh") or "/bin/sh"
            lms_q = _shell_quote(lms_bin)
            return [sh, "-c", f"{lms_q} load {_shell_quote(launch_model)} && exec {lms_q} server start --port {port}"]

        return [lms_bin, "server", "start", "--port", str(port)]

    def _is_daemon_running(self) -> bool:
        """Return True if the LM Studio daemon is reachable via lms server status.

        Result is cached for ``_DAEMON_CACHE_TTL`` seconds to avoid redundant
        subprocess calls when both ``is_installed()`` and ``check_requirements()``
        run in the same ``list_engines()`` pass.
        """
        global _daemon_cache
        now = _time.monotonic()
        if _daemon_cache is not None:
            ts, result = _daemon_cache
            if now - ts < _DAEMON_CACHE_TTL:
                return result
        lms = self._find_lms()
        if not lms:
            _daemon_cache = (now, False)
            return False
        try:
            proc = subprocess.run(
                [lms, "server", "status"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            result = proc.returncode == 0
        except Exception:
            result = False
        _daemon_cache = (now, result)
        return result

    def is_installed(self) -> bool:
        """Return True if the lms binary exists anywhere on the system.

        Daemon running state is NOT checked here — an installed-but-not-running
        LM Studio is still "installed".  Use ``check_requirements()`` for
        runtime warnings (daemon not running, etc.).  Previously this checked
        both binary existence AND daemon running state, which caused
        ``start_server()`` to report "Engine 'lm-studio' is not installed"
        even when LM Studio was installed but the app wasn't open yet.
        """
        return self._find_lms() is not None

    def check_requirements(self) -> list[str]:
        """Warn if the `lms` CLI is not installed or the daemon is not running."""
        if not self._find_lms():
            return [
                "LM Studio CLI (`lms`) not found on PATH. "
                "Install LM Studio from https://lmstudio.ai, then enable the CLI "
                "via LM Studio → Settings → CLI."
            ]
        if not self._is_daemon_running():
            return [
                "LM Studio app is not running. Open LM Studio, then try again."
            ]
        return []

    def get_version(self) -> str | None:
        lms_bin = self._find_lms()
        if not lms_bin:
            return None
        try:
            result = subprocess.run(
                [lms_bin, "version"],
                capture_output=True, text=True, timeout=5,
            )
            v = (result.stdout or result.stderr).strip().splitlines()[0]
            return v or None
        except Exception:
            return None

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "launch_model",
                "label": "Model to Load",
                "type": "str",
                "default": "",
                "help": (
                    "LM Studio model identifier to load before starting the server "
                    "(e.g. meta-llama/Meta-Llama-3.1-8B-Instruct). "
                    "Leave empty to use whichever model is already loaded in LM Studio."
                ),
            },
            {
                "key": "_models_dir_hint",
                "label": "LM Studio Model Folder",
                "type": "info",
                "default": "",
                "help": (
                    "To share models with other engines, configure LM Studio's model "
                    "directory to match your Models Directory (Settings → Models Directory). "
                    "In LM Studio: My Models → ⋮ → Change models folder."
                ),
            },
        ]


def _shell_quote(s: str) -> str:
    """Minimal single-quote escaping for POSIX shells."""
    return "'" + s.replace("'", "'\\''") + "'"
