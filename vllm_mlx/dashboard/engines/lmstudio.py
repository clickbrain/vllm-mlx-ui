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

import subprocess
from typing import Any, ClassVar

from .base import BaseEngine


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
    release_url: ClassVar[str] = "https://lmstudio.ai/download"

    #: LM Studio uses /v1/models instead of /health
    health_path: ClassVar[str] = "/v1/models"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Start (or restart) the LM Studio local server.

        If a ``launch_model`` is set in engine settings, loads it via
        ``lms load`` before starting the server, using a shell wrapper so
        both steps happen in one Popen call.
        """
        lms_bin = self._which("lms") or "lms"
        port = int(config.get("port", 1234))
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        launch_model = engine_settings.get("launch_model", "").strip()

        if launch_model:
            # Load then start.  We use a shell-free two-step via a small wrapper
            # so the mgmt server doesn't need shell=True.
            # NOTE: lms load may take a while; the fail-fast check in start_server
            # (3 s timeout) will NOT kill it — lms exits once loading finishes,
            # then "lms server start" is a separate invocation.  We concatenate
            # both commands via the system sh for simplicity.
            import shutil
            sh = shutil.which("sh") or "/bin/sh"
            return [sh, "-c", f"{lms_bin} load {_shell_quote(launch_model)} && {lms_bin} server start --port {port}"]

        return [lms_bin, "server", "start", "--port", str(port)]

    def is_installed(self) -> bool:
        return self._which("lms") is not None

    def get_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["lms", "version"],
                capture_output=True, text=True, timeout=5,
            )
            # Output is typically just the version string "0.3.12"
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
