# SPDX-License-Identifier: Apache-2.0
"""ExternalApiEngine — adapter for OpenAI-compatible remote API providers.

This engine does NOT run a local inference process. Instead, it configures
the dashboard's proxy to forward `/v1/chat/completions` requests to a remote
OpenAI-compatible API (OpenAI, Anthropic via proxy, Groq, OpenRouter, etc.).

Installation is always "available" — there is no binary to install. The user
just provides a base URL and API key in the engine settings.

Usage:
  1. Switch to this engine in Settings → Engine.
  2. Configure "API Base URL" (e.g. https://api.openai.com/v1).
  3. Set "API Key" for authentication.
  4. Add model IDs to "Enabled Models" (comma-separated).
  5. Start the server — requests to `/v1/chat/completions` proxy to the
     remote API. Auto-model-switch selects among the enabled models.
"""

from __future__ import annotations

import sys
from typing import Any, ClassVar

from .base import BaseEngine


class ExternalApiEngine(BaseEngine):
    """Adapter for OpenAI-compatible remote API providers."""

    id: ClassVar[str] = "openai-compatible"
    name: ClassVar[str] = "OpenAI-Compatible API"
    description: ClassVar[str] = (
        "Proxy requests to any OpenAI-compatible API provider "
        "(OpenAI, Groq, OpenRouter, Together AI, etc.). "
        "No local inference process — configure your API key and base URL, "
        "then chat through the dashboard proxy. "
        "Model auto-switch selects among configured model IDs. "
        "Requires an active internet connection and valid API credentials."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "reasoning",
    })
    install_method: ClassVar[str] = "external"
    homepage_url: ClassVar[str] = ""
    release_url: ClassVar[str] = ""

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """No local process — return a no-op sleep.

        The dashboard's proxy layer checks the engine type and routes
        to the remote URL configured in engine_settings.
        """
        return [sys.executable, "-c", "import time; time.sleep(999999)"]

    def is_installed(self) -> bool:
        """Always installed — this is a remote API, not a local binary."""
        return True

    def get_version(self) -> str | None:
        """Return a static version string for consistency."""
        return "1.0.0"

    def get_discovered_models(self) -> list[dict[str, Any]]:
        """Auto-discover from the remote API via /models endpoint."""
        return []  # discovery happens on first connect

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "base_url",
                "label": "API Base URL",
                "type": "str",
                "default": "https://api.openai.com/v1",
                "help": "Base URL of the OpenAI-compatible API. Examples:\n"
                        "  • OpenAI:      https://api.openai.com/v1\n"
                        "  • Groq:        https://api.groq.com/openai/v1\n"
                        "  • OpenRouter:  https://openrouter.ai/api/v1\n"
                        "  • Together AI: https://api.together.xyz/v1\n"
                        "  • Custom:      http://host:port/v1",
            },
            {
                "key": "api_key",
                "label": "API Key",
                "type": "str",
                "default": "",
                "help": "Your API key for the remote provider. "
                        "Stored in config — keep this value secure.",
            },
            {
                "key": "models",
                "label": "Enabled Models",
                "type": "str",
                "default": "",
                "help": "Comma-separated model IDs to enable for auto-switch. "
                        "Examples:\n"
                        "  • gpt-4o, gpt-4o-mini\n"
                        "  • llama-3.3-70b-versatile, mixtral-8x7b-32768",
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "models": "",
        }
