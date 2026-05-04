# SPDX-License-Identifier: Apache-2.0
"""RapidMlxEngine — adapter for the Rapid-MLX inference engine.

Rapid-MLX (github.com/raullenchai/Rapid-MLX) is a performance-focused MLX
inference server with proprietary features like TurboQuant, DeltaNet snapshots,
and cloud routing.  It exposes an OpenAI-compatible API on the same port scheme
as vllm-mlx, making hot-swapping straightforward.

Install:  pip install rapid-mlx
Launch:   rapid-mlx serve <model> --host <h> --port <p> [flags...]

Model identifiers:
  Rapid-MLX supports both full HF repo IDs (mlx-community/Qwen3-8B-4bit) and
  curated short aliases (qwen3-8b, qwen3.5-9b, etc.).  The dashboard always
  stores the canonical HF repo ID in config["model"].  An optional
  config["engine_settings"]["rapid-mlx"]["launch_model"] override lets users
  map to a Rapid-MLX alias without changing the canonical model ID.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, ClassVar

from .base import BaseEngine


# Curated alias → canonical HF repo ID map for the Quick Start section.
RAPID_MLX_ALIASES: dict[str, str] = {
    "qwen3-0.6b":    "mlx-community/Qwen3-0.6B-4bit",
    "qwen3-1.7b":    "mlx-community/Qwen3-1.7B-4bit",
    "qwen3-4b":      "mlx-community/Qwen3-4B-4bit",
    "qwen3-8b":      "mlx-community/Qwen3-8B-4bit",
    "qwen3-14b":     "mlx-community/Qwen3-14B-4bit",
    "qwen3-30b":     "mlx-community/Qwen3-30B-A3B-4bit",
    "qwen3-72b":     "mlx-community/Qwen3-72B-4bit",
    "qwen3.5-9b":    "mlx-community/Qwen3.5-9B-8bit",
    "llama3-8b":     "mlx-community/Meta-Llama-3-8B-Instruct-4bit",
    "llama3-70b":    "mlx-community/Meta-Llama-3-70B-Instruct-4bit",
    "mistral-7b":    "mlx-community/Mistral-7B-Instruct-v0.3-4bit",
    "gemma3-4b":     "mlx-community/gemma-3-4b-it-4bit",
    "gemma3-12b":    "mlx-community/gemma-3-12b-it-4bit",
    "phi4-mini":     "mlx-community/phi-4-mini-instruct-4bit",
    "deepseek-r2-8b":"mlx-community/DeepSeek-R1-0528-Qwen3-8B-4bit",
}

# Inverse map for lookup when the user has an HF repo and wants the alias.
_HF_TO_ALIAS: dict[str, str] = {v: k for k, v in RAPID_MLX_ALIASES.items()}


class RapidMlxEngine(BaseEngine):
    """Adapter for the Rapid-MLX inference engine."""

    id: ClassVar[str] = "rapid-mlx"
    name: ClassVar[str] = "Rapid-MLX"
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "prefix_cache",
        "kv_quantization",
        "reasoning",
        "metrics",
    })
    install_method: ClassVar[str] = "pip"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the rapid-mlx serve command."""
        model = self.resolve_launch_model(config)

        # rapid-mlx is a pip-installed package — use sys.executable to guarantee
        # the same Python environment as the management server.
        cmd = [sys.executable, "-m", "rapid_mlx.cli", "serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        es = config.get("engine_settings", {}).get(self.id, {})

        if config.get("api_key"):
            cmd += ["--api-key", config["api_key"]]

        # Rapid-MLX specific flags from engine_settings
        if es.get("turboquant"):
            cmd += ["--turboquant"]
        if es.get("deltanet_snapshot"):
            cmd += ["--deltanet-snapshot", str(es["deltanet_snapshot"])]
        if es.get("cloud_routing"):
            cmd += ["--cloud-routing"]
        if es.get("kv_quantization"):
            cmd += ["--kv-cache-quantization"]
        if es.get("max_tokens", 0) > 0:
            cmd += ["--max-tokens", str(es["max_tokens"])]
        if es.get("enable_metrics"):
            cmd += ["--enable-metrics"]
        if not es.get("enable_prefix_cache", True):
            cmd += ["--disable-prefix-cache"]

        return cmd

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the model token for the rapid-mlx command line.

        Preference order:
        1. ``engine_settings["rapid-mlx"]["launch_model"]`` — explicit user override
        2. Known alias for the canonical HF repo ID (from RAPID_MLX_ALIASES)
        3. The canonical HF repo ID directly (rapid-mlx accepts those too)
        """
        es = config.get("engine_settings", {}).get(self.id, {})
        if es.get("launch_model"):
            return es["launch_model"]
        canonical = config.get("model", "")
        return _HF_TO_ALIAS.get(canonical, canonical)

    def is_installed(self) -> bool:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "rapid_mlx.cli", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_version(self) -> str | None:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "rapid_mlx.cli", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                line = (result.stdout or result.stderr or "").strip()
                # Version lines like "rapid-mlx 1.2.3" or "1.2.3"
                parts = line.split()
                return parts[-1] if parts else None
        except Exception:
            pass
        return None

    def validate_model_id(self, model_id: str) -> bool:
        # Accept both HF repo IDs (contains "/") and known aliases.
        if "/" in model_id:
            return True
        return model_id.lower() in RAPID_MLX_ALIASES

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "turboquant",
                "label": "TurboQuant",
                "type": "bool",
                "default": False,
                "help": "Enable Rapid-MLX TurboQuant dynamic quantization for faster inference.",
            },
            {
                "key": "deltanet_snapshot",
                "label": "DeltaNet Snapshot",
                "type": "str",
                "default": "",
                "help": "Path to a DeltaNet KV snapshot file for ultra-fast cold starts.",
            },
            {
                "key": "cloud_routing",
                "label": "Cloud Routing",
                "type": "bool",
                "default": False,
                "help": "Enable cloud routing for requests that exceed local capacity.",
            },
            {
                "key": "kv_quantization",
                "label": "KV Cache Quantization",
                "type": "bool",
                "default": False,
                "help": "Quantize KV cache to reduce memory usage.",
            },
            {
                "key": "max_tokens",
                "label": "Max Tokens",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": "Maximum tokens per request. 0 = engine default.",
            },
            {
                "key": "enable_metrics",
                "label": "Enable Metrics",
                "type": "bool",
                "default": False,
                "help": "Expose /metrics endpoint for Prometheus scraping.",
            },
            {
                "key": "enable_prefix_cache",
                "label": "Prefix Cache",
                "type": "bool",
                "default": True,
                "help": "Cache common prompt prefixes to reduce TTFT for repeated prefixes.",
            },
            {
                "key": "launch_model",
                "label": "Launch Model Override",
                "type": "str",
                "default": "",
                "help": "Optional Rapid-MLX alias (e.g. qwen3-8b). Overrides the canonical model ID at launch.",
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "turboquant": False,
            "deltanet_snapshot": "",
            "cloud_routing": False,
            "kv_quantization": False,
            "max_tokens": 0,
            "enable_metrics": False,
            "enable_prefix_cache": True,
            "launch_model": "",
        }
