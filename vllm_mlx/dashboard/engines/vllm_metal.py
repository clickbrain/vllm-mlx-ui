# SPDX-License-Identifier: Apache-2.0
"""VllmMetalEngine — adapter for the original vLLM project on Apple Silicon.

vLLM (github.com/vllm-project/vllm) is a high-throughput LLM serving engine.
Recent versions include experimental Apple Silicon / MPS support.

Install:  ``pip install vllm``
          (Apple Silicon MPS support available in vLLM 0.6+; may require
           ``pip install vllm --pre`` for the latest builds.)
Launch:   ``vllm serve <model> --device mps --dtype float16 ...``
          or the older entrypoint:
          ``python -m vllm.entrypoints.openai.api_server --model <m> ...``

Device handling:
  On Apple Silicon we automatically add ``--device mps --dtype float16``.
  On other platforms we omit the device flag and let vLLM auto-detect.

Note:
  vLLM's Apple Silicon support is marked experimental upstream.  For
  production Apple Silicon inference, vllm-mlx (bundled) or Rapid-MLX are
  the recommended choices.
"""
from __future__ import annotations

import platform
import sys
from typing import Any, ClassVar

from .base import BaseEngine


def _is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


class VllmMetalEngine(BaseEngine):
    """Adapter for the original vLLM project with Apple Silicon MPS support."""

    id: ClassVar[str] = "vllm"
    name: ClassVar[str] = "vLLM (Metal)"
    description: ClassVar[str] = (
        "The original vLLM inference engine with experimental Apple Silicon / MPS support. "
        "Install with `pip install vllm`. Note: for production Apple Silicon inference, "
        "the bundled vLLM-MLX engine is recommended."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "continuous_batching",
        "prefix_cache",
        "kv_quantization",
        "embedding",
        "metrics",
        "paged_cache",
    })
    install_method: ClassVar[str] = "pip"
    is_builtin: ClassVar[bool] = True
    release_url: ClassVar[str] = "https://pypi.org/project/vllm/#history"

    def get_package_name(self) -> str:
        return "vllm"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_env(self, config: dict[str, Any]) -> dict[str, str]:
        # Prevent vllm-mlx's MLXPlatform plugin from hijacking the platform
        # detection when both vllm and vllm-mlx are installed in the same env.
        return {"VLLM_PLUGINS": ""}

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the vLLM serve command.

        Tries the ``vllm serve`` CLI first (vLLM ≥ 0.4), falls back to
        the ``python -m vllm.entrypoints.openai.api_server`` entrypoint.
        """
        import shutil
        model = self.resolve_launch_model(config)
        host = config.get("host", "127.0.0.1")
        port = int(config.get("port", 8000))
        engine_settings = config.get("engine_settings", {}).get(self.id, {})

        # Prefer the vllm CLI when available; it's faster and simpler.
        vllm_bin = shutil.which("vllm")
        if vllm_bin:
            cmd = [vllm_bin, "serve", model]
        else:
            cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model]

        cmd += ["--host", host, "--port", str(port)]

        # Apple Silicon: use MPS backend with float16 for stability.
        if _is_apple_silicon():
            cmd += ["--device", "mps", "--dtype", "float16"]

        # Expose the canonical HF repo ID as the served model name so the
        # dashboard's requests use the same identifier regardless of aliases.
        if config.get("model") and config["model"] != model:
            cmd += ["--served-model-name", config["model"]]

        if config.get("api_key"):
            cmd += ["--api-key", config["api_key"]]

        # Engine settings
        dtype = engine_settings.get("dtype", "")
        if dtype and dtype != "auto" and not _is_apple_silicon():
            # Don't double-set dtype on Apple Silicon (already set above).
            cmd += ["--dtype", dtype]

        max_model_len = int(engine_settings.get("max_model_len", 0))
        if max_model_len > 0:
            cmd += ["--max-model-len", str(max_model_len)]

        gpu_util = float(engine_settings.get("gpu_memory_utilization", 0.9))
        if gpu_util != 0.9:
            cmd += ["--gpu-memory-utilization", str(gpu_util)]

        tp = int(engine_settings.get("tensor_parallel_size", 1))
        if tp > 1:
            cmd += ["--tensor-parallel-size", str(tp)]

        if engine_settings.get("enable_chunked_prefill"):
            cmd += ["--enable-chunked-prefill"]

        if engine_settings.get("trust_remote_code") or config.get("trust_remote_code"):
            cmd += ["--trust-remote-code"]

        if engine_settings.get("enable_prefix_caching") if "enable_prefix_caching" in engine_settings else config.get("enable_prefix_cache", True):
            cmd += ["--enable-prefix-caching"]

        max_tokens = int(config.get("max_tokens", 0))
        if max_tokens > 0:
            cmd += ["--max-num-seqs", str(max(256, max_tokens // 64))]

        return cmd

    def is_installed(self) -> bool:
        try:
            import vllm  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str | None:
        try:
            import vllm
            return getattr(vllm, "__version__", None)
        except Exception:
            return None

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "dtype",
                "label": "Data Type",
                "type": "select",
                "default": "auto",
                "options": ["auto", "float16", "bfloat16", "float32"],
                "help": (
                    "Model weight precision. On Apple Silicon, float16 is always used. "
                    "`auto` lets vLLM choose based on the model config."
                ),
            },
            {
                "key": "max_model_len",
                "label": "Max Model Length",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": "Override the model's maximum sequence length. 0 = use model default.",
            },
            {
                "key": "gpu_memory_utilization",
                "label": "GPU Memory Utilisation",
                "type": "float",
                "default": 0.9,
                "min": 0.1,
                "max": 0.99,
                "help": "Fraction of GPU memory to reserve for KV cache (0.1–0.99).",
            },
            {
                "key": "tensor_parallel_size",
                "label": "Tensor Parallel Size",
                "type": "int",
                "default": 1,
                "min": 1,
                "max": 8,
                "help": "Number of GPUs for tensor parallelism. 1 = no parallelism.",
            },
            {
                "key": "enable_chunked_prefill",
                "label": "Chunked Prefill",
                "type": "bool",
                "default": False,
                "help": "Split long prefills into chunks to reduce first-token latency.",
            },
            {
                "key": "enable_prefix_caching",
                "label": "Prefix Caching",
                "type": "bool",
                "default": True,
                "help": "Cache and reuse KV tensors for repeated prompt prefixes.",
            },
            {
                "key": "trust_remote_code",
                "label": "Trust Remote Code",
                "type": "bool",
                "default": False,
                "help": "Allow executing custom model code from HuggingFace. Use only with trusted models.",
            },
        ]
