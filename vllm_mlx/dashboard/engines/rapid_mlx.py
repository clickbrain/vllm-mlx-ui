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
from .flag_probe import add_if_supported

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
    homepage_url: ClassVar[str] = "https://github.com/raullenchai/Rapid-MLX"
    release_url: ClassVar[str] = "https://github.com/raullenchai/Rapid-MLX/releases"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def _resolve_cmd(self) -> list[str]:
        """Return the argv prefix to launch rapid-mlx (binary or module fallback)."""
        found = self._which("rapid-mlx")
        if found:
            return [found]
        try:
            import importlib.util
            if importlib.util.find_spec("rapid_mlx") is not None:
                return [sys.executable, "-m", "rapid_mlx.cli"]
        except ImportError:
            pass
        return []

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the rapid-mlx serve command with verified CLI flags."""
        model = self.resolve_launch_model(config)

        cmd = self._resolve_cmd()
        if not cmd:
            raise RuntimeError(
                "rapid-mlx is not installed. Run `pip install rapid-mlx`."
            )
        probe_bin = self._which("rapid-mlx") or "rapid-mlx"
        probe = (probe_bin, "serve")
        cmd += ["serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        es = config.get("engine_settings", {}).get(self.id, {})

        if config.get("api_key"):
            add_if_supported(
                cmd, probe, "--api-key", [config["api_key"]],
                warn_if_unsupported=(
                    "rapid-mlx does not support --api-key in this version; "
                    "API key will not be enforced by the engine."
                ),
            )

        # --- Performance flags ---
        if es.get("kv_turboquant"):
            add_if_supported(cmd, probe, "--kv-cache-turboquant")
        if es.get("kv_quantization"):
            add_if_supported(cmd, probe, "--kv-cache-quantization")
        if es.get("enable_prefix_cache"):
            add_if_supported(cmd, probe, "--enable-prefix-cache")
        prefill = es.get("prefill_step_size", 0)
        if prefill and prefill > 0:
            add_if_supported(cmd, probe, "--prefill-step-size", [str(prefill)])
        gpu_util = es.get("gpu_memory_utilization", 0.0)
        if gpu_util and 0.0 < gpu_util < 1.0:
            add_if_supported(cmd, probe, "--gpu-memory-utilization", [str(gpu_util)])
        if es.get("enable_tool_logits_bias"):
            add_if_supported(cmd, probe, "--enable-tool-logits-bias")

        # --- Token limits ---
        if es.get("max_tokens", 0) > 0:
            add_if_supported(cmd, probe, "--max-tokens", [str(es["max_tokens"])])

        # --- Cloud routing ---
        cloud_model = es.get("cloud_model", "").strip()
        if cloud_model:
            add_if_supported(cmd, probe, "--cloud-model", [cloud_model])
            cloud_threshold = es.get("cloud_threshold", 0)
            if cloud_threshold and cloud_threshold > 0:
                add_if_supported(cmd, probe, "--cloud-threshold", [str(cloud_threshold)])

        # --- Parser overrides ---
        tool_parser = es.get("tool_call_parser", "").strip()
        if tool_parser:
            add_if_supported(cmd, probe, "--tool-call-parser", [tool_parser])
        reasoning_parser = es.get("reasoning_parser", "").strip()
        if reasoning_parser:
            add_if_supported(cmd, probe, "--reasoning-parser", [reasoning_parser])

        # --- Rate limits ---
        rate_limit = es.get("rate_limit", 0)
        if rate_limit and rate_limit > 0:
            add_if_supported(cmd, probe, "--rate-limit", [str(rate_limit)])

        # --- Multimodal mode ---
        if es.get("mllm"):
            add_if_supported(cmd, probe, "--mllm")

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

    def uninstall_command(self) -> list[str]:
        """Uninstall rapid-mlx, trying both naming conventions.

        The PyPI package is ``rapid-mlx`` (hyphen) but older docs referenced
        ``rapid_mlx`` (underscore).  We try the primary name first; if pip
        reports it is not installed, try the alternate.
        """
        primary = [sys.executable, "-m", "pip", "uninstall", "-y", "rapid-mlx"]
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "show", "rapid-mlx"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                return primary
        except Exception:
            pass
        return [sys.executable, "-m", "pip", "uninstall", "-y", "rapid_mlx"]

    def upgrade_command(self) -> list[str] | None:
        """Upgrade rapid-mlx via pip."""
        return [sys.executable, "-m", "pip", "install", "--upgrade", "rapid-mlx"]

    def is_installed(self) -> bool:
        if self._which("rapid-mlx"):
            return True
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "rapid-mlx"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        # Final fallback: try importing the package directly
        try:
            import rapid_mlx  # noqa: F401
            return True
        except ImportError:
            return False

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        """Set HF_HUB_CACHE so the inference subprocess uses the configured models directory."""
        try:
            from ..model_manager import get_hf_cache_dir
            cache_dir = get_hf_cache_dir()
            return {"HF_HUB_CACHE": cache_dir}
        except Exception:
            return None

    def get_version(self) -> str | None:
        # Try binary first (handles both PATH and _which-resolved paths)
        try:
            cmd = self._resolve_cmd() + ["--version"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                line = (result.stdout or result.stderr or "").strip()
                parts = line.split()
                return parts[-1] if parts else None
        except Exception:
            pass
        # Fallback: pip show (works when binary not on PATH)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "rapid-mlx"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
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
                "default": True,
                "help": "Rotate + Lloyd-Max compress V cache (86% savings on dense models). On by default for maximum memory efficiency. Flag: --kv-cache-turboquant",
            },
            {
                "key": "kv_quantization",
                "label": "KV Cache Quantization",
                "type": "bool",
                "default": True,
                "help": "Quantize prefix cache entries to reduce memory usage. On by default — reduces memory with minimal quality impact. Flag: --kv-cache-quantization",
            },
            {
                "key": "enable_prefix_cache",
                "label": "Prefix Cache",
                "type": "bool",
                "default": True,
                "help": "Cache common prompt prefixes to reduce TTFT. On by default for faster chat responses. Flag: --enable-prefix-cache",
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
                "default": True,
                "help": "Jump-forward decoding — bias logits toward structured tokens for faster tool calls. On by default for faster tool-call responses. Flag: --enable-tool-logits-bias",
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
            "kv_turboquant": True,
            "kv_quantization": True,
            "enable_prefix_cache": True,
            "prefill_step_size": 8192,
            "gpu_memory_utilization": 0.85,
            "enable_tool_logits_bias": True,
            "max_tokens": 0,
            "cloud_model": "",
            "cloud_threshold": 20000,
            "tool_call_parser": "",
            "reasoning_parser": "",
            "rate_limit": 0,
            "mllm": False,
            "launch_model": "",
        }
