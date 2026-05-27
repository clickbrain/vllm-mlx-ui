# SPDX-License-Identifier: Apache-2.0
"""LlamaCppEngine — adapter for the llama.cpp HTTP inference server.

llama.cpp (github.com/ggerganov/llama.cpp) is a high-performance C++ inference
runtime that loads GGUF model files.  The ``llama-server`` binary exposes an
OpenAI-compatible API at ``/v1``.

Install (macOS):  ``brew install llama.cpp``
Install (build):  clone and ``cmake --build build --config Release``
Launch:           ``llama-server --model <path/to/model.gguf> --port <p>``

Model naming:
  llama.cpp loads local GGUF files, not HF repo IDs.  The ``launch_model``
  engine setting must be set to the absolute path (or ``~``-prefixed path)
  of the GGUF file to serve.

  To keep the dashboard's canonical model ID working in API requests, we pass
  ``--alias <canonical-hf-id>`` so that ``/v1/chat/completions`` accepts the
  same model string the dashboard uses everywhere else.

Health endpoint:
  llama.cpp exposes ``/health`` — the same as vllm-mlx, so no override needed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

from .base import BaseEngine
from .flag_probe import add_if_supported


class LlamaCppEngine(BaseEngine):
    """Adapter for the llama.cpp HTTP inference server."""

    id: ClassVar[str] = "llama-cpp"
    name: ClassVar[str] = "llama.cpp"
    description: ClassVar[str] = (
        "llama.cpp runs quantised GGUF models in a high-performance C++ server. "
        "Install via `brew install llama.cpp` (macOS) or build from source. "
        "Set the GGUF model path in Engine Settings below."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "continuous_batching",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    homepage_url: ClassVar[str] = "https://github.com/ggerganov/llama.cpp"
    release_url: ClassVar[str] = "https://github.com/ggerganov/llama.cpp/releases"

    # llama.cpp can be installed via Homebrew on macOS, or built from source.
    # We provide an install_command so the UI "Install" button works on macOS.
    def install_command(self) -> list[str]:
        """Return the command to install llama.cpp.

        On macOS: ``brew install llama.cpp``
        On Linux: clone + cmake build (not automated here).
        """
        import platform
        import shutil
        if platform.system() == "Darwin" and shutil.which("brew"):
            return ["brew", "install", "llama.cpp"]
        # On Linux or without brew, user must build from source.
        raise NotImplementedError(
            "llama.cpp must be built from source on this platform. "
            "See https://github.com/ggerganov/llama.cpp/blob/master/docs/install.md"
        )

    def uninstall_command(self) -> list[str]:
        """Uninstall llama.cpp via Homebrew, or raise."""
        import shutil
        if shutil.which("brew"):
            return ["brew", "uninstall", "llama.cpp"]
        raise NotImplementedError(
            "llama.cpp must be uninstalled manually on this platform. "
            "See https://github.com/ggerganov/llama.cpp"
        )

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the llama-server launch command.

        Raises:
            ValueError: if ``launch_model`` is not set or the file does not exist.
        """
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        raw_path = engine_settings.get("launch_model", "").strip()
        if not raw_path:
            raise ValueError(
                "llama.cpp requires a GGUF model path. "
                "Set it in Settings → Inference Engine → llama.cpp → GGUF Model Path."
            )
        model_path = str(Path(raw_path).expanduser().resolve())
        if not Path(model_path).exists():
            raise ValueError(
                f"GGUF model file not found: {model_path!r}. "
                "Check the path in Settings → Inference Engine → llama.cpp."
            )

        llama_bin = self._which("llama-server") or "llama-server"
        host = config.get("host", "127.0.0.1")
        port = int(config.get("port", 8000))
        canonical_id = config.get("model", "")

        cmd = [llama_bin]
        cmd += ["--model", model_path]
        cmd += ["--host", host]
        cmd += ["--port", str(port)]

        # Alias allows the dashboard (and API clients) to use the canonical HF repo ID
        # as the model name in /v1/chat/completions requests.
        if canonical_id:
            cmd += ["--alias", canonical_id]

        ctx_size = int(engine_settings.get("ctx_size", 0))
        if ctx_size > 0:
            cmd += ["--ctx-size", str(ctx_size)]

        n_gpu_layers = int(engine_settings.get("n_gpu_layers", -1))
        if n_gpu_layers != 0:  # 0 = CPU only; negative = all layers on GPU
            cmd += ["--n-gpu-layers", str(n_gpu_layers)]

        threads = int(engine_settings.get("threads", -1))
        if threads > 0:
            cmd += ["--threads", str(threads)]

        batch_size = int(engine_settings.get("batch_size", 512))
        if batch_size != 512:
            cmd += ["--batch-size", str(batch_size)]

        ubatch_size = int(engine_settings.get("ubatch_size", 512))
        if ubatch_size != 512:
            cmd += ["--ubatch-size", str(ubatch_size)]

        if engine_settings.get("flash_attn"):
            cmd += ["--flash-attn"]

        if engine_settings.get("mlock"):
            cmd += ["--mlock"]

        if engine_settings.get("no_mmap"):
            cmd += ["--no-mmap"]

        parallel = int(engine_settings.get("parallel", 1))
        if parallel > 1:
            cmd += ["--parallel", str(parallel)]

        if config.get("api_key"):
            add_if_supported(
                cmd, (llama_bin,), "--api-key", [config["api_key"]],
                warn_if_unsupported=(
                    "llama-server does not support --api-key in this version; "
                    "API key will not be enforced by the engine."
                ),
            )

        return cmd

    def is_installed(self) -> bool:
        return self._which("llama-server") is not None

    def get_version(self) -> str | None:
        llama_bin = self._which("llama-server") or "llama-server"
        try:
            result = subprocess.run(
                [llama_bin, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            text = result.stdout + result.stderr
            # "version: 3956 (1234abcd)" or "llama-server v0.0.3820-..."
            import re
            m = re.search(r"version[:\s]+(\S+)", text, re.IGNORECASE)
            return m.group(1) if m else text.strip().splitlines()[0] or None
        except Exception:
            return None

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the local GGUF path for the ``--model`` flag."""
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        raw = engine_settings.get("launch_model", "").strip()
        if raw:
            return str(Path(raw).expanduser().resolve())
        return config.get("model", "")

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "launch_model",
                "label": "GGUF Model File",
                "type": "gguf_file",
                "default": "",
                "help": (
                    "Select a GGUF file from your Models Directory, or enter an absolute "
                    "path (~ is expanded). Set your Models Directory in Settings → Models Directory "
                    "to populate this list automatically. "
                    "Example: ~/models/llama-3.2-8b-q4_k_m.gguf"
                ),
            },
            {
                "key": "n_gpu_layers",
                "label": "GPU Layers (n-gpu-layers)",
                "type": "int",
                "default": -1,
                "min": -1,
                "max": 200,
                "help": (
                    "-1 = offload all layers to GPU (default). "
                    "0 = CPU only. Positive = number of layers to offload."
                ),
            },
            {
                "key": "ctx_size",
                "label": "Context Size",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": "Context window size. 0 = use model default.",
            },
            {
                "key": "parallel",
                "label": "Parallel Requests",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 32,
                "help": "Number of parallel request slots (continuous batching). Default 4 for most Apple Silicon Macs.",
            },
            {
                "key": "batch_size",
                "label": "Batch Size",
                "type": "int",
                "default": 512,
                "min": 32,
                "max": 4096,
                "help": "Logical maximum batch size for token processing.",
            },
            {
                "key": "ubatch_size",
                "label": "Micro-batch Size",
                "type": "int",
                "default": 512,
                "min": 32,
                "max": 4096,
                "help": "Physical maximum batch size (ubatch). Must be ≤ batch_size.",
            },
            {
                "key": "threads",
                "label": "CPU Threads",
                "type": "int",
                "default": -1,
                "min": -1,
                "max": 256,
                "help": "Number of CPU threads. -1 = auto-detect.",
            },
            {
                "key": "flash_attn",
                "label": "Flash Attention",
                "type": "bool",
                "default": True,
                "help": "Enable Flash Attention (requires compatible model and build). On by default — faster generation on supported hardware.",
            },
            {
                "key": "mlock",
                "label": "mlock",
                "type": "bool",
                "default": False,
                "help": "Lock model weights in RAM to prevent swapping.",
            },
            {
                "key": "no_mmap",
                "label": "Disable mmap",
                "type": "bool",
                "default": False,
                "help": "Load model weights into RAM instead of memory-mapping the file.",
            },
        ]
