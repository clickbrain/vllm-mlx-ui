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

Requires fast-dllm-mlx AND Python >= 3.13:
    pip install "git+https://github.com/MacPaw/Fast-dLLM-mlx"

NOTE: The Homebrew venv runs Python 3.11.  fast-dllm-mlx requires Python 3.13+.
This engine discovers a compatible Python at runtime and runs diffusion_server.py
via that interpreter rather than sys.executable.

Recommended model: mlx-community/DiffuCoder-7B-cpGRPO-8bit
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, ClassVar

from .base import BaseEngine

# Default port for the diffusion server subprocess.
# Chosen to avoid conflicts with rapid-mlx (8000), mgmt server (8502), etc.
_DEFAULT_PORT = 8511

# ── Python 3.13+ discovery ────────────────────────────────────────────────────

# Module-level cache: (executable_path | None, timestamp)
_py313_cache: tuple[str | None, float] = (None, 0.0)
_py313_cache_ttl: float = 60.0  # re-probe at most once per minute

# Module-level cache for is_installed result: (bool, timestamp)
_installed_cache: tuple[bool, float] = (False, 0.0)
_installed_cache_ttl: float = 30.0


def _find_python313() -> str | None:
    """Find a Python >= 3.13 executable on this machine.

    Checks (in order):
    1. Explicit version names on PATH: python3.14, python3.13
    2. Known conda/anaconda base locations
    3. python3 on PATH (works when conda is active in the shell that launched vmui)

    Returns the first candidate whose ``--version`` reports >= 3.13, or None.
    Caches the result for _py313_cache_ttl seconds to avoid repeated probing.
    """
    global _py313_cache
    path, ts = _py313_cache
    if time.monotonic() - ts < _py313_cache_ttl:
        return path

    candidates: list[str] = []

    # Explicit version names on PATH — prefer 3.13 over 3.14 (3.14 is bleeding-edge
    # and some packages may not yet support it)
    for name in ("python3.13", "python3.14"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # Known conda/anaconda base Python locations
    conda_bases = [
        "/opt/homebrew/Caskroom/miniconda/base/bin/python3",
        "/opt/homebrew/Caskroom/anaconda/base/bin/python3",
        "/opt/anaconda3/bin/python3",
        "/usr/local/anaconda3/bin/python3",
        str(Path.home() / "anaconda3" / "bin" / "python3"),
        str(Path.home() / "miniconda3" / "bin" / "python3"),
    ]
    for p in conda_bases:
        if Path(p).exists() and p not in candidates:
            candidates.append(p)

    # python3 on PATH as last resort (covers shell with conda activated)
    py3 = shutil.which("python3")
    if py3 and py3 not in candidates:
        candidates.append(py3)

    result: str | None = None
    for candidate in candidates:
        try:
            r = subprocess.run(
                [candidate, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                # Output: "Python 3.13.2"
                parts = r.stdout.strip().split()
                if len(parts) == 2:
                    ver_parts = parts[1].split(".")
                    major, minor = int(ver_parts[0]), int(ver_parts[1])
                    if (major, minor) >= (3, 13):
                        result = candidate
                        break
        except Exception:
            continue

    _py313_cache = (result, time.monotonic())
    return result


def _invalidate_caches() -> None:
    """Invalidate discovery and install caches (call after install/uninstall)."""
    global _py313_cache, _installed_cache
    _py313_cache = (None, 0.0)
    _installed_cache = (False, 0.0)


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

    def _runtime_python(self) -> str:
        """Return the Python executable to use for this engine.

        Prefers: (1) a Python >=3.13 that already has fast-dllm-mlx installed,
        (2) any Python >=3.13 found on the machine.
        Falls back to sys.executable with a warning logged if nothing found.
        """
        py313 = _find_python313()
        return py313 if py313 else sys.executable

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Launch diffusion_server.py as a subprocess.

        Runs diffusion_server.py directly by absolute path using a Python >=3.13
        interpreter (discovered at runtime).  This avoids requiring fast-dllm-mlx
        to be installed in the vmui Homebrew venv.
        """
        model_id = config.get("model", "mlx-community/DiffuCoder-7B-cpGRPO-8bit")
        host = config.get("host", "127.0.0.1")
        port = config.get("port", _DEFAULT_PORT)

        es = config.get("engine_settings", {}).get(self.id, {})
        steps = int(es.get("steps", 24))
        temperature = float(es.get("temperature", 0.4))
        block_length = int(es.get("block_length", 32))
        threshold = float(es.get("threshold", 0.9))

        # Run diffusion_server.py by absolute path — it has no vllm_mlx imports,
        # so it works with any Python that has fastapi + fast-dllm-mlx installed.
        server_script = str(Path(__file__).parent.parent / "diffusion_server.py")
        python = self._runtime_python()

        cmd = [
            python, server_script,
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
        """Return True if fast-dllm-mlx is importable under the runtime Python."""
        global _installed_cache
        installed, ts = _installed_cache
        if time.monotonic() - ts < _installed_cache_ttl:
            return installed

        python = _find_python313()
        if python is None:
            _installed_cache = (False, time.monotonic())
            return False

        try:
            r = subprocess.run(
                [python, "-c", "import fast_dllm_mlx"],
                capture_output=True, timeout=10,
            )
            result = r.returncode == 0
        except Exception:
            result = False

        _installed_cache = (result, time.monotonic())
        return result

    def get_version(self) -> str | None:
        """Return the installed fast-dllm-mlx version string, or None."""
        python = _find_python313() or sys.executable
        try:
            result = subprocess.run(
                [python, "-m", "pip", "show", "fast-dllm-mlx"],
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
        """Return a list of unmet requirements.

        Returns an error only if NO Python >=3.13 can be found on this machine.
        The vmui venv runs 3.11 but that is fine — we use a separate interpreter.
        """
        if _find_python313() is None:
            return [
                "fast-dllm-mlx requires Python ≥ 3.13, which was not found on this machine. "
                "Install Python 3.13+ via conda (recommended), Homebrew (brew install python@3.13), "
                "or python.org, then reinstall the engine."
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
        """Install fast-dllm-mlx and required server deps into the Python 3.13 env.

        Also installs fastapi/uvicorn/pydantic because diffusion_server.py is run
        as a standalone script under the 3.13 interpreter (not inside the vmui venv).
        """
        python = _find_python313()
        if python is None:
            # No 3.13 found — return a command that will fail with a clear message
            return [
                sys.executable, "-c",
                "import sys; sys.exit('ERROR: Python 3.13+ not found. Install via conda or brew install python@3.13')",
            ]
        _invalidate_caches()
        return [
            python, "-m", "pip", "install", "--upgrade",
            "fastapi", "uvicorn[standard]", "pydantic",
            "mlx-lm", "huggingface_hub",
            "git+https://github.com/MacPaw/Fast-dLLM-mlx",
        ]

    def uninstall_command(self) -> list[str]:
        python = _find_python313() or sys.executable
        _invalidate_caches()
        return [python, "-m", "pip", "uninstall", "-y", "fast-dllm-mlx"]

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
