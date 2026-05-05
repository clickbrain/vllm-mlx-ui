# SPDX-License-Identifier: Apache-2.0
"""RapidMlxEngine — adapter for the Rapid-MLX inference engine.

Rapid-MLX (github.com/raullenchai/Rapid-MLX) is a performance-focused MLX
inference server with TurboQuant V-cache compression, DeltaNet state snapshots
(automatic — no CLI flag), smart cloud routing, and 17+ tool-call parsers.
It exposes an OpenAI-compatible API on the same port scheme as vllm-mlx.

Install:  pip install rapid-mlx
Launch:   rapid-mlx serve <model> --host <h> --port <p> [flags...]

CLI flags verified against the Rapid-MLX README
(github.com/raullenchai/Rapid-MLX) on 2026-04-30.

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
    description: ClassVar[str] = (
        "Rapid-MLX is a performance-focused MLX inference server for Apple Silicon with "
        "TurboQuant V-cache compression, 17+ tool-call parsers, and smart cloud routing. "
        "Install with `pip install rapid-mlx`."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "audio",
        "prefix_cache",
        "kv_quantization",
        "reasoning",
        "cloud_routing",
    })
    install_method: ClassVar[str] = "pip"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the rapid-mlx serve command with verified CLI flags."""
        model = self.resolve_launch_model(config)

        # rapid-mlx is a pip-installed package — use sys.executable to guarantee
        # the same Python environment as the management server.
        cmd = [sys.executable, "-m", "rapid_mlx.cli", "serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        es = config.get("engine_settings", {}).get(self.id, {})

        if config.get("api_key"):
            cmd += ["--api-key", config["api_key"]]

        # --- Performance flags ---
        if es.get("kv_turboquant"):
            cmd += ["--kv-cache-turboquant"]
        if es.get("kv_quantization"):
            cmd += ["--kv-cache-quantization"]
        if es.get("enable_prefix_cache"):
            # Default is OFF in the engine; user opts in via settings.
            cmd += ["--enable-prefix-cache"]
        prefill = es.get("prefill_step_size", 0)
        if prefill and prefill > 0:
            cmd += ["--prefill-step-size", str(prefill)]
        gpu_util = es.get("gpu_memory_utilization", 0.0)
        if gpu_util and 0.0 < gpu_util < 1.0:
            cmd += ["--gpu-memory-utilization", str(gpu_util)]
        if es.get("enable_tool_logits_bias"):
            cmd += ["--enable-tool-logits-bias"]

        # --- Token limits ---
        if es.get("max_tokens", 0) > 0:
            cmd += ["--max-tokens", str(es["max_tokens"])]

        # --- Cloud routing (--cloud-model is a litellm model string, not a bool) ---
        cloud_model = es.get("cloud_model", "").strip()
        if cloud_model:
            cmd += ["--cloud-model", cloud_model]
            cloud_threshold = es.get("cloud_threshold", 0)
            if cloud_threshold and cloud_threshold > 0:
                cmd += ["--cloud-threshold", str(cloud_threshold)]

        # --- Parser overrides (auto-detected from model name by default) ---
        tool_parser = es.get("tool_call_parser", "").strip()
        if tool_parser:
            cmd += ["--tool-call-parser", tool_parser]
        reasoning_parser = es.get("reasoning_parser", "").strip()
        if reasoning_parser:
            cmd += ["--reasoning-parser", reasoning_parser]

        # --- Rate limits ---
        rate_limit = es.get("rate_limit", 0)
        if rate_limit and rate_limit > 0:
            cmd += ["--rate-limit", str(rate_limit)]

        # --- Multimodal mode ---
        if es.get("mllm"):
            cmd += ["--mllm"]

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
            # --- Performance ---
            {
                "key": "kv_turboquant",
                "label": "TurboQuant V-Cache",
                "type": "bool",
                "default": False,
                "help": "Rotate + Lloyd-Max compress V cache (86% savings on dense models). Flag: --kv-cache-turboquant",
            },
            {
                "key": "kv_quantization",
                "label": "KV Cache Quantization",
                "type": "bool",
                "default": False,
                "help": "Quantize prefix cache entries to reduce memory usage. Flag: --kv-cache-quantization",
            },
            {
                "key": "enable_prefix_cache",
                "label": "Prefix Cache",
                "type": "bool",
                "default": False,
                "help": "Cache common prompt prefixes to reduce TTFT. Off by default in the engine. Flag: --enable-prefix-cache",
            },
            {
                "key": "prefill_step_size",
                "label": "Prefill Step Size",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 32768,
                "help": "Tokens per prefill chunk. 0 = engine default (2048). Increase to 8192 for large models. Flag: --prefill-step-size",
            },
            {
                "key": "gpu_memory_utilization",
                "label": "GPU Memory Utilization",
                "type": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 1.0,
                "help": "Fraction of device memory to use (0.0–1.0). 0.0 = engine default (0.90). Flag: --gpu-memory-utilization",
            },
            {
                "key": "enable_tool_logits_bias",
                "label": "Tool Logits Bias",
                "type": "bool",
                "default": False,
                "help": "Jump-forward decoding — bias logits toward structured tokens for faster tool calls. Flag: --enable-tool-logits-bias",
            },
            # --- Token limits ---
            {
                "key": "max_tokens",
                "label": "Max Tokens",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": "Default max tokens for generation. 0 = engine default (32768). Flag: --max-tokens",
            },
            # --- Cloud routing ---
            {
                "key": "cloud_model",
                "label": "Cloud Routing Model",
                "type": "str",
                "default": "",
                "help": "litellm model string to route large-context requests to cloud (e.g. openai/gpt-4o). Leave blank to disable. Flag: --cloud-model",
            },
            {
                "key": "cloud_threshold",
                "label": "Cloud Routing Threshold (tokens)",
                "type": "int",
                "default": 20000,
                "min": 1000,
                "max": 1000000,
                "help": "New token count above which to trigger cloud routing. Only used when Cloud Routing Model is set. Flag: --cloud-threshold",
            },
            # --- Parser overrides ---
            {
                "key": "tool_call_parser",
                "label": "Tool Call Parser",
                "type": "str",
                "default": "",
                "help": "Override auto-detected parser (e.g. hermes, llama, deepseek). Leave blank for auto-detection. Flag: --tool-call-parser",
            },
            {
                "key": "reasoning_parser",
                "label": "Reasoning Parser",
                "type": "str",
                "default": "",
                "help": "Override auto-detected reasoning parser (e.g. qwen3, deepseek_r1). Leave blank for auto-detection. Flag: --reasoning-parser",
            },
            # --- Rate limits ---
            {
                "key": "rate_limit",
                "label": "Rate Limit (req/min)",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 10000,
                "help": "Max requests per minute per client. 0 = unlimited. Flag: --rate-limit",
            },
            # --- Multimodal ---
            {
                "key": "mllm",
                "label": "Force Multimodal Mode",
                "type": "bool",
                "default": False,
                "help": "Force vision/multimodal mode. Auto-detected by default for VLMs. Flag: --mllm",
            },
            # --- Model override ---
            {
                "key": "launch_model",
                "label": "Launch Model Override",
                "type": "str",
                "default": "",
                "help": "Optional Rapid-MLX alias (e.g. qwen3.5-9b) or HF repo ID. Overrides the canonical model ID at launch.",
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "kv_turboquant": False,
            "kv_quantization": False,
            "enable_prefix_cache": False,
            "prefill_step_size": 0,
            "gpu_memory_utilization": 0.0,
            "enable_tool_logits_bias": False,
            "max_tokens": 0,
            "cloud_model": "",
            "cloud_threshold": 20000,
            "tool_call_parser": "",
            "reasoning_parser": "",
            "rate_limit": 0,
            "mllm": False,
            "launch_model": "",
        }
