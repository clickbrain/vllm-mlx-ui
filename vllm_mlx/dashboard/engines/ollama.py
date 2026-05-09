# SPDX-License-Identifier: Apache-2.0
"""OllamaEngine — adapter for the Ollama inference runtime.

Ollama (ollama.com) manages its own model library using short tag names such
as ``llama3.2``, ``mistral``, ``qwen2.5:14b``.  It exposes an OpenAI-compatible
API at ``/v1`` (Ollama ≥ 0.3) as well as its native ``/api`` routes.

Install:  https://ollama.com/download  (brew install ollama, curl installer, etc.)
Launch:   ``ollama serve`` — Ollama binds to ``OLLAMA_HOST`` (default 127.0.0.1:11434).

Model naming:
  Ollama uses its own short-name registry (e.g. ``llama3.2:latest``), NOT HF repo IDs.
  Set ``config["model"]`` to the Ollama tag and also set
  ``config["engine_settings"]["ollama"]["launch_model"]`` to the same value.
  The dashboard always stores ``config["model"]`` as the tag when Ollama is the engine.

Port handling:
  We set ``OLLAMA_HOST=127.0.0.1:<port>`` via ``build_env()`` so Ollama binds to the
  dashboard-configured port instead of its default 11434.  This keeps the
  single-port contract intact across all engines.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any, ClassVar

from .base import BaseEngine


class OllamaEngine(BaseEngine):
    """Adapter for the Ollama inference runtime."""

    id: ClassVar[str] = "ollama"
    name: ClassVar[str] = "Ollama"
    description: ClassVar[str] = (
        "Ollama runs quantised models locally with a simple pull-and-run workflow. "
        "Uses Ollama's own short model tags (e.g. llama3.2, mistral, qwen2.5:14b). "
        "Install Ollama from ollama.com then pull a model with `ollama pull <tag>`."
    )
    capabilities: ClassVar[frozenset[str]] = frozenset({
        "tool_calls",
        "vision",
        "continuous_batching",
        "embedding",
        "prefix_cache",
    })
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = True
    release_url: ClassVar[str] = "https://ollama.com/download"

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Return the ``ollama serve`` command.

        The port is not passed as a flag — Ollama reads it from the
        ``OLLAMA_HOST`` environment variable, which ``build_env()`` sets.
        """
        ollama_bin = self._which("ollama") or "ollama"
        return [ollama_bin, "serve"]

    def _which(self, cmd: str) -> str | None:
        found = super()._which(cmd)
        if found is not None:
            return found
        if cmd == "ollama":
            for p in [
                "/usr/local/bin/ollama",
                os.path.expanduser("~/.local/bin/ollama"),
            ]:
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
        return None

    def is_installed(self) -> bool:
        return self._which("ollama") is not None

    def get_version(self) -> str | None:
        ollama_bin = self._which("ollama") or "ollama"
        try:
            result = subprocess.run(
                [ollama_bin, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            # "ollama version 0.3.6" or "ollama version is 0.7.0"
            m = re.search(r"version(?:\s+is)?\s+(\S+)", result.stdout + result.stderr)
            return m.group(1) if m else None
        except Exception:
            return None

    def latest_version(self) -> str | None:
        try:
            import json as _json
            import urllib.request
            with urllib.request.urlopen(
                "https://api.github.com/repos/ollama/ollama/releases/latest",
                timeout=5,
            ) as resp:
                tag = _json.loads(resp.read()).get("tag_name", "")
                return tag.lstrip("v") or None
        except Exception:
            return None

    def upgrade_command(self) -> list[str] | None:
        """Return a Python command to download and install the latest Ollama release.

        Queries the GitHub releases API to find the macOS asset by prefix
        (``ollama-darwin``), so renames between ``.zip``, ``.tgz``, etc.
        never break the upgrade.  Falls back to ``brew upgrade ollama`` if
        the API call or download fails.

        Base64-encodes the script so it's a single shell-safe argument
        (multi-line scripts break inside ``sh -c`` strings).
        """
        import base64 as _base64
        version = self.latest_version()
        if not version:
            return None
        script = f"""
import json, os, shutil, stat, subprocess, tarfile, tempfile, urllib.request, zipfile

# Query GitHub releases API for the macOS CLI asset
api_url = "https://api.github.com/repos/ollama/ollama/releases/tags/v{version}"
dl_url = None
try:
    with urllib.request.urlopen(api_url, timeout=10) as r:
        data = json.loads(r.read().decode())
    for asset in data.get("assets", []):
        name = asset["name"]
        # Match "ollama-darwin" (CLI) but NOT "Ollama-darwin" (desktop app)
        if name.startswith("ollama-darwin") and not name.startswith("Ollama"):
            dl_url = asset["browser_download_url"]
            break
except Exception:
    pass

if not dl_url:
    # Fallback: try brew
    if shutil.which("brew"):
        r = subprocess.run(["brew", "list", "ollama"], capture_output=True, timeout=10)
        if r.returncode == 0:
            subprocess.run(["brew", "upgrade", "ollama"], timeout=120)
            raise SystemExit(0)
    raise SystemExit(1)

# Download
tmp_file = tempfile.mktemp(suffix=os.path.splitext(dl_url)[1] or ".tmp")
try:
    urllib.request.urlretrieve(dl_url, tmp_file)
except Exception:
    try:
        os.unlink(tmp_file)
    except OSError:
        pass
    # Final fallback: try brew
    if shutil.which("brew"):
        r = subprocess.run(["brew", "list", "ollama"], capture_output=True, timeout=10)
        if r.returncode == 0:
            subprocess.run(["brew", "upgrade", "ollama"], timeout=120)
            raise SystemExit(0)
    raise SystemExit(1)

# Extract to temp dir
tmp_dir = tempfile.mktemp(suffix=".ollama")
try:
    if dl_url.endswith(".zip"):
        with zipfile.ZipFile(tmp_file, "r") as zf:
            zf.extractall(tmp_dir)
    else:
        with tarfile.open(tmp_file, "r:*") as tf:
            tf.extractall(tmp_dir)
finally:
    os.unlink(tmp_file)

# Find the ollama binary
binary = os.path.join(tmp_dir, "ollama")
if not os.path.isfile(binary):
    shutil.rmtree(tmp_dir, ignore_errors=True)
    raise SystemExit(1)

target = shutil.which("ollama") or (
    "/usr/local/bin/ollama"
    if os.path.isfile("/usr/local/bin/ollama")
    else os.path.expanduser("~/.local/bin/ollama")
)
target_dir = os.path.dirname(target)

# If target dir is not writable, fall back to user-local bin
if not os.access(target_dir, os.W_OK):
    target = os.path.expanduser("~/.local/bin/ollama")
    os.makedirs(os.path.dirname(target), exist_ok=True)

try:
    shutil.copy2(binary, target)
    os.chmod(target, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
except PermissionError:
    raise SystemExit(1)

# Ensure ~/.local/bin is in PATH when falling back to it
if target.startswith(os.path.expanduser("~/.local/bin/ollama")):
    _bin = os.path.dirname(target)
    if _bin not in os.environ.get("PATH", "").split(":"):
        _shell = os.environ.get("SHELL", "")
        _home = os.path.expanduser("~")
        _rc_files = []
        if "zsh" in _shell:
            _rc_files = [os.path.join(_home, ".zshenv"), os.path.join(_home, ".zshrc")]
        elif "bash" in _shell:
            _rc_files = [os.path.join(_home, ".bash_profile"), os.path.join(_home, ".bashrc")]
        elif "fish" in _shell:
            _rc_files = [os.path.join(_home, ".config", "fish", "config.fish")]
        for _rc in _rc_files:
            if os.path.isfile(_rc):
                with open(_rc) as _f:
                    _existing = _f.read()
                if "$HOME/.local/bin" not in _existing and "~/.local/bin" not in _existing:
                    with open(_rc, "a") as _f:
                        _f.write("\\n# Added by vllm-mlx-ui upgrade")
                        _f.write('\\nif [ -d "$HOME/.local/bin" ]; then')
                        _f.write('\\n    export PATH="$HOME/.local/bin:$PATH"')
                        _f.write("\\nfi\\n")
                    print(f'Added $HOME/.local/bin to PATH in {{_rc}} — restart shell or run: export PATH="$HOME/.local/bin:$PATH"')
                else:
                    print(f'Ollama installed to {{target}} but $HOME/.local/bin is not in PATH. Restart your shell or run: export PATH="$HOME/.local/bin:$PATH"')
                break
        else:
            print(f"Ollama installed to {{target}} but no shell rc file found. Add ~/.local/bin to your PATH manually.")
    else:
        print(f"Ollama upgraded to {{target}}")
else:
    print(f"Ollama upgraded to {{target}}")

shutil.rmtree(tmp_dir, ignore_errors=True)
"""
        encoded = _base64.b64encode(script.encode()).decode()
        return [
            sys.executable, "-c",
            f"import base64; exec(base64.b64decode({encoded!r}).decode())",
        ]

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the Ollama model tag to pass to the API.

        For Ollama, the launch model IS the model used in API requests.
        Falls back to ``config["model"]`` which should already be an Ollama tag.
        """
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        return engine_settings.get("launch_model") or config.get("model", "")

    def config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "launch_model",
                "label": "Ollama Model Tag",
                "type": "str",
                "default": "",
                "help": (
                    "The Ollama model tag to serve (e.g. llama3.2, mistral, qwen2.5:14b). "
                    "Run `ollama pull <tag>` first. Leave blank to use the main model field."
                ),
            },
            {
                "key": "num_ctx",
                "label": "Context Window (num_ctx)",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 131072,
                "help": (
                    "Sets OLLAMA_CONTEXT_LENGTH. 0 = use Ollama's default for the model. "
                    "Override if you need a larger or smaller context window."
                ),
            },
            {
                "key": "num_parallel",
                "label": "Parallel Requests (num_parallel)",
                "type": "int",
                "default": 0,
                "min": 0,
                "max": 16,
                "help": "Sets OLLAMA_NUM_PARALLEL. 0 = Ollama default (auto).",
            },
            {
                "key": "max_loaded_models",
                "label": "Max Loaded Models",
                "type": "int",
                "default": 1,
                "min": 1,
                "max": 8,
                "help": "Sets OLLAMA_MAX_LOADED_MODELS. How many models to keep loaded simultaneously.",
            },
            {
                "key": "flash_attention",
                "label": "Flash Attention",
                "type": "bool",
                "default": False,
                "help": "Sets OLLAMA_FLASH_ATTENTION=1 for supported models.",
            },
        ]

    def build_env(self, config: dict[str, Any]) -> dict[str, str]:  # type: ignore[override]
        """Return Ollama environment variables derived from dashboard config."""
        host = config.get("host", "127.0.0.1")
        port = int(config.get("port", 11434))
        engine_settings = config.get("engine_settings", {}).get(self.id, {})

        env: dict[str, str] = {"OLLAMA_HOST": f"{host}:{port}"}

        num_ctx = int(engine_settings.get("num_ctx", 0))
        if num_ctx > 0:
            env["OLLAMA_CONTEXT_LENGTH"] = str(num_ctx)

        num_parallel = int(engine_settings.get("num_parallel", 0))
        if num_parallel > 0:
            env["OLLAMA_NUM_PARALLEL"] = str(num_parallel)

        max_loaded = int(engine_settings.get("max_loaded_models", 1))
        if max_loaded != 1:
            env["OLLAMA_MAX_LOADED_MODELS"] = str(max_loaded)

        if engine_settings.get("flash_attention"):
            env["OLLAMA_FLASH_ATTENTION"] = "1"

        return env

    def validate_model_id(self, model_id: str) -> bool:
        # Ollama tags: "name" or "name:tag" — simple alphanumeric + slashes for namespaced models
        return bool(re.match(r"^[\w./-]+(?::[\w.-]+)?$", model_id.strip()))
