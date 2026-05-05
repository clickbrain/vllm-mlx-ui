# SPDX-License-Identifier: Apache-2.0
"""ManifestEngine — engine adapter driven by a JSON manifest file.

This is a **trusted, local-admin feature**.  Manifest files are loaded from
``~/.config/vllm-mlx-ui/engines/`` and allow power users to integrate any
CLI-based inference server without writing Python code.

Security model:
  - Manifests are JSON files that the *local user* places in a protected config
    directory (permissions enforced on load).
  - ``check_command`` and ``launch_template`` define arbitrary executables.
    This is equivalent to running any shell command as the current user — it is
    intentionally a trusted-user feature, not a remote-execution vector.
  - Interpreter-based commands (``sh -c``, ``bash -c``, ``python -c``, etc.)
    are rejected to prevent accidental injection vectors.

Manifest JSON schema::

    {
      "id": "my-engine",           // required, unique machine identifier
      "name": "My Engine",         // required, display name
      "version": "1.0.0",          // optional, static version string
      "capabilities": ["tool_calls"],  // optional, default []
      "install_method": "external",   // optional, default "external"
      "package_name": "",          // optional, PyPI package name if pip-based
      "check_command": ["my-engine", "--version"],  // required, probe for is_installed
      "version_regex": "([0-9]+\\.[0-9]+\\.[0-9]+)",  // optional, extract version from check_command output
      "launch_template": [         // required, command to launch the engine
        "my-engine", "serve", "{model}",
        "--host", "{host}", "--port", "{port}"
      ]
      // Template variables: {model} {host} {port} {api_key}
      // Additional engine_settings keys become template vars automatically.
    }
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from .base import BaseEngine

logger = logging.getLogger(__name__)

# Executables that would allow shell injection — always rejected.
_BLOCKED_INTERPRETERS = {"sh", "bash", "zsh", "fish", "cmd", "powershell", "python", "python3", "perl", "ruby", "node"}


def _safe_command(cmd: list[str]) -> bool:
    """Return True if the command list is safe (no interpreter injection)."""
    if not cmd:
        return False
    # Reject any command whose first token (basename) is a shell/interpreter.
    binary = os.path.basename(cmd[0]).lower()
    # Strip .exe suffix on Windows
    binary = binary.removesuffix(".exe")
    if binary in _BLOCKED_INTERPRETERS:
        return False
    # Reject -c / --command flags that execute arbitrary strings.
    return "-c" not in cmd and "--command" not in cmd


class ManifestEngine(BaseEngine):
    """Engine adapter loaded from a JSON manifest file.

    Instances are created by ``_load_manifest(path)`` — do not instantiate directly.
    """

    # ClassVar stubs — overridden per-instance via __dict__ (dataclass-like pattern)
    id: ClassVar[str] = "manifest-engine"
    name: ClassVar[str] = "Manifest Engine"
    capabilities: ClassVar[frozenset[str]] = frozenset()
    install_method: ClassVar[str] = "external"
    is_builtin: ClassVar[bool] = False

    def __init__(
        self,
        engine_id: str,
        display_name: str,
        capabilities: frozenset[str],
        install_method: str,
        check_command: list[str],
        launch_template: list[str],
        package_name_: str = "",
        version_regex: str = "",
        static_version: str = "",
        manifest_path: str = "",
    ) -> None:
        # Store instance-level attributes (override ClassVar stubs at instance level)
        object.__setattr__(self, "id", engine_id)
        object.__setattr__(self, "name", display_name)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "install_method", install_method)
        self._check_command = check_command
        self._launch_template = launch_template
        self._package_name = package_name_
        self._version_regex = re.compile(version_regex) if version_regex else None
        self._static_version = static_version
        self._manifest_path = manifest_path

    # Allow ClassVar-declared attributes to be shadowed at instance level.
    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)

    # ── BaseEngine implementation ─────────────────────────────────────────────

    def get_package_name(self) -> str:
        return self._package_name or self.id

    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Substitute template variables in launch_template and return the argv."""
        es = config.get("engine_settings", {}).get(self.id, {})
        variables: dict[str, str] = {
            "model": config.get("model", ""),
            "host": str(config.get("host", "127.0.0.1")),
            "port": str(config.get("port", 8000)),
            "api_key": config.get("api_key", ""),
            **{k: str(v) for k, v in es.items()},
        }
        cmd = []
        for token in self._launch_template:
            try:
                cmd.append(token.format(**variables))
            except KeyError as exc:
                logger.warning("Manifest %s: unknown template variable %s", self.id, exc)
                cmd.append(token)
        return cmd

    def is_installed(self) -> bool:
        """Run check_command and return True if it exits 0."""
        try:
            result = subprocess.run(
                self._check_command,
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_version(self) -> str | None:
        """Run check_command and extract version via regex, or return static version."""
        if self._static_version:
            return self._static_version
        try:
            result = subprocess.run(
                self._check_command,
                capture_output=True, text=True, timeout=5,
            )
            output = (result.stdout or result.stderr or "").strip()
            if self._version_regex:
                m = self._version_regex.search(output)
                if m:
                    return m.group(1) if m.lastindex else m.group(0)
            # Fallback: last whitespace-delimited token
            parts = output.split()
            return parts[-1] if parts else None
        except Exception:
            return None

    def config_schema(self) -> list[dict[str, Any]]:
        return []

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: Path) -> "ManifestEngine | None":
        """Load and validate a manifest JSON file, returning None on error."""
        try:
            # Only accept files owned by the current user (or root).
            stat = path.stat()
            if hasattr(stat, "st_uid") and stat.st_uid not in (0, os.getuid()):
                logger.warning("Manifest %s owned by uid %d (not current user) — skipping", path, stat.st_uid)
                return None

            with path.open() as fh:
                data = json.load(fh)

            engine_id = data.get("id", "").strip()
            display_name = data.get("name", "").strip()
            if not engine_id or not display_name:
                logger.warning("Manifest %s missing required 'id' or 'name' field", path)
                return None

            check_command = data.get("check_command", [])
            launch_template = data.get("launch_template", [])
            if not isinstance(check_command, list) or not isinstance(launch_template, list):
                logger.warning("Manifest %s: check_command and launch_template must be lists", path)
                return None

            if not _safe_command(check_command):
                logger.warning("Manifest %s: check_command uses a blocked interpreter — skipping", path)
                return None
            if not _safe_command(launch_template):
                logger.warning("Manifest %s: launch_template uses a blocked interpreter — skipping", path)
                return None

            # Resolve the binary name to an absolute path (shutil.which) so the
            # manifest works even if PATH differs between environments.
            for cmd_list in (check_command, launch_template):
                binary = shutil.which(cmd_list[0]) if cmd_list else None
                if binary:
                    cmd_list[0] = binary

            capabilities = frozenset(str(c) for c in data.get("capabilities", []))
            install_method = data.get("install_method", "external")
            if install_method not in ("pip", "external", "bundled"):
                install_method = "external"

            return cls(
                engine_id=engine_id,
                display_name=display_name,
                capabilities=capabilities,
                install_method=install_method,
                check_command=check_command,
                launch_template=launch_template,
                package_name_=data.get("package_name", ""),
                version_regex=data.get("version_regex", ""),
                static_version=data.get("version", ""),
                manifest_path=str(path),
            )
        except Exception as exc:
            logger.warning("Failed to load engine manifest %s: %s", path, exc, exc_info=True)
            return None


def discover_manifests() -> list[ManifestEngine]:
    """Scan ``~/.config/vllm-mlx-ui/engines/`` for JSON manifests.

    Returns a list of successfully loaded ManifestEngine instances in filename order.
    """
    engines: list[ManifestEngine] = []
    config_dir = Path.home() / ".config" / "vllm-mlx-ui" / "engines"
    if not config_dir.is_dir():
        return engines
    for manifest_file in sorted(config_dir.glob("*.json")):
        engine = ManifestEngine.from_file(manifest_file)
        if engine is not None:
            engines.append(engine)
            logger.info("Loaded engine manifest: %s (%s)", engine.id, manifest_file.name)
    return engines
