# SPDX-License-Identifier: Apache-2.0
"""AppleFMEngine — adapter for Apple's on-device Foundation Model framework.

Apple's Foundation Models framework (`FoundationModels` in Swift) provides
native access to the on-device ~3B parameter LLM that powers Apple Intelligence
(macOS 26+ / iOS 26+).  This adapter wraps the community ``apfel`` tool
which exposes the model through an OpenAI-compatible HTTP server.

Requirements:
  - macOS 26.0+
  - Apple Silicon (M1+)
  - Apple Intelligence enabled in System Settings
  - ``brew install apfel`` (community wrapper: github.com/Arthur-Ficial/apfel)

Capabilities:
  - Single ~3B parameter on-device LLM (no model selection)
  - Tool calling (function calling)
  - Structured output (JSON mode)
  - Optimized for chat, summarisation, entity extraction

Limitations:
  - Only Apple's own model is available — no Llama, Mistral, Qwen, etc.
  - Apple rate-limits CLI/background tools; GUI apps get unlimited access.
    The ``apfel`` server runs as a background process and may be throttled.
  - Model performance depends on Apple Intelligence update schedule.
"""

from __future__ import annotations

import json as _json
import logging
import os
import platform as _platform
import re
import shutil
import subprocess
import urllib.request as _urllib
from typing import Any, ClassVar

from .base import BaseEngine

logger = logging.getLogger(__name__)


class AppleFMEngine(BaseEngine):
    """Adapter for Apple's on-device Foundation Model via the apfel wrapper."""

    id: ClassVar[str] = "apple-fm"
    name: ClassVar[str] = "Apple Foundation Model (apfel)"
    description: ClassVar[str] = (
        "Apple's on-device ~3B parameter LLM, accessed via the community "
        "``apfel`` tool. Requires macOS\u00a026, Apple\u00a0Silicon, and "
        "Apple\u00a0Intelligence enabled. "
        "Single fixed model (Apple\u2019s own) \u2014 no model selection. "
        "Install with: brew install Arthur-Ficial/apfel/apfel"
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "reasoning",
    })
    # apfel is installed via Homebrew — "brew" tells server_manager to launch
    # it as a real local process (not skip it like "external"/"openai-compatible").
    install_method: ClassVar[str] = "brew"
    # apfel exposes an OpenAI-compatible API, not /health
    health_path: ClassVar[str] = "/v1/models"
    homepage_url: ClassVar[str] = "https://github.com/Arthur-Ficial/apfel"
    release_url: ClassVar[str] = "https://github.com/Arthur-Ficial/apfel/releases"

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Return the ``apfel serve`` command.

        The server exposes an OpenAI-compatible /v1/chat/completions endpoint.
        Binds to the dashboard-configured host and port.
        """
        host = config.get("host", "127.0.0.1")
        port = str(int(config.get("port", 8080)))
        return ["apfel", "serve", "--host", host, "--port", port]

    def is_installed(self) -> bool:
        return shutil.which("apfel") is not None

    def get_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["apfel", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r"(\d+\.\d+\.\d+)", result.stdout + result.stderr)
            return m.group(1) if m else None
        except Exception:
            return None

    def latest_version(self) -> str | None:
        try:
            with _urllib.urlopen(
                "https://api.github.com/repos/Arthur-Ficial/apfel/releases/latest",
                timeout=5,
            ) as resp:
                tag = _json.loads(resp.read()).get("tag_name", "")
                return tag.lstrip("v") or None
        except Exception:
            return None

    def upgrade_command(self) -> list[str] | None:
        if not shutil.which("brew"):
            return None
        return ["brew", "upgrade", "apfel"]

    def install_command(self) -> list[str]:
        return ["brew", "install", "Arthur-Ficial/apfel/apfel"]

    def uninstall_command(self) -> list[str]:
        if shutil.which("apfel"):
            return ["brew", "uninstall", "apfel"]
        raise NotImplementedError(
            "apfel binary not found. Uninstall manually: brew uninstall apfel"
        )

    def get_fixed_model_display(self) -> str:
        """Apple FM only provides Apple's own on-device foundation model."""
        return "Apple On-Device LLM (~3B)"

    def check_requirements(self) -> list[str]:
        """Check macOS version and hardware constraints."""
        issues: list[str] = []

        machine = _platform.machine().lower()
        if machine not in ("arm64", "aarch64"):
            issues.append("Apple Silicon (M1+) is required — Intel Macs are not supported.")

        # macOS version check (26.0+)
        try:
            ver = _platform.mac_ver()[0]
            if ver:
                parts = [int(p) for p in ver.split(".") if p.isdigit()]
                if parts and parts[0] < 26:
                    issues.append(f"macOS 26+ is required (detected: macOS {ver}).")
        except Exception:
            pass

        return issues

    def check_warnings(self) -> list[str]:
        """Warn about Apple CLI rate limiting and single-model constraint.

        The rate-limit advisory is only shown when apfel is actually installed —
        there is no point warning about throttling before the binary is present.
        """
        warnings: list[str] = []

        # macOS 26+ version check
        try:
            ver = _platform.mac_ver()[0]
            if ver:
                parts = [int(p) for p in ver.split(".") if p.isdigit()]
                if parts and parts[0] < 26:
                    warnings.append("Apple FM requires macOS 26 or later.")
        except Exception:
            pass

        # Apple Intelligence enabled check (heuristic: check for FM model cache dir)
        fm_cache = os.path.expanduser(
            "~/Library/Application Support/com.apple.spotlight/FoundationModel"
        )
        if not os.path.isdir(fm_cache):
            warnings.append(
                "Apple Intelligence may not be enabled. "
                "Enable it in System Settings > Apple Intelligence & Siri."
            )

        # Rate-limit advisory — only relevant when apfel is installed.
        if self.is_installed():
            warnings.append(
                "Apple applies rate limits to non-GUI tools. "
                "The apfel server runs as a background process and may be throttled. "
                "For heavy usage, run the apfel GUI app instead."
            )

        return warnings

    def validate_model_id(self, model_id: str) -> bool:
        """Apple FM only serves its single on-device model — all model IDs are accepted."""
        return True

    def get_discovered_models(self) -> list[dict[str, Any]]:
        """Apple FM has no model discovery — it's a single fixed model."""
        return []
