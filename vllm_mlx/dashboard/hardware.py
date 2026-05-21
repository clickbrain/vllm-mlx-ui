# SPDX-License-Identifier: Apache-2.0
"""Hardware fingerprinting — chip, RAM, OS, MLX version capture.

Used by benchmark runners to tag every result with reproducible hardware
context, enabling cross-machine comparison and community aggregation.
"""

from __future__ import annotations

import functools
import platform
import re
import subprocess
from typing import Any


def _sysctl_str(key: str) -> str:
    try:
        return subprocess.run(
            ["sysctl", "-n", key], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def _sysctl_int(key: str) -> int | None:
    try:
        return int(_sysctl_str(key))
    except (ValueError, TypeError):
        return None


def detect_chip() -> str:
    brand = _sysctl_str("machdep.cpu.brand_string")
    if brand:
        return brand
    machine = platform.machine()
    if machine == "arm64":
        return "Apple Silicon (unknown variant)"
    return machine


def chip_generation(chip_str: str) -> str:
    m = re.search(r"M(\d)", chip_str)
    if m:
        return f"M{m.group(1)}"
    if "Intel" in chip_str:
        return "Intel"
    return "Unknown"


def total_ram_gb() -> float:
    mem = _sysctl_int("hw.memsize")
    if mem:
        return mem / (1024 ** 3)
    return 0.0


def os_version() -> str:
    try:
        return platform.mac_ver()[0] or _sysctl_str("kern.osversion") or ""
    except Exception:
        return ""


def mlx_version() -> str:
    try:
        import mlx.core as _mx
        return getattr(_mx, "__version__", "")
    except ImportError:
        try:
            import mlx as _mlx
            return getattr(_mlx, "__version__", "")
        except ImportError:
            return ""
    except Exception:
        return ""


def dashboard_version() -> str:
    try:
        from vllm_mlx.dashboard import __version__
        return __version__
    except Exception:
        return ""


@functools.lru_cache(maxsize=1)
def fingerprint() -> dict[str, Any]:
    chip = detect_chip()
    return {
        "chip": chip,
        "chip_gen": chip_generation(chip),
        "total_ram_gb": round(total_ram_gb(), 1),
        "os_version": os_version(),
        "python_version": platform.python_version(),
        "mlx_version": mlx_version(),
        "dashboard_version": dashboard_version(),
    }
