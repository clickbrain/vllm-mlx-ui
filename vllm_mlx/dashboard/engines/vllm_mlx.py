# SPDX-License-Identifier: Apache-2.0
"""VllmMlxEngine — adapter for the vllm-mlx inference engine.

This adapter encapsulates all the flag-building logic that was previously
hard-coded in server_manager._build_command(). The logic is unchanged;
only the packaging has moved.
"""
from __future__ import annotations

import re
import sys
from typing import Any, ClassVar

from .base import BaseEngine


class VllmMlxEngine(BaseEngine):
    """Adapter for waybarrios/vllm-mlx (the bundled default engine)."""

    id: ClassVar[str] = "vllm-mlx"
    name: ClassVar[str] = "vLLM-MLX"
    description: ClassVar[str] = (
        "The bundled vLLM-MLX engine — optimised MLX inference for Apple Silicon with "
        "paged KV cache, continuous batching, tool calls, audio, and vision support. "
        "This is the default recommended engine for Apple Silicon Macs."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "audio",
        "continuous_batching",
        "prefix_cache",
        "kv_quantization",
        "paged_cache",
        "reasoning",
        "metrics",
        "embedding",
        "rerank",
        "mtp",
        "ssd_cache",
        "auto_model_switch",
    })
    # vllm-mlx ships bundled inside this package — cannot be installed separately.
    install_method: ClassVar[str] = "bundled"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the vllm-mlx serve command from the dashboard config.

        Always uses sys.executable so the inference server runs in the same
        Python environment as the management server (dev install or Homebrew,
        never mixed).  Using shutil.which("vllm-mlx") could find a
        Homebrew-frozen binary even when the mgmt server is running from a dev
        install, causing version skew.
        """
        model = self.resolve_launch_model(config)
        cmd = [sys.executable, "-m", "vllm_mlx.cli"]
        cmd += ["serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        if config.get("served_model_name"):
            cmd += ["--served-model-name", config["served_model_name"]]
        if config.get("api_key"):
            cmd += ["--api-key", config["api_key"]]
        if config.get("continuous_batching"):
            cmd += ["--continuous-batching"]

        # Only override token limits when explicitly changed from defaults.
        # max_request_tokens must >= max_tokens — engine enforces this.
        _max_tok = config.get("max_tokens", 32768)
        _max_req = config.get("max_request_tokens", 32768)
        if _max_req < _max_tok:
            _max_req = _max_tok
        if _max_tok != 32768 or _max_req != 32768:
            cmd += ["--max-tokens", str(_max_tok), "--max-request-tokens", str(_max_req)]

        # Reasoning parser: explicit config wins; otherwise auto-detect from model name.
        _reasoning_parser = (
            config.get("reasoning_parser")
            or _auto_detect_reasoning_parser(config.get("model", ""))
        )
        if _reasoning_parser:
            cmd += ["--reasoning-parser", _reasoning_parser]
        if config.get("tool_call_parser"):
            cmd += ["--tool-call-parser", config["tool_call_parser"]]
        if config.get("enable_auto_tool_choice") and config.get("tool_call_parser"):
            cmd += ["--enable-auto-tool-choice"]
        if config.get("gpu_memory_utilization", 0.90) != 0.90:
            cmd += ["--gpu-memory-utilization", str(config["gpu_memory_utilization"])]
        if not config.get("enable_prefix_cache", True):
            cmd += ["--disable-prefix-cache"]
        if config.get("cache_memory_mb", 0) > 0:
            cmd += ["--cache-memory-mb", str(config["cache_memory_mb"])]
        if config.get("kv_cache_quantization"):
            cmd += ["--kv-cache-quantization"]
            if config.get("kv_cache_quantization_bits", 8) != 8:
                cmd += ["--kv-cache-quantization-bits", str(config["kv_cache_quantization_bits"])]
        if config.get("use_paged_cache"):
            cmd += ["--use-paged-cache"]
        if config.get("enable_mtp"):
            cmd += ["--enable-mtp"]
            if config.get("mtp_num_draft_tokens", 1) != 1:
                cmd += ["--mtp-num-draft-tokens", str(config["mtp_num_draft_tokens"])]
        if config.get("rate_limit", 0) > 0:
            cmd += ["--rate-limit", str(config["rate_limit"])]
        if config.get("stream_interval", 1) != 1:
            cmd += ["--stream-interval", str(config["stream_interval"])]
        if config.get("mllm"):
            cmd += ["--mllm"]
        if config.get("trust_remote_code"):
            cmd += ["--trust-remote-code"]
        if config.get("embedding_model"):
            cmd += ["--embedding-model", config["embedding_model"]]
        if config.get("rerank_model"):
            cmd += ["--rerank-model", config["rerank_model"]]
        if config.get("enable_metrics"):
            cmd += ["--enable-metrics"]
        if config.get("offline"):
            cmd += ["--offline"]
        if config.get("ssd_cache_dir"):
            cmd += ["--ssd-cache-dir", config["ssd_cache_dir"]]
            if config.get("ssd_cache_max_gb", 0) > 0:
                cmd += ["--ssd-cache-max-gb", str(config["ssd_cache_max_gb"])]
        if config.get("warm_prompts"):
            cmd += ["--warm-prompts", config["warm_prompts"]]
        if config.get("prefill_step_size", 0) > 0:
            cmd += ["--prefill-step-size", str(config["prefill_step_size"])]
        if config.get("auto_model_switch"):
            cmd += ["--auto-model-switch"]

        return cmd

    def is_installed(self) -> bool:
        try:
            import vllm_mlx  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str | None:
        try:
            from vllm_mlx import __version__
            return __version__
        except Exception:
            return None

    def config_schema(self) -> list[dict[str, Any]]:
        # vllm-mlx settings are managed via the common settings panel in SettingsView.
        # Engine-specific extras (future: mtp advanced options, etc.) go here.
        return []


# ── Reasoning parser auto-detection ──────────────────────────────────────────

_REASONING_PATTERNS: list[tuple[str, str]] = [
    (r"qwen3|qwq", "qwen3"),
    (r"deepseek.?r[12]|ds.?r[12]", "deepseek_r1"),
    (r"gemma.?4", "gemma4"),
    (r"harmony", "harmony"),
]


def _auto_detect_reasoning_parser(model_name: str) -> str:
    model_lower = model_name.lower()
    for pattern, parser in _REASONING_PATTERNS:
        if re.search(pattern, model_lower):
            return parser
    return ""
