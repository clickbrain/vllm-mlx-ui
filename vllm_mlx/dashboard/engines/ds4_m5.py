# SPDX-License-Identifier: Apache-2.0
"""Ds4M5Engine — adapter for the DeepSeek V4 Flash inference engine with M5 optimizations.

The ds4-m5 engine (github.com/Swival/ds4-m5) is a specialised native Metal/CUDA
inference engine for DeepSeek V4 Flash GGUF models.  It provides an OpenAI-compatible
server with native thinking/reasoning support, tool calls via DSML, and a disk-backed
KV cache for long-context sessions.

Requires an Apple Silicon Mac (M1–M5) with **at least 96 GB of RAM** for the
2-bit quantised model (q2-imatrix) and 256 GB+ for the 4-bit quant (q4-imatrix).
The ``m5`` branch includes M5-specific Metal optimisations that provide ~1.86x
prefill and ~1.45x generation speedup on Apple M5 Max hardware.

Install::

    git clone -b m5 https://github.com/Swival/ds4-m5.git
    cd ds4-m5 && make
    ./download_model.sh q2-imatrix   # or q4-imatrix

Launch:  ``./ds4-server --ctx 100000 --kv-disk-dir /tmp/ds4-kv``
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import Any, ClassVar

from .base import BaseEngine

# ── Apple Silicon chip detection ─────────────────────────────────────────────

def detect_apple_chip() -> str | None:
    """Detect the Apple Silicon chip generation.

    Returns ``"M1"``, ``"M2"``, ``"M3"``, ``"M4"``, ``"M5"`` or ``None``
    when not running on Apple Silicon.
    """
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=2,
        )
        variant = result.stdout.strip()
        m = re.search(r"Apple\s+(M\d+)", variant)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def is_m5_chip() -> bool:
    """Return ``True`` if running on an Apple M5-series chip."""
    chip = detect_apple_chip()
    return chip is not None and chip.upper().startswith("M5")


# ── Helpers ──────────────────────────────────────────────────────────────────

_DEFAULT_DS4_DIR = os.path.expanduser("~/.local/share/ds4-m5")


def _ds4_dir() -> str:
    return os.environ.get("DS4_DIR") or _DEFAULT_DS4_DIR


def _ds4_bin() -> str:
    return os.path.join(_ds4_dir(), "ds4-server")


def _total_ram_gb() -> int:
    """Return total physical RAM in GB, or 0 if undetectable."""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=2,
            )
            return int(result.stdout.strip()) // (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024 // 1024
    except Exception:
        pass
    return 0


def _recommended_quant() -> str:
    """Pick the best model quant for the available RAM."""
    ram = _total_ram_gb()
    if ram >= 256:
        return "q4-imatrix"
    return "q2-imatrix"


def _download_script() -> str:
    return os.path.join(_ds4_dir(), "download_model.sh")


def _gguf_dir() -> str:
    return os.path.join(_ds4_dir(), "gguf")


# ── Engine adapter ──────────────────────────────────────────────────────────


class Ds4M5Engine(BaseEngine):
    """Adapter for the DeepSeek V4 Flash inference engine (ds4-m5)."""

    id: ClassVar[str] = "ds4-m5"
    name: ClassVar[str] = "ds4-m5 (DeepSeek V4 Flash)"

    @property
    def description(self) -> str:
        chip = detect_apple_chip()
        ram = _total_ram_gb()

        chip_info = ""
        if chip and chip.upper().startswith("M5"):
            chip_info = " M5-optimised — ~1.86× prefill, ~1.45× gen."
        elif chip:
            chip_info = f" Running on {chip} (m5 branch works on all Apple Silicon)."

        ram_info = ""
        if ram > 0:
            rec = _recommended_quant()
            ram_info = f" Detected {ram} GB RAM — will auto-select {rec} on install."

        return (
            f"Specialised Metal inference engine for DeepSeek V4 Flash GGUF.{chip_info}{ram_info}\n\n"
            f"⚠ HARDWARE ⚠ Apple Silicon Mac with ≥96 GB RAM (q2-imatrix ~81 GB)\n"
            f"≥256 GB for q4-imatrix (~153 GB). 1M ctx ~ +26 GB. M3 Ultra / M5 recommended."
        )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "reasoning",
        "mtp",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    release_url: ClassVar[str] = "https://github.com/Swival/ds4-m5"
    health_path: ClassVar[str] = "/v1/models"

    # ── Core BaseEngine implementation ───────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the ``ds4-server`` launch command."""
        engine_settings = config.get("engine_settings", {}).get(self.id, {})

        cmd = [self._path_to_binary()]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        ctx = int(engine_settings.get("ctx_size", 100000))
        cmd += ["--ctx", str(ctx)]

        kv_dir = engine_settings.get("kv_disk_dir", "").strip()
        if kv_dir:
            cmd += ["--kv-disk-dir", kv_dir]

        kv_mb = int(engine_settings.get("kv_disk_space_mb", 8192))
        if kv_mb > 0:
            cmd += ["--kv-disk-space-mb", str(kv_mb)]

        mtp = engine_settings.get("mtp_model_path", "").strip()
        if mtp:
            cmd += ["--mtp", mtp]

        if engine_settings.get("mtp_draft"):
            cmd += ["--mtp-draft", str(int(engine_settings.get("mtp_draft", 2)))]

        if config.get("api_key"):
            cmd += ["--api-key", config["api_key"]]

        if engine_settings.get("nothink"):
            cmd += ["--nothink"]

        return cmd

    def _path_to_binary(self) -> str:
        return _ds4_bin()

    def _which(self, cmd: str) -> str | None:
        if cmd in ("ds4-server", "ds4"):
            path = self._path_to_binary()
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return super()._which(cmd)

    def is_installed(self) -> bool:
        path = self._path_to_binary()
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def get_version(self) -> str | None:
        """Read version via git tag or fall back to the binary's help text."""
        try:
            d = _ds4_dir()
            if os.path.isdir(os.path.join(d, ".git")):
                result = subprocess.run(
                    ["git", "-C", d, "describe", "--tags", "--always"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    v = result.stdout.strip()
                    if v:
                        return v
        except Exception:
            pass
        try:
            result = subprocess.run(
                [self._path_to_binary(), "--help"],
                capture_output=True, text=True, timeout=5,
            )
            text = (result.stdout or result.stderr or "")
            # Fallback: return first line as version info
            lines = text.strip().splitlines()
            if lines:
                m = re.match(r"ds4[-\s]server[-\s]?(.*)", lines[0], re.IGNORECASE)
                return m.group(1) or lines[0] if m else lines[0]
        except Exception:
            pass
        return None

    def latest_version(self) -> str | None:
        """Query GitHub for the latest ds4-m5 commit."""

        try:
            import json as _json
            import urllib.request as _urllib

            with _urllib.request.urlopen(
                "https://api.github.com/repos/Swival/ds4-m5/commits/m5",
                timeout=5,
            ) as resp:
                data = _json.loads(resp.read().decode())
                sha = data.get("sha", "")
                return sha[:12] if sha else None
        except Exception:
            return None

    def upgrade_command(self) -> list[str] | None:
        """Return a command that pulls the latest code and rebuilds."""
        d = _ds4_dir()
        if not os.path.isdir(os.path.join(d, ".git")):
            return None
        return [
            "sh", "-c",
            f"cd {shlex_quote(d)} && git pull && make clean && make -j$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4)",
        ]

    def install_command(self) -> list[str]:
        """Clone the m5 branch, build, and download the recommended model for this machine."""
        d = _ds4_dir()
        quant = _recommended_quant()
        return [
            "sh", "-c",
            f"mkdir -p {shlex_quote(os.path.dirname(d))} "
            f"&& echo '=== Step 1/2: Cloning ds4-m5 engine (m5 branch) ===' "
            f"&& git clone -b m5 https://github.com/Swival/ds4-m5.git {shlex_quote(d)} "
            f"&& cd {shlex_quote(d)} "
            f"&& echo '=== Step 2/2: Building inference engine... ===' "
            f"&& make -j$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4) "
            f"&& echo '=== Build complete. Now downloading model ({quant})... ===' "
            f"&& echo 'Auto-selected {quant} based on {_total_ram_gb()} GB RAM detected.' "
            f"&& echo 'This downloads the DeepSeek V4 Flash GGUF weights from HuggingFace.' "
            f"&& echo 'It may take 10-30 minutes depending on your internet connection.' "
            f"&& ./download_model.sh {quant} "
            f"&& echo '=== Install complete! Engine + model ready. ==='",
        ]

    def config_schema(self) -> list[dict[str, Any]]:
        default_quant = _recommended_quant()


        return [
            # ── Model selector ────────────────────────────────────────────
            {
                "key": "quantization",
                "label": "Model Quantization",
                "type": "select",
                "default": default_quant,
                "options": [
                    {"value": "q2-imatrix", "label": "q2-imatrix — 96/128 GB RAM (recommended)"},
                    {"value": "q4-imatrix", "label": "q4-imatrix — 256+ GB RAM"},
                    {"value": "q2", "label": "q2 — legacy, 96/128 GB RAM"},
                    {"value": "q4", "label": "q4 — legacy, 256+ GB RAM"},
                ],
                "help": (
                    "Which DeepSeek V4 Flash GGUF variant to download and serve. "
                    "Auto-detected based on available RAM on this machine. "
                    "The model is downloaded via ``download_model.sh`` into ``gguf/``."
                ),
            },
            # ── Context / performance ────────────────────────────────────
            {
                "key": "ctx_size",
                "label": "Context Window (tokens)",
                "type": "int",
                "default": 100000,
                "min": 2048,
                "max": 1_000_000,
                "help": (
                    "Maximum context length.  Larger contexts use more memory. "
                    "With 128 GB RAM and q2, 100k-300k is typical. "
                    "Full 1M context requires ~26 GB extra for the compressed indexer."
                ),
            },
            {
                "key": "kv_disk_dir",
                "label": "Disk KV Cache Directory",
                "type": "str",
                "default": "",
                "help": (
                    "Directory for disk-backed KV cache (enables session persistence "
                    "across server restarts).  Leave blank to disable. "
                    "Example: /tmp/ds4-kv or ~/.cache/ds4-kv"
                ),
            },
            {
                "key": "kv_disk_space_mb",
                "label": "Disk KV Cache Size (MB)",
                "type": "int",
                "default": 8192,
                "min": 512,
                "max": 65536,
                "help": "Maximum disk space for the KV cache directory.",
            },
            {
                "key": "nothink",
                "label": "Disable Thinking Mode",
                "type": "bool",
                "default": False,
                "help": (
                    "Start with thinking/reasoning disabled by default. "
                    "Clients can still request thinking via the API."
                ),
            },
            # ── MTP speculative decoding ─────────────────────────────────
            {
                "key": "mtp_model_path",
                "label": "MTP Draft Model Path",
                "type": "str",
                "default": "",
                "help": (
                    "Path to an MTP speculative-decoding GGUF file. "
                    "Download with ``./download_model.sh mtp`` first. "
                    "Currently experimental — slight speedup only with greedy decoding."
                ),
            },
            {
                "key": "mtp_draft",
                "label": "MTP Draft Tokens",
                "type": "int",
                "default": 2,
                "min": 1,
                "max": 5,
                "help": "Number of speculative tokens for MTP draft (1-5). Only active when MTP model path is set.",
            },
        ]

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        return None

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """ds4 uses a local GGUF path — return the configured path or default."""
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        return engine_settings.get("launch_model") or config.get("model", "")


def shlex_quote(s: str) -> str:
    """Minimal shell quoting for a single path argument."""
    return "'" + s.replace("'", "'\\''") + "'"
