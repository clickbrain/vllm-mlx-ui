# SPDX-License-Identifier: Apache-2.0
"""DiffusionMlxEngine — adapter for Dream-architecture diffusion language models.

Supports models built on the Dream masked-diffusion architecture, such as
Apple's DiffuCoder family.  Uses MacPaw's Fast-dLLM-mlx backend which adds
KV-cache reuse and confidence-threshold parallel token finalization on top of
standard Dream inference, giving substantially faster generation than a naive
step-by-step implementation.

Performance characteristics vs. autoregressive models:
- No per-token streaming (all tokens denoised in parallel per step)
- Fast-dLLM path: ~20 steps with confidence thresholding ≈ quality of 256 naive steps
- Generation latency: typically 5-15s for DiffuCoder-7B on M-series chips
- Tool calls and thinking/reasoning are NOT supported

Requires fast-dllm-mlx:
    pip install "git+https://github.com/MacPaw/Fast-dLLM-mlx"

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
    """Return True if fast-dllm-mlx is installed and importable."""
    try:
        from fast_dllm_mlx import stream_diffusion_generate  # noqa: F401
        return True
    except Exception:
        return False


class DiffusionMlxEngine(BaseEngine):
    """Adapter for Dream-architecture diffusion language models via MLX."""

    id: ClassVar[str] = "diffusion-mlx"
    name: ClassVar[str] = "Diffusion MLX (Fast-dLLM)"
    description: ClassVar[str] = (
        "Runs Dream-architecture masked-diffusion language models (e.g. DiffuCoder) on Apple "
        "Silicon using MacPaw's Fast-dLLM-mlx backend.\n\n"
        "Fast-dLLM adds KV-cache reuse and confidence-threshold parallel token finalization "
        "for substantially faster inference than naive Dream: ~20 steps ≈ quality of 256 steps.\n\n"
        "Recommended model: mlx-community/DiffuCoder-7B-cpGRPO-8bit\n"
        "Note: tool calls and thinking/reasoning are not supported by this architecture."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "diffusion",
    })
    install_method: ClassVar[str] = "pip"
    homepage_url: ClassVar[str] = "https://github.com/MacPaw/Fast-dLLM-mlx"
    release_url: ClassVar[str] = "https://github.com/MacPaw/Fast-dLLM-mlx/releases"
    health_path: ClassVar[str] = "/health"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Launch diffusion_server.py as a subprocess."""
        model_id = config.get("model", "mlx-community/DiffuCoder-7B-cpGRPO-8bit")
        host = config.get("host", "127.0.0.1")
        port = config.get("port", _DEFAULT_PORT)

        es = config.get("engine_settings", {}).get(self.id, {})
        steps = int(es.get("steps", 24))
        temperature = float(es.get("temperature", 0.4))
        block_length = int(es.get("block_length", 32))
        threshold = float(es.get("threshold", 0.9))

        server_module = "vllm_mlx.dashboard.diffusion_server"

        cmd = [
            sys.executable, "-m", server_module,
            "--model", model_id,
            "--host", host,
            "--port", str(port),
            "--steps", str(steps),
            "--temperature", str(temperature),
            "--block-length", str(block_length),
            "--threshold", str(threshold),
        ]

        try:
            from ..model_manager import get_hf_cache_dir
            cmd += ["--hf-cache", get_hf_cache_dir()]
        except Exception:
            pass

        return cmd

    def is_installed(self) -> bool:
        """Return True if fast-dllm-mlx is available."""
        return _has_dream_support()

    def get_version(self) -> str | None:
        """Return the installed fast-dllm-mlx version string, or None."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "fast-dllm-mlx"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    def check_requirements(self) -> list[str]:
        import sys as _sys
        v = _sys.version_info
        if (v.major, v.minor) < (3, 13):
            return [
                f"fast-dllm-mlx requires Python ≥ 3.13 (running {v.major}.{v.minor}.{v.micro}). "
                "Please upgrade Python and reinstall."
            ]
        return []

    def check_warnings(self) -> list[str]:
        return []

    def latest_version(self) -> str | None:
        """Return latest fast-dllm-mlx version from GitHub API."""
        try:
            import urllib.request
            import json as _json
            url = "https://api.github.com/repos/MacPaw/Fast-dLLM-mlx/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "vllm-mlx-ui"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read())
                return data.get("tag_name", "").lstrip("v") or None
        except Exception:
            return None

    def install_command(self) -> list[str]:
        """Install fast-dllm-mlx from GitHub."""
        return [
            sys.executable, "-m", "pip", "install", "--upgrade",
            "git+https://github.com/MacPaw/Fast-dLLM-mlx",
        ]

    def uninstall_command(self) -> list[str]:
        return [sys.executable, "-m", "pip", "uninstall", "-y", "fast-dllm-mlx"]

    def validate_model_id(self, model_id: str) -> bool:
        # Accept any HF repo ID; DiffuCoder models are under apple/ or mlx-community/
        return "/" in model_id

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "steps",
                "label": "Denoising Steps",
                "type": "int",
                "default": 24,
                "min": 8,
                "max": 256,
                "help": (
                    "Number of denoising steps. Fast-dLLM uses confidence thresholding so "
                    "24 steps delivers quality comparable to 256 naive steps. "
                    "Must be a multiple of num_blocks (max_new_tokens ÷ block_length); "
                    "steps are automatically rounded up to satisfy this constraint."
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
                "key": "block_length",
                "label": "Block Length",
                "type": "int",
                "default": 32,
                "min": 8,
                "max": 128,
                "help": (
                    "Number of tokens processed per denoising block. "
                    "Larger blocks = more parallelism but coarser granularity. "
                    "max_new_tokens will be rounded up to the nearest multiple of this value."
                ),
            },
            {
                "key": "threshold",
                "label": "Confidence Threshold",
                "type": "float",
                "default": 0.9,
                "min": 0.5,
                "max": 1.0,
                "help": (
                    "Confidence gate for early token finalization. Tokens whose predicted "
                    "probability exceeds this threshold are finalized early, skipping later steps. "
                    "Higher = more conservative (more steps); lower = faster but lower quality."
                ),
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "steps": 24,
            "temperature": 0.4,
            "block_length": 32,
            "threshold": 0.9,
        }

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        try:
            from ..model_manager import get_hf_cache_dir
            return {"HF_HUB_CACHE": get_hf_cache_dir()}
        except Exception:
            return None
