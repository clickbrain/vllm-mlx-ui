# SPDX-License-Identifier: Apache-2.0
"""OllamaEngine — adapter for the Ollama inference runtime.

Ollama (ollama.com) manages its own model library using short tag names such
as ``llama3.2``, ``mistral``, ``qwen2.5:14b``.  It exposes an OpenAI-compatible
API at ``/v1`` (Ollama ≥ 0.3) as well as its native ``/api`` routes.

Install:  https://ollama.com/download  (brew install ollama, curl installer, etc.)
Launch:   ``ollama serve`` — Ollama binds to ``OLLAMA_HOST`` (default 127.0.0.1:11434).

Model naming:
  Ollama uses its own short-name registry (e.g. ``llama3.2:latest``), NOT HF repo IDs.
  Set ``config["model"]`` to the Ollama tag and also set
  ``config["engine_settings"]["ollama"]["launch_model"]`` to the same value.
  The dashboard always stores ``config["model"]`` as the tag when Ollama is the engine.

Port handling:
  We set ``OLLAMA_HOST=127.0.0.1:<port>`` via ``build_env()`` so Ollama binds to the
  dashboard-configured port instead of its default 11434.  This keeps the
  single-port contract intact across all engines.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, ClassVar

from .base import BaseEngine


class OllamaEngine(BaseEngine):
    """Adapter for the Ollama inference runtime."""

    id: ClassVar[str] = "ollama"
    name: ClassVar[str] = "Ollama"
    description: ClassVar[str] = (
        "Ollama runs quantised models locally with a simple pull-and-run workflow. "
        "Uses Ollama's own short model tags (e.g. llama3.2, mistral, qwen2.5:14b). "
        "Install Ollama from ollama.com then pull a model with `ollama pull <tag>`."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "continuous_batching",
        "embedding",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    release_url: ClassVar[str] = "https://ollama.com/download"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Return the ``ollama serve`` command.

        The port is not passed as a flag — Ollama reads it from the
        ``OLLAMA_HOST`` environment variable, which ``build_env()`` sets.
        """
        ollama_bin = self._which("ollama") or "ollama"
        return [ollama_bin, "serve"]

    def is_installed(self) -> bool:
        return self._which("ollama") is not None

    def get_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            # "ollama version 0.3.6" or "ollama version is 0.7.0"
            m = re.search(r"version(?:\s+is)?\s+(\S+)", result.stdout + result.stderr)
            return m.group(1) if m else None
        except Exception:
            return None

    def latest_version(self) -> str | None:
        try:
            import urllib.request
            import json as _json
            with urllib.request.urlopen(
                "https://api.github.com/repos/ollama/ollama/releases/latest",
                timeout=5,
            ) as resp:
                tag = _json.loads(resp.read()).get("tag_name", "")
                return tag.lstrip("v") or None
        except Exception:
            return None

    def upgrade_command(self) -> list[str] | None:
        """Try Homebrew upgrade for Ollama, or None if brew doesn't manage it."""
        if not shutil.which("brew"):
            return None
        # Only run brew upgrade if ollama is actually managed by brew
        # (brew list exits 0 if installed, non-zero if not a brew package)
        try:
            result = subprocess.run(
                ["brew", "list", "ollama"],
                capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                return None
        except Exception:
            return None
        return ["brew", "upgrade", "ollama"]

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the Ollama model tag to pass to the API.

        For Ollama, the launch model IS the model used in API requests.
        Falls back to ``config["model"]`` which should already be an Ollama tag.
        """
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        return engine_settings.get("launch_model") or config.get("model", "")

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "launch_model",
                "label": "Ollama Model Tag",
                "type": "str",
                "default": "",
                "help": (
                    "The Ollama model tag to serve (e.g. llama3.2, mistral, qwen2.5:14b). "
                    "Run `ollama pull <tag>` first. Leave blank to use the main model field."
                ),
            },
            {
                "key": "num_ctx",
                "label": "Context Window (num_ctx)",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": (
                    "Sets OLLAMA_CONTEXT_LENGTH. 0 = use Ollama's default for the model. "
                    "Override if you need a larger or smaller context window."
                ),
            },
            {
                "key": "num_parallel",
                "label": "Parallel Requests (num_parallel)",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 16,
                "help": "Sets OLLAMA_NUM_PARALLEL. 0 = Ollama default (auto).",
            },
            {
                "key": "max_loaded_models",
                "label": "Max Loaded Models",
                "type": "int",
                "default": 1,
                "min": 1,
                "max": 8,
                "help": "Sets OLLAMA_MAX_LOADED_MODELS. How many models to keep loaded simultaneously.",
            },
            {
                "key": "flash_attention",
                "label": "Flash Attention",
                "type": "bool",
                "default": False,
                "help": "Sets OLLAMA_FLASH_ATTENTION=1 for supported models.",
            },
        ]

    def build_env(self, config: dict[str, Any]) -> dict[str, str]:  # type: ignore[override]
        """Return Ollama environment variables derived from dashboard config."""
        host = config.get("host", "127.0.0.1")
        port = int(config.get("port", 11434))
        engine_settings = config.get("engine_settings", {}).get(self.id, {})

        env: dict[str, str] = {"OLLAMA_HOST": f"{host}:{port}"}

        num_ctx = int(engine_settings.get("num_ctx", 0))
        if num_ctx > 0:
            env["OLLAMA_CONTEXT_LENGTH"] = str(num_ctx)

        num_parallel = int(engine_settings.get("num_parallel", 0))
        if num_parallel > 0:
            env["OLLAMA_NUM_PARALLEL"] = str(num_parallel)

        max_loaded = int(engine_settings.get("max_loaded_models", 1))
        if max_loaded != 1:
            env["OLLAMA_MAX_LOADED_MODELS"] = str(max_loaded)

        if engine_settings.get("flash_attention"):
            env["OLLAMA_FLASH_ATTENTION"] = "1"

        return env

    def validate_model_id(self, model_id: str) -> bool:
        # Ollama tags: "name" or "name:tag" — simple alphanumeric + slashes for namespaced models
        return bool(re.match(r"^[\w./-]+(?::[\w.-]+)?$", model_id.strip()))
