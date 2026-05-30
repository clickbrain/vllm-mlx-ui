# SPDX-License-Identifier: Apache-2.0
"""DiffusionMlxEngine — adapter for Dream-architecture diffusion language models.

Supports models built on the Dream masked-diffusion architecture, such as
Apple's DiffuCoder family. These models denoise a masked token sequence over N
steps rather than generating one token at a time, so they have different
performance characteristics from autoregressive models:

- No per-token streaming (all tokens refined simultaneously per step)
- Generation latency is dominated by steps × full-model-forward-pass
- Output quality improves with more steps (default 256; 512 for best quality)
- Tool calls and multi-step reasoning are NOT supported

Requires mlx-lm with Dream architecture support:
    pip install "git+https://github.com/Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder"

Once mlx-lm PR #270 is merged, the standard `pip install --upgrade mlx-lm`
will suffice and this engine will automatically detect that and use it.

Recommended model: mlx-community/DiffuCoder-7B-cpGRPO-8bit
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

from .base import BaseEngine

# Default port for the diffusion server subprocess.
# Chosen to avoid conflicts with rapid-mlx (8000), mgmt server (8502), etc.
_DEFAULT_PORT = 8511


def _has_dream_support() -> bool:
    """Return True if the installed mlx-lm has Dream/diffusion generation support.

    Does a real import (not just find_spec) to catch broken partial installs
    where the file exists on disk but fails to load.
    """
    try:
        from mlx_lm.generate_diffusion import stream_diffusion_generate  # noqa: F401
        return True
    except Exception:
        return False


class DiffusionMlxEngine(BaseEngine):
    """Adapter for Dream-architecture diffusion language models via MLX."""

    id: ClassVar[str] = "diffusion-mlx"
    name: ClassVar[str] = "Diffusion MLX"
    description: ClassVar[str] = (
        "Runs Dream-architecture masked-diffusion language models (e.g. DiffuCoder) on Apple "
        "Silicon via MLX. Diffusion models generate ALL tokens simultaneously over N denoising "
        "steps — no per-token streaming, but high output quality for code generation tasks.\n\n"
        "Recommended model: mlx-community/DiffuCoder-7B-cpGRPO-8bit\n"
        "Note: tool calls and thinking/reasoning are not supported by this architecture."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "diffusion",
    })
    install_method: ClassVar[str] = "pip"
    homepage_url: ClassVar[str] = "https://github.com/apple/ml-diffucoder"
    release_url: ClassVar[str] = "https://github.com/ml-explore/mlx-lm/pull/270"
    health_path: ClassVar[str] = "/health"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Launch diffusion_server.py as a subprocess."""
        model_id = config.get("model", "mlx-community/DiffuCoder-7B-cpGRPO-8bit")
        host = config.get("host", "127.0.0.1")
        port = config.get("port", _DEFAULT_PORT)

        es = config.get("engine_settings", {}).get(self.id, {})
        steps = int(es.get("steps", 256))
        temperature = float(es.get("temperature", 0.4))
        alg = es.get("alg", "entropy")

        server_module = "vllm_mlx.dashboard.diffusion_server"

        cmd = [
            sys.executable, "-m", server_module,
            "--model", model_id,
            "--host", host,
            "--port", str(port),
            "--steps", str(steps),
            "--temperature", str(temperature),
            "--alg", alg,
        ]

        try:
            from ..model_manager import get_hf_cache_dir
            cmd += ["--hf-cache", get_hf_cache_dir()]
        except Exception:
            pass

        return cmd

    def is_installed(self) -> bool:
        """Return True if mlx-lm with Dream support is available."""
        return _has_dream_support()

    def get_version(self) -> str | None:
        """Return the mlx-lm version (Dream support is gated on the version)."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "mlx-lm"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    def latest_version(self) -> str | None:
        """Return latest mlx-lm version from PyPI."""
        try:
            import urllib.request
            import json as _json
            with urllib.request.urlopen(
                "https://pypi.org/pypi/mlx-lm/json", timeout=5
            ) as resp:
                data = _json.loads(resp.read())
                return data["info"]["version"]
        except Exception:
            return None

    def install_command(self) -> list[str]:
        """Install the mlx-lm PR branch with Dream support."""
        return [
            sys.executable, "-m", "pip", "install", "--upgrade",
            "git+https://github.com/Goekdeniz-Guelmez/mlx-lm@adding-DiffuCoder",
        ]

    def uninstall_command(self) -> list[str]:
        # mlx-lm is shared with other engines (rapid-mlx, etc.) so we can't
        # `pip uninstall mlx-lm`. Instead, downgrade to the stable PyPI release,
        # which removes Dream support (generate_diffusion.py) without breaking
        # other engines that depend on mlx-lm.
        return [
            sys.executable, "-m", "pip", "install", "--upgrade", "mlx-lm",
        ]

    def check_requirements(self) -> list[str]:
        # No hardware/OS requirements — Dream models run on any Apple Silicon.
        # "Dream support not installed" is NOT a requirements error; it's fixed by Install.
        return []

    def check_warnings(self) -> list[str]:
        # Always warn while Dream support is from the PR branch (not a released mlx-lm).
        # The git+ pip install reports the branch version (e.g. "0.0.30"), NOT "x.y.z+git...",
        # so checking the version string is unreliable. Warn whenever Dream support is present.
        if _has_dream_support():
            return [
                "Using pre-release mlx-lm branch (PR #270 not yet merged in mlx-lm). "
                "Once PR #270 merges, upgrade with: pip install --upgrade mlx-lm"
            ]
        return []

    def validate_model_id(self, model_id: str) -> bool:
        # Accept any HF repo ID; DiffuCoder models are under apple/ or mlx-community/
        return "/" in model_id

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "steps",
                "label": "Denoising Steps",
                "type": "int",
                "default": 256,
                "min": 32,
                "max": 1024,
                "help": (
                    "Number of denoising steps. More steps = higher quality but slower. "
                    "256 is a good default; use 512 for maximum quality."
                ),
            },
            {
                "key": "temperature",
                "label": "Temperature",
                "type": "float",
                "default": 0.4,
                "min": 0.0,
                "max": 2.0,
                "help": "Sampling temperature. Lower = more deterministic. 0.4 works well for code.",
            },
            {
                "key": "alg",
                "label": "Unmasking Algorithm",
                "type": "enum",
                "default": "entropy",
                "options": ["entropy", "origin", "maskgit_plus", "topk_margin"],
                "help": (
                    "Algorithm used to select which masked tokens to unmask each step. "
                    "'entropy' (default) picks the most confident tokens first."
                ),
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "steps": 256,
            "temperature": 0.4,
            "alg": "entropy",
        }

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        try:
            from ..model_manager import get_hf_cache_dir
            return {"HF_HUB_CACHE": get_hf_cache_dir()}
        except Exception:
            return None
