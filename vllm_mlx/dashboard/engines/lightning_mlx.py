# SPDX-License-Identifier: Apache-2.0
"""LightningMlxEngine — adapter for the lightning-mlx inference engine.

lightning-mlx (github.com/samuelfaj/lightning-mlx) is a performance-focused
MLX inference server for Apple Silicon with MTPLX speculative decoding (MTP +
n-gram stacked drafting).  It is built on Rapid-MLX and MTPLX and delivers
2–5x higher throughput than mlx-lm on MTPLX-packaged models (e.g. the
Qwen3.6-35B-A3B MTPLX-Optimized-Speed family).

Install:  pip install git+https://github.com/samuelfaj/lightning-mlx.git
Launch:   lightning-mlx serve <model> --host <h> --port <p> [flags...]
Default port: 8010

CLI flags verified against the lightning-mlx README
(github.com/samuelfaj/lightning-mlx) on 2026-05-29.

Model identifiers:
  lightning-mlx accepts HF repo IDs and curated short aliases.  The dashboard
  always stores the canonical HF repo ID in config["model"].  An optional
  config["engine_settings"]["lightning-mlx"]["launch_model"] override lets
  users map to a lightning-mlx alias without changing the canonical model ID.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any, ClassVar

from .base import BaseEngine

# Curated alias → canonical HF repo ID map (from lightning-mlx README).
# IMPORTANT: Only include aliases where the mapping is exact and bidirectional.
# Prefer passing the full HF repo ID when in doubt — lightning-mlx accepts
# both aliases and canonical HF repo IDs, and the alias can change between
# lightning-mlx versions.
LIGHTNING_MLX_ALIASES: dict[str, str] = {
    "qwopus3.6-35b-8bit":            "samuelfaj/Qwopus3.6-35B-A3B-v1-8bit-MTPLX-Optimized-Speed",
    "qwopus3.6-35b-4bit":            "samuelfaj/Qwopus3.6-35B-A3B-v1-4bit-MTPLX-Optimized-Speed",
    "ornstein3.6-35b-saber-8bit":    "samuelfaj/Ornstein3.6-35B-A3B-SABER-8bit-MTPLX-Optimized-Speed",
    "ornstein3.6-35b-saber-4bit":    "samuelfaj/Ornstein3.6-35B-A3B-SABER-4bit-MTPLX-Optimized-Speed",
    "qwen3.6-35b-nsc-ace-saber-8bit": "samuelfaj/Qwen3.6-35B-A3B-NSC-ACE-SABER-MLX-8bit-MTPLX-Optimized-Speed",
    "qwen3.6-35b-nsc-ace-saber-4bit": "samuelfaj/Qwen3.6-35B-A3B-NSC-ACE-SABER-MLX-4bit-MTPLX-Optimized-Speed",
    "ornstein3.6-27b-nsc-ace-saber-8bit": "samuelfaj/Ornstein3.6-27B-MTP-NSC-ACE-SABER-8bit-MTPLX-Optimized-Speed",
    "ornstein3.6-27b-nsc-ace-saber-4bit": "samuelfaj/Ornstein3.6-27B-MTP-NSC-ACE-SABER-4bit-MTPLX-Optimized-Speed",
}

# Inverse map for alias lookup by canonical HF repo ID.
_HF_TO_ALIAS: dict[str, str] = {v: k for k, v in LIGHTNING_MLX_ALIASES.items()}


class LightningMlxEngine(BaseEngine):
    """Adapter for the lightning-mlx inference engine."""

    id: ClassVar[str] = "lightning-mlx"
    name: ClassVar[str] = "Lightning MLX"
    description: ClassVar[str] = (
        "The fastest local AI engine for Apple Silicon. "
        "Delivers 2–5× higher throughput than mlx-lm on MTPLX-packaged models "
        "via stacked MTP + n-gram speculative decoding. "
        "Purpose-built for the Qwen3.6-35B-A3B family and MTPLX-Optimized-Speed checkpoints. "
        "Install: pip install git+https://github.com/samuelfaj/lightning-mlx.git"
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "reasoning",
        "mtp",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "pip"
    homepage_url: ClassVar[str] = "https://github.com/samuelfaj/lightning-mlx"
    release_url: ClassVar[str] = "https://github.com/samuelfaj/lightning-mlx/releases"
    health_path: ClassVar[str] = "/v1/models"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def _resolve_cmd(self) -> list[str]:
        """Return the argv prefix for lightning-mlx binary."""
        found = self._which("lightning-mlx")
        return [found] if found else []

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the lightning-mlx serve command."""
        model = self._resolve_launch_model(config)

        cmd = self._resolve_cmd()
        if not cmd:
            raise RuntimeError(
                "lightning-mlx is not installed. "
                "Run: pip install git+https://github.com/samuelfaj/lightning-mlx.git"
            )

        cmd += ["serve", model]
        cmd += ["--host", str(config.get("host", "127.0.0.1"))]
        cmd += ["--port", str(config.get("port", 8010))]
        # Pass the canonical HF repo ID so /v1/status reports the real model name
        # instead of the default "local" placeholder set by the underlying CLI.
        canonical = config.get("model") or model
        if canonical:
            cmd += ["--served-model-name", canonical]

        es = config.get("engine_settings", {}).get(self.id, {})

        # --- MTP speculative decoding ---
        mtp_draft = es.get("mtp_num_draft_tokens", 5)
        if mtp_draft and mtp_draft > 0:
            cmd += ["--mtp-num-draft-tokens", str(mtp_draft)]
        if es.get("mtp_optimistic", True):
            cmd += ["--mtp-optimistic"]

        # --- N-gram speculation ---
        if es.get("disable_ngram", False):
            cmd += ["--disable-ngram"]

        # --- Prefill step size ---
        prefill = es.get("prefill_step_size", 0)
        if prefill and prefill > 0:
            cmd += ["--prefill-step-size", str(prefill)]

        # --- Thinking ---
        if es.get("no_thinking", False):
            cmd += ["--no-thinking"]

        # --- Daemon mode ---
        if es.get("daemon", False):
            cmd += ["--daemon"]

        return cmd

    def _resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the model token for the command line.

        Preference order:
        1. ``engine_settings["lightning-mlx"]["launch_model"]`` — explicit override
        2. Known alias for the canonical HF repo ID
        3. Canonical HF repo ID directly
        """
        es = config.get("engine_settings", {}).get(self.id, {})
        if es.get("launch_model"):
            return es["launch_model"]
        canonical = config.get("model", "")
        return _HF_TO_ALIAS.get(canonical, canonical)

    def install_command(self) -> list[str]:
        return [
            sys.executable, "-m", "pip", "install",
            "git+https://github.com/samuelfaj/lightning-mlx.git",
        ]

    def get_package_name(self) -> str:
        # lightning-mlx is not on PyPI; use the git URL so that
        # process_pending_engine_reinstalls() can restore it after brew upgrade.
        return "git+https://github.com/samuelfaj/lightning-mlx.git"

    def latest_version(self) -> str | None:
        """Return the latest lightning-mlx release tag from GitHub."""
        try:
            import urllib.request
            import json as _json
            url = "https://api.github.com/repos/samuelfaj/lightning-mlx/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "vllm-mlx-ui"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read())
                return data.get("tag_name", "").lstrip("v") or None
        except Exception:
            return None

    def uninstall_command(self) -> list[str]:
        return [sys.executable, "-m", "pip", "uninstall", "-y", "lightning-mlx"]

    def upgrade_command(self) -> list[str] | None:
        return [
            sys.executable, "-m", "pip", "install", "--upgrade",
            "git+https://github.com/samuelfaj/lightning-mlx.git",
        ]

    def is_installed(self) -> bool:
        if self._which("lightning-mlx"):
            return True
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "lightning-mlx"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        return False

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:
        """Pass HF_HUB_CACHE so the subprocess uses the configured models directory."""
        try:
            from ..model_manager import get_hf_cache_dir
            cache_dir = get_hf_cache_dir()
            return {"HF_HUB_CACHE": cache_dir}
        except Exception:
            return None

    def get_version(self) -> str | None:
        try:
            cmd = self._resolve_cmd() + ["--version"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                line = (result.stdout or result.stderr or "").strip()
                parts = line.split()
                return parts[-1] if parts else None
        except Exception:
            pass
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "lightning-mlx"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.lower().startswith("version:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    def validate_model_id(self, model_id: str) -> bool:
        if "/" in model_id:
            return True
        return model_id.lower() in LIGHTNING_MLX_ALIASES

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "mtp_num_draft_tokens",
                "label": "MTP Draft Tokens",
                "type": "int",
                "default": 5,
                "min": 1,
                "max": 10,
                "help": (
                    "Number of draft tokens per MTP speculative step. "
                    "5 is the optimised default (was 3, +11–22% from experiments). "
                    "Flag: --mtp-num-draft-tokens"
                ),
            },
            {
                "key": "mtp_optimistic",
                "label": "MTP Optimistic Drafting",
                "type": "bool",
                "default": True,
                "help": (
                    "Accept draft tokens optimistically (greedy) before full verification. "
                    "Improves throughput on MTPLX-optimized models. Flag: --mtp-optimistic"
                ),
            },
            {
                "key": "prefill_step_size",
                "label": "Prefill Step Size",
                "type": "int",
                "default": 8192,
                "min": 0,
                "max": 32768,
                "help": (
                    "Tokens per prefill chunk. 8192 recommended for large models. "
                    "0 = engine default. Flag: --prefill-step-size"
                ),
            },
            {
                "key": "disable_ngram",
                "label": "Disable N-gram Speculation",
                "type": "bool",
                "default": False,
                "help": (
                    "Disable n-gram prompt-lookup drafting (auto-enabled for qwen3.6-35b). "
                    "N-gram adds ~18% throughput on mixed reasoning + tool workloads. "
                    "Flag: --disable-ngram"
                ),
            },
            {
                "key": "no_thinking",
                "label": "Disable Thinking (<think> tags)",
                "type": "bool",
                "default": False,
                "help": (
                    "Disable reasoning/thinking output. Thinking stays on by default for "
                    "agentic tool use on Qwen3.6 models. Flag: --no-thinking"
                ),
            },
            {
                "key": "launch_model",
                "label": "Launch Model Override",
                "type": "str",
                "default": "",
                "help": (
                    "Optional lightning-mlx alias (e.g. qwen3.6-35b-8bit) or HF repo ID. "
                    "Overrides the canonical model ID at launch."
                ),
            },
        ]

    def default_engine_settings(self) -> dict[str, Any]:
        return {
            "mtp_num_draft_tokens": 5,
            "mtp_optimistic": True,
            "prefill_step_size": 8192,
            "disable_ngram": False,
            "no_thinking": False,
            "launch_model": "",
        }
