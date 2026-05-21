# SPDX-License-Identifier: Apache-2.0
"""Ds4M5Engine — adapter for the DeepSeek V4 Flash (ds4) inference engine.

Auto-selects the best upstream fork based on your Apple Silicon chip:
  • M5 and newer → ``audreyt/ds4``  (M5 Metal Tensor: +~10% gen, +~5% prefill)
  • M1–M4         → ``antirez/ds4``  (original by Salvatore Sanfilippo; authoritative)

Both forks use the same ``antirez/deepseek-v4-gguf`` weights and expose identical
endpoints including ``/v1/responses`` (Codex CLI), ``/v1/messages`` (Claude Code),
and ``/v1/chat/completions``.

Requires an Apple Silicon Mac with ≥96 GB RAM (q2-imatrix, ~81 GB) or ≥256 GB
for q4-imatrix (~153 GB).  Typical generation: 26 t/s on M3 Max 128 GB, 38 t/s
on M5 Max 128 GB.

Install::

    git clone https://github.com/antirez/ds4.git   # M1–M4
    git clone https://github.com/audreyt/ds4.git    # M5+
    cd ds4 && make
    ./download_model.sh q2-imatrix

Launch:  ``./ds4-server --ctx 393216 --kv-disk-dir ~/.cache/ds4-kv``  (≥128 GB)
"""
from __future__ import annotations

import contextlib
import functools
import logging
import os
import platform
import re
import subprocess
from typing import Any, ClassVar

from .base import BaseEngine
from .flag_probe import add_if_supported

logger = logging.getLogger(__name__)

# ── Apple Silicon chip detection ─────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def detect_apple_chip() -> str | None:
    """Return ``"M1"``, ``"M2"``, ``"M3"``, ``"M4"``, ``"M5"`` etc. or ``None``.

    Cached after first call — hardware doesn't change during process lifetime.
    """
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=2,
        )
        m = re.search(r"Apple\s+(M\d+)", result.stdout.strip())
        if m:
            return m.group(1)
    except Exception as e:
        logger.warning("Failed to detect Apple chip: %s", e, exc_info=True)
    return None


@functools.lru_cache(maxsize=1)
def _chip_generation() -> int | None:
    """Return the Apple Silicon generation number (1=M1, 5=M5, …) or ``None``.

    Cached after first call.
    """
    chip = detect_apple_chip()
    if chip is None:
        return None
    m = re.match(r"M(\d+)", chip.upper())
    return int(m.group(1)) if m else None


def is_m5_chip() -> bool:
    """Return ``True`` if running on an Apple M5-series chip (kept for compatibility)."""
    return is_m5_or_newer()


def is_m5_or_newer() -> bool:
    """Return ``True`` if running on M5 or any newer Apple Silicon chip."""
    gen = _chip_generation()
    return gen is not None and gen >= 5


# ── Fork selection ────────────────────────────────────────────────────────────

_FORK_M5 = "audreyt"   # M5+: Metal Tensor optimization
_FORK_STD = "antirez"  # M1–M4: original, authoritative

_FORK_REPOS: dict[str, str] = {
    "antirez": "https://github.com/antirez/ds4.git",
    "audreyt": "https://github.com/audreyt/ds4.git",
}


def _select_fork() -> str:
    """Choose the best fork for the current machine (used for new installs)."""
    return _FORK_M5 if is_m5_or_newer() else _FORK_STD


def _detect_installed_fork(ds4_dir: str) -> str | None:
    """Read git remote origin and return ``"antirez"``, ``"audreyt"``, ``"swival"``, or ``None``."""
    git_dir = os.path.join(ds4_dir, ".git")
    if not os.path.isdir(git_dir):
        return None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ds4_dir, capture_output=True, text=True, timeout=5,
        )
        remote = result.stdout.strip().lower()
        if "audreyt" in remote:
            return "audreyt"
        if "antirez" in remote:
            return "antirez"
        if "swival" in remote:
            return "swival"
    except Exception as e:
        logger.warning("Failed to detect installed ds4 fork: %s", e, exc_info=True)
    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

# Legacy Swival install path (migrate → _DEFAULT_DS4_DIR on upgrade)
_LEGACY_DS4_DIR = os.path.expanduser("~/.local/share/ds4-m5")
# Canonical install path used for all new installs
_DEFAULT_DS4_DIR = os.path.expanduser("~/.local/share/ds4")

# HuggingFace repo that hosts the DeepSeek V4 Flash GGUF model files
_MODEL_HF_REPO = "antirez/deepseek-v4-gguf"


def _ds4_dir() -> str:
    """Resolve the ds4 install directory.

    Priority: ``$DS4_DIR`` env var → ``~/.local/share/ds4`` (new canonical) →
    ``~/.local/share/ds4-m5`` (legacy Swival fallback) → ``~/.local/share/ds4``.
    """
    explicit = os.environ.get("DS4_DIR")
    if explicit:
        return explicit
    if os.path.isdir(_DEFAULT_DS4_DIR):
        return _DEFAULT_DS4_DIR
    if os.path.isdir(_LEGACY_DS4_DIR):
        return _LEGACY_DS4_DIR
    return _DEFAULT_DS4_DIR


def _ds4_bin() -> str:
    """Return the absolute path to the ds4-server binary."""
    return os.path.join(_ds4_dir(), "ds4-server")


@functools.lru_cache(maxsize=1)
def _total_ram_gb() -> int:
    """Return total physical RAM in GB, or 0 if undetectable. Cached after first call."""
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
    except Exception as e:
        logger.warning("Failed to detect total RAM: %s", e, exc_info=True)
    return 0


def _free_ram_gb() -> int:
    """Return approximately available (free + inactive + speculative) RAM in GB.

    On Apple Silicon, inactive pages are reclaimed on demand, so this is a
    realistic estimate of how much RAM the OS can hand to a new process.
    Returns 0 if detection fails.
    """
    try:
        if platform.system() == "Darwin":
            # Get page size (4096 on Intel, 16384 on Apple Silicon)
            ps = subprocess.run(
                ["sysctl", "-n", "hw.pagesize"],
                capture_output=True, text=True, timeout=2,
            )
            page_size = int(ps.stdout.strip()) if ps.returncode == 0 else 16384

            vm = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=2,
            )
            free = inactive = speculative = 0
            for line in vm.stdout.splitlines():
                def _pages(l: str) -> int:
                    return int(l.split(":")[1].strip().rstrip("."))
                if "Pages free:" in line:
                    free = _pages(line)
                elif "Pages inactive:" in line:
                    inactive = _pages(line)
                elif "Pages speculative:" in line:
                    speculative = _pages(line)
            return (free + inactive + speculative) * page_size // (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024 // 1024
    except Exception as e:
        logger.warning("Failed to detect free RAM: %s", e, exc_info=True)
    return 0


def _recommended_quant() -> str:
    """Pick the best model quant for the available RAM."""
    ram = _total_ram_gb()
    if ram >= 256:
        return "q4-imatrix"
    return "q2-imatrix"


def _recommended_ctx_size() -> int:
    """Pick a context window size appropriate for available RAM.

    With the q2-imatrix model using ~74 GB:
    - ≥128 GB: 393216 (384K) → ~7.5 GB buffer → Think Max mode enabled
    - <128 GB: 131072 (128K) → ~2.5 GB buffer → leaves ~18 GB headroom on 96 GB
    """
    ram = _total_ram_gb()
    if ram >= 128:
        return 393216
    return 131072


def _download_script() -> str:
    return os.path.join(_ds4_dir(), "download_model.sh")


def _gguf_dir() -> str:
    return os.path.join(_ds4_dir(), "gguf")


# ── Engine adapter ──────────────────────────────────────────────────────────


class Ds4M5Engine(BaseEngine):
    """Adapter for the DeepSeek V4 Flash (ds4) inference engine."""

    id: ClassVar[str] = "ds4-m5"
    name: ClassVar[str] = "DeepSeek V4 Flash (ds4)"

    def _build_description(self) -> str:
        chip = detect_apple_chip()
        ram = _total_ram_gb()
        d = _ds4_dir()
        installed_fork = _detect_installed_fork(d)
        target_fork = _select_fork()

        if installed_fork == "swival":
            fork_line = (
                "⚠️  Legacy Swival fork detected — missing /v1/responses (Codex CLI).\n"
                "   Click 'Upgrade Engine' to migrate to the official fork without re-downloading the model."
            )
        elif installed_fork in ("antirez", "audreyt"):
            fork_line = f"Engine source: {installed_fork}/ds4 ✓"
        elif target_fork == _FORK_M5:
            fork_line = f"Will install: audreyt/ds4 (M5 Metal Tensor — ~10% faster generation)"
        else:
            chip_gen = _chip_generation()
            chip_label = f"M{chip_gen}" if chip_gen else (chip or "your chip")
            fork_line = f"Will install: antirez/ds4 (original by Salvatore Sanfilippo, optimised for {chip_label})"

        ram_info = ""
        if ram > 0:
            rec = _recommended_quant()
            ram_info = f"Detected {ram} GB RAM → auto-selects {rec} on install.  "

        speed_info = ""
        if chip:
            gen = _chip_generation()
            if gen == 5:
                speed_info = "M5 Max 128 GB: ~86 short-prefill / ~348 long-prefill / ~38 gen t/s."
            elif gen in (3, 4):
                speed_info = "M3 Max 128 GB: ~59 short-prefill / ~250 long-prefill / ~27 gen t/s."

        parts = [
            f"Specialised Metal inference engine for DeepSeek V4 Flash GGUF.\n{fork_line}",
        ]
        if ram_info or speed_info:
            parts.append(f"\n{ram_info}{speed_info}")
        parts.append(
            "\n\n⚠ HARDWARE ⚠ Apple Silicon Mac with ≥96 GB RAM (q2-imatrix ~81 GB)\n"
            "≥256 GB for q4-imatrix (~153 GB).  Full /v1/responses, /v1/messages (Claude Code) endpoints."
        )
        return "".join(parts)

    @property
    def description(self) -> str:
        try:
            return self._desc_cache
        except AttributeError:
            self._desc_cache = self._build_description()
            return self._desc_cache

    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "reasoning",
        "mtp",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    release_url: ClassVar[str] = "https://github.com/antirez/ds4"
    health_path: ClassVar[str] = "/v1/models"

    # ── Core BaseEngine implementation ───────────────────────────────────────

    def _find_gguf(self) -> str | None:
        """Scan the gguf/ directory for a .gguf file, or None."""
        gguf_dir = _gguf_dir()
        if not os.path.isdir(gguf_dir):
            return None
        for entry in sorted(os.listdir(gguf_dir)):
            if entry.endswith(".gguf"):
                return os.path.join(gguf_dir, entry)
        return None

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the ``ds4-server`` launch command."""
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        ds4_dir = _ds4_dir()
        binary = self._path_to_binary()

        # ── Model path ──────────────────────────────────────────────
        model = self.resolve_launch_model(config) or self._find_gguf()
        if not model:
            raise RuntimeError(
                "No GGUF model found for ds4. "
                "Run install first, or set a launch_model path in engine settings."
            )
        # Normalize to absolute path so --chdir doesn't affect model resolution
        model = os.path.abspath(model)

        cmd = [binary]
        cmd += ["--model", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8000))]

        ctx = int(engine_settings.get("ctx_size", _recommended_ctx_size()))
        cmd += ["--ctx", str(ctx)]

        # Per-request output token budget.  Setting this to 384000 (recommended
        # by the antirez/ds4 project for coding agents) effectively removes the
        # premature cap — the context window becomes the natural limit.  In
        # thinking mode the <think> section also counts against this limit, so
        # a value that is too small (e.g. 2048) exhausts the budget before any
        # answer is emitted.
        max_tokens = int(engine_settings.get("max_output_tokens", 384000))
        if max_tokens > 0:
            add_if_supported(cmd, (binary,), "--tokens", [str(max_tokens)])

        # --chdir: required so relative runtime paths (metal/*.metal shaders) resolve
        # from the ds4 source tree when launched from the dashboard working directory.
        add_if_supported(cmd, (binary,), "--chdir", [ds4_dir])

        # Disk KV cache — strongly recommended by the dev; defaults to
        # ~/.cache/ds4-kv if the user has not overridden it.
        kv_dir = os.path.abspath(os.path.expanduser(
            engine_settings.get("kv_disk_dir", "~/.cache/ds4-kv").strip()
        )) if engine_settings.get("kv_disk_dir", "~/.cache/ds4-kv").strip() else ""
        if kv_dir:
            cmd += ["--kv-disk-dir", kv_dir]

        kv_mb = int(engine_settings.get("kv_disk_space_mb", 8192))
        if kv_mb > 0:
            cmd += ["--kv-disk-space-mb", str(kv_mb)]

        mtp = engine_settings.get("mtp_model_path", "").strip()
        if mtp:
            cmd += ["--mtp", os.path.abspath(os.path.expanduser(mtp))]

        if engine_settings.get("mtp_draft"):
            cmd += ["--mtp-draft", str(int(engine_settings.get("mtp_draft", 2)))]

        if config.get("api_key"):
            add_if_supported(
                cmd, (binary,), "--api-key", [config["api_key"]],
                warn_if_unsupported=(
                    "ds4-server does not support --api-key in this version; "
                    "API key will not be enforced by the engine."
                ),
            )

        # Metal Tensor acceleration (audreyt fork, M5+).
        # --mt auto gracefully disables itself on pre-M5 hardware, but only the
        # audreyt fork includes the M5 Metal Tensor kernels that make it worthwhile.
        # Only probe on M5+ to avoid spurious --help calls on every launch on M1-M4.
        if is_m5_or_newer():
            add_if_supported(cmd, (binary,), "--mt", ["auto"])

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
        except Exception as e:
            logger.warning("Failed to read ds4 git version: %s", e, exc_info=True)
        try:
            result = subprocess.run(
                [self._path_to_binary(), "--help"],
                capture_output=True, text=True, timeout=5,
            )
            text = (result.stdout or result.stderr or "")
            lines = text.strip().splitlines()
            if lines:
                m = re.match(r"ds4[-\s]server[-\s]?(.*)", lines[0], re.IGNORECASE)
                return m.group(1) or lines[0] if m else lines[0]
        except Exception as e:
            logger.warning("Failed to read ds4 binary version: %s", e, exc_info=True)
        return None

    def latest_version(self) -> str | None:
        """Query GitHub for the latest commit on the installed (or target) fork."""
        try:
            import json as _json
            import urllib.request as _urllib

            d = _ds4_dir()
            installed_fork = _detect_installed_fork(d)
            # Use installed fork if known; otherwise use what would be installed
            fork = installed_fork if installed_fork in ("antirez", "audreyt") else _select_fork()
            url = f"https://api.github.com/repos/{fork}/ds4/commits/main"
            try:
                with _urllib.urlopen(url, timeout=5) as resp:
                    data = _json.loads(resp.read().decode())
                    sha = data.get("sha", "")
                    if sha:
                        return sha[:12]
            except Exception as e:
                logger.warning("Failed to query GitHub for latest ds4 version: %s", e)
        except Exception as e:
            logger.warning("Failed to query GitHub for latest ds4 version: %s", e)
        return None

    def get_working_directory(self) -> str | None:
        return _ds4_dir()

    def check_requirements(self) -> list[str]:
        """Return hardware/OS requirement errors for this engine.

        Checks:
        1. macOS is required (Metal/Apple GPU).
        2. Apple Silicon (M1+) is required — Intel Macs cannot use Metal.
        3. At least 96 GB total RAM is required for the q2-imatrix model (~81 GB).
           (Use check_warnings() for low *free* RAM — that's a runtime condition.)
        """
        errors: list[str] = []

        if platform.system() != "Darwin":
            errors.append(
                f"Requires macOS (Apple Silicon Mac). "
                f"Your system is {platform.system()}."
            )
            # No point checking further — not macOS at all
            return errors

        chip = detect_apple_chip()
        if chip is None:
            errors.append(
                "Requires an Apple Silicon Mac (M1 or newer). "
                "Intel Macs are not supported — this engine uses Metal GPU acceleration."
            )

        total = _total_ram_gb()
        if 0 < total < 96:
            errors.append(
                f"Requires at least 96 GB of RAM — your machine has {total} GB total. "
                f"The q2-imatrix model uses ~81 GB of unified memory."
            )

        return errors

    def check_warnings(self) -> list[str]:
        """Return advisory warnings about current memory conditions.

        Your machine may have enough total RAM to run this engine, but if other
        apps are consuming most of it right now, the engine may fail to start.
        This does NOT block install — it informs the user.
        """
        warnings: list[str] = []

        total = _total_ram_gb()
        if total < 96:
            # Already blocked by check_requirements() — no need to warn too
            return warnings

        free = _free_ram_gb()
        if 0 < free < 96:
            warnings.append(
                f"Your machine has {total} GB total RAM (enough to run this engine), "
                f"but only ~{free} GB is currently free. "
                f"Close other apps and quit Safari/Chrome before starting — "
                f"the q2-imatrix model needs ~81 GB of free unified memory."
            )

        return warnings

    def upgrade_command(self) -> list[str] | None:
        """Return a command that updates and rebuilds the ds4 engine.

        If a legacy Swival install is detected the command migrates to the correct
        fork — cloning into ``~/.local/share/ds4`` and copying the existing model
        files so an 80+ GB re-download is not required.
        """
        d = _ds4_dir()
        installed_fork = _detect_installed_fork(d)

        if installed_fork == "swival":
            # Migrate: clone correct fork, build, copy existing model files
            target_fork = _select_fork()
            fork_url = _FORK_REPOS[target_fork]
            new_dir = _DEFAULT_DS4_DIR
            old_gguf = shlex_quote(os.path.join(d, "gguf"))
            new_gguf = shlex_quote(os.path.join(new_dir, "gguf"))
            nq = shlex_quote(new_dir)
            furl = shlex_quote(fork_url)
            return [
                "sh", "-c",
                f"echo '=== Migrating from Swival fork to {target_fork}/ds4 ===' "
                f"&& mkdir -p {shlex_quote(os.path.dirname(new_dir))} "
                f"&& git clone {furl} {nq} "
                f"&& cd {nq} "
                f"&& make -j$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4) "
                f"&& if [ -d {old_gguf} ] && [ ! -d {new_gguf} ]; then "
                f"echo '=== Copying existing model files (no re-download needed) ===' "
                f"&& cp -r {old_gguf} {new_gguf}; fi "
                f"&& echo '=== Migration complete — now using {target_fork}/ds4 ==='",
            ]

        if not os.path.isdir(os.path.join(d, ".git")):
            return None

        return [
            "sh", "-c",
            f"cd {shlex_quote(d)} && git pull && make clean && make -j$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4)",
        ]

    def install_command(self) -> list[str]:
        """Clone the correct fork for this machine, build, and download the recommended model."""
        d = _ds4_dir()
        quant = _recommended_quant()
        fork = _select_fork()
        fork_url = _FORK_REPOS[fork]
        ram = _total_ram_gb()
        fork_note = (
            "M5 Metal Tensor fork (audreyt/ds4)" if fork == _FORK_M5
            else "original upstream fork (antirez/ds4)"
        )
        return [
            "sh", "-c",
            f"mkdir -p {shlex_quote(os.path.dirname(d))} "
            f"&& echo '=== Step 1/2: Cloning ds4 engine ({fork_note}) ===' "
            f"&& git clone {shlex_quote(fork_url)} {shlex_quote(d)} "
            f"&& cd {shlex_quote(d)} "
            f"&& echo '=== Step 2/2: Building inference engine... ===' "
            f"&& make -j$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4) "
            f"&& echo '=== Build complete. Now downloading model ({quant})... ===' "
            f"&& echo 'Auto-selected {quant} based on {ram} GB RAM detected.' "
            f"&& echo 'Downloading DeepSeek V4 Flash GGUF weights from HuggingFace.' "
            f"&& echo 'This may take 10-30 minutes depending on your internet connection.' "
            f"&& ./download_model.sh {quant} "
            f"&& echo '=== Install complete! Engine + model ready. ==='",
        ]

    def uninstall_command(self) -> list[str]:
        """Remove the ds4 engine directory."""
        d = _ds4_dir()
        return [
            "sh", "-c",
            f"echo '=== Removing ds4 from {shlex_quote(d)} ===' "
            f"&& rm -rf {shlex_quote(d)} "
            f"&& echo '=== Uninstall complete. ==='",
        ]

    # ── Model version/info ──────────────────────────────────────────────────────

    def _model_get_version(self) -> str | None:
        """Return the installed model's version (HF commit SHA or mtime hash)."""
        gguf = self._find_gguf()
        if not gguf:
            return None
        try:
            mtime = os.path.getmtime(gguf)
            import datetime
            return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except OSError:
            return None

    def hf_model_latest(self) -> str | None:
        """Check the HF model repo for the latest update date."""
        if not _MODEL_HF_REPO:
            return None
        try:
            import json as _json
            import urllib.request as _urllib
            url = f"https://huggingface.co/api/models/{_MODEL_HF_REPO}"
            with _urllib.urlopen(url, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            last_modified = data.get("lastModified", "")
            if last_modified:
                import datetime
                dt = datetime.datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            siblings = data.get("siblings", [])
            for sib in siblings:
                lm = sib.get("lastModified", sib.get("rfilename", ""))
                if lm:
                    return str(lm)[:10]
        except Exception as e:
            logger.warning("Failed to check HF model latest version: %s", e, exc_info=True)
            return None
        return None

    def model_update_available(self) -> bool:
        """Return True when a newer model version is available on HF."""
        installed = self._model_get_version()
        latest = self.hf_model_latest()
        if not installed or not latest:
            return False
        return latest > installed

    def model_upgrade_command(self) -> list[str] | None:
        """Re-download the model for the current quantization."""
        d = _ds4_dir()
        scripts = ["download_model.sh", os.path.join(d, "download_model.sh")]
        script = next((s for s in scripts if os.path.isfile(s)), None)
        if not script:
            return None
        quant = _recommended_quant()
        engine_settings = {}  # populated at runtime
        return [
            "sh", "-c",
            f"cd {shlex_quote(d)} && echo '=== Re-downloading model ({quant}) ===' "
            f"&& bash {shlex_quote(script)} {quant} "
            f"&& echo '=== Model update complete. ==='",
        ]

    def get_fixed_model_display(self) -> str | None:
        """ds4 serves a single fixed GGUF — report it so the UI shows a label."""
        gguf = self._find_gguf()
        if gguf:
            return f"DeepSeek V4 Flash ({os.path.basename(gguf)})"
        return "DeepSeek V4 Flash"

    def get_discovered_models(self) -> list[dict[str, Any]]:
        gguf = self._find_gguf()
        if not gguf:
            return []
        name = os.path.basename(gguf)
        size_gb = 0.0
        with contextlib.suppress(OSError):
            size_gb = round(os.path.getsize(gguf) / (1024 ** 3), 2)
        return [{
            "id": f"ds4:{name}",
            "name": name,
            "path": gguf,
            "size_gb": size_gb,
            "engine": self.id,
            "display": f"DeepSeek V4 Flash ({name})",
            "cached": True,
        }]

    def config_schema(self) -> list[dict[str, Any]]:
        default_quant = _recommended_quant()
        default_ctx = _recommended_ctx_size()

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
                "default": default_ctx,
                "min": 2048,
                "max": 1_000_000,
                "help": (
                    "Maximum context length (KV cache size). "
                    "Auto-detected based on available RAM. "
                    "≥128 GB RAM: 393216 (384K, ~7.5 GB) — full Think Max mode available. "
                    "<128 GB RAM: 131072 (128K, ~2.5 GB) — normal thinking, reliable chat. "
                    "Full 1M context requires ~26 GB extra."
                ),
            },
            {
                "key": "max_output_tokens",
                "label": "Max Output Tokens (--tokens)",
                "type": "int",
                "default": 384000,
                "min": 1024,
                "max": 393216,
                "help": (
                    "Per-request output token limit passed to ds4-server as --tokens. "
                    "384000 (recommended by the ds4 project for coding agents) effectively removes "
                    "premature caps — the context window becomes the natural limit. "
                    "In thinking mode, both the <think> section AND the answer count against this. "
                    "Reduce to 65536 for interactive chat to free KV cache for new requests."
                ),
            },
            {
                "key": "kv_disk_dir",
                "label": "Disk KV Cache Directory",
                "type": "str",
                "default": "~/.cache/ds4-kv",
                "help": (
                    "Directory for disk-backed KV cache. "
                    "Strongly recommended — saves expensive prefill work across sessions and server restarts. "
                    "Leave blank to disable."
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
            # ── Reproducibility ──────────────────────────────────────────
            {
                "key": "reproducible",
                "label": "Reproducible Output (DS4_REPRODUCIBLE=1)",
                "type": "bool",
                "default": True,
                "help": (
                    "Set DS4_REPRODUCIBLE=1 when launching ds4-server. "
                    "Injects seed 42 and produces stable tool-call IDs — "
                    "every run with the same prompt returns the same output. "
                    "Recommended for auditability. Disable if you prefer varied responses."
                ),
            },
        ]

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        env: dict[str, str] = {}
        # DS4_REPRODUCIBLE=1: injects seed 42 and stable tool-call IDs so every
        # run with the same prompt produces the same output — recommended by the
        # antirez/ds4 project for auditability.  Users can opt out via settings.
        if engine_settings.get("reproducible", True):
            env["DS4_REPRODUCIBLE"] = "1"
        return env or None

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the GGUF model path — configured, auto-discovered, or empty."""
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        explicit = engine_settings.get("launch_model", "").strip()
        if explicit:
            return os.path.expanduser(explicit)
        # Auto-discover the GGUF in the install directory
        found = self._find_gguf()
        if found:
            return found
        return ""


def shlex_quote(s: str) -> str:
    """Minimal shell quoting for a single path argument."""
    return "'" + s.replace("'", "'\\''") + "'"
