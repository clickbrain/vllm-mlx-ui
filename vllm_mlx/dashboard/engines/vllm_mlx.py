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
from .flag_probe import add_if_supported

# Probe command for the vllm-mlx serve sub-command.  Used to gate optional
# flags that were added in newer versions of the engine.
_PROBE: tuple[str, ...] = ()  # populated lazily in build_command


def _vllm_probe() -> tuple[str, ...]:
    import sys as _sys
    return (_sys.executable, "-m", "vllm_mlx.cli", "serve")


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
    # vllm-mlx is a separate pip package from waybarrios/vllm-mlx.
    # Even though it ships as a hard dependency of vllm-mlx-ui, treating it as
    # "pip" ensures the global upgrade flow and per-engine latest-version check
    # update it independently from the dashboard package itself.
    install_method: ClassVar[str] = "pip"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the vllm-mlx serve command from the dashboard config.

        Always uses sys.executable so the inference server runs in the same
        Python environment as the management server (dev install or Homebrew,
        never mixed).  Using shutil.which("vllm-mlx") could find a
        Homebrew-frozen binary even when the mgmt server is running from a dev
        install, causing version skew.

        Optional flags are guarded via flag_probe so that older installed
        versions of vllm-mlx don't receive flags they don't understand.
        """
        probe = _vllm_probe()
        model = self.resolve_launch_model(config)
        cmd = [sys.executable, "-m", "vllm_mlx.cli"]
        cmd += ["serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        if config.get("served_model_name"):
            cmd += ["--served-model-name", config["served_model_name"]]
        if config.get("api_key"):
            add_if_supported(
                cmd, probe, "--api-key", [config["api_key"]],
                warn_if_unsupported=(
                    "vllm-mlx does not support --api-key in this version; "
                    "API key will not be enforced by the engine."
                ),
            )
        if config.get("continuous_batching"):
            add_if_supported(cmd, probe, "--continuous-batching")

        # Token limits: only override when explicitly changed from defaults.
        # max_request_tokens must >= max_tokens — engine enforces this.
        _max_tok = config.get("max_tokens", 32768)
        _max_req = config.get("max_request_tokens", 32768)
        if _max_req < _max_tok:
            _max_req = _max_tok
        if _max_tok != 32768 or _max_req != 32768:
            add_if_supported(cmd, probe, "--max-tokens", [str(_max_tok)])
            add_if_supported(cmd, probe, "--max-request-tokens", [str(_max_req)])

        # Reasoning parser: explicit config wins; otherwise auto-detect from model name.
        _reasoning_parser = (
            config.get("reasoning_parser")
            or _auto_detect_reasoning_parser(config.get("model", ""))
        )
        if _reasoning_parser:
            add_if_supported(cmd, probe, "--reasoning-parser", [_reasoning_parser])
        if config.get("tool_call_parser"):
            add_if_supported(cmd, probe, "--tool-call-parser", [config["tool_call_parser"]])
        if config.get("enable_auto_tool_choice") and config.get("tool_call_parser"):
            add_if_supported(cmd, probe, "--enable-auto-tool-choice")
        if config.get("gpu_memory_utilization", 0.90) != 0.90:
            add_if_supported(
                cmd, probe, "--gpu-memory-utilization",
                [str(config["gpu_memory_utilization"])],
            )
        if not config.get("enable_prefix_cache", True):
            add_if_supported(cmd, probe, "--disable-prefix-cache")
        if config.get("cache_memory_mb", 0) > 0:
            add_if_supported(cmd, probe, "--cache-memory-mb", [str(config["cache_memory_mb"])])
        if config.get("kv_cache_quantization"):
            add_if_supported(cmd, probe, "--kv-cache-quantization")
            if config.get("kv_cache_quantization_bits", 8) != 8:
                add_if_supported(
                    cmd, probe, "--kv-cache-quantization-bits",
                    [str(config["kv_cache_quantization_bits"])],
                )
        if config.get("use_paged_cache"):
            add_if_supported(cmd, probe, "--use-paged-cache")
        if config.get("enable_mtp"):
            add_if_supported(cmd, probe, "--enable-mtp")
            if config.get("mtp_num_draft_tokens", 1) != 1:
                add_if_supported(
                    cmd, probe, "--mtp-num-draft-tokens",
                    [str(config["mtp_num_draft_tokens"])],
                )
        if config.get("rate_limit", 0) > 0:
            add_if_supported(cmd, probe, "--rate-limit", [str(config["rate_limit"])])
        if config.get("stream_interval", 1) != 1:
            add_if_supported(cmd, probe, "--stream-interval", [str(config["stream_interval"])])
        if config.get("mllm"):
            add_if_supported(cmd, probe, "--mllm")
        # Check per-model trust_remote_code first, fall back to global default
        model_id = config.get("model", "")
        model_settings = config.get("model_settings", {})
        per_model = model_settings.get(model_id, {}).get("trust_remote_code")
        if per_model or (per_model is None and config.get("trust_remote_code")):
            add_if_supported(cmd, probe, "--trust-remote-code")
        if config.get("embedding_model"):
            add_if_supported(cmd, probe, "--embedding-model", [config["embedding_model"]])
        if config.get("rerank_model"):
            add_if_supported(cmd, probe, "--rerank-model", [config["rerank_model"]])
        if config.get("enable_metrics"):
            add_if_supported(cmd, probe, "--enable-metrics")
        if config.get("offline"):
            add_if_supported(cmd, probe, "--offline")
        if config.get("ssd_cache_dir"):
            add_if_supported(cmd, probe, "--ssd-cache-dir", [config["ssd_cache_dir"]])
            if config.get("ssd_cache_max_gb", 0) > 0:
                add_if_supported(
                    cmd, probe, "--ssd-cache-max-gb",
                    [str(config["ssd_cache_max_gb"])],
                )
        if config.get("warm_prompts"):
            add_if_supported(cmd, probe, "--warm-prompts", [config["warm_prompts"]])
        if config.get("prefill_step_size", 0) > 0:
            add_if_supported(
                cmd, probe, "--prefill-step-size",
                [str(config["prefill_step_size"])],
            )
        if config.get("auto_model_switch"):
            add_if_supported(cmd, probe, "--auto-model-switch")

        return cmd

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        """Set HF_HUB_CACHE so the inference subprocess uses the configured models directory."""
        try:
            from ..model_manager import get_hf_cache_dir
            cache_dir = get_hf_cache_dir()
            return {"HF_HUB_CACHE": cache_dir}
        except Exception:
            return None

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

    def get_package_name(self) -> str:
        """The vllm-mlx engine lives on PyPI under the ``vllm-mlx`` package."""
        return "vllm-mlx"

    def upgrade_command(self) -> list[str] | None:
        """Upgrade using the running Python's pip (not a resolved pip binary).

        Using ``sys.executable -m pip`` ensures the upgrade always targets the
        same Python environment the management process runs in — critical when
        ``pip_bin`` resolves to a different venv (e.g. brew cellar vs system).
        """
        return [sys.executable, "-m", "pip", "install", "--upgrade", "vllm-mlx"]

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
