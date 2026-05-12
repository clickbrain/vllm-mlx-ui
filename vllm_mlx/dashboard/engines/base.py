# SPDX-License-Identifier: Apache-2.0
"""BaseEngine — abstract contract for all inference engine adapters."""
from __future__ import annotations

import shutil
import sys
from abc import ABC, abstractmethod
from typing import Any, ClassVar


class BaseEngine(ABC):
    """Abstract base for inference engine adapters.

    Each concrete engine encapsulates:
    - how to build the launch command from dashboard config
    - how to detect installation and read version
    - which capabilities are supported (drives UI feature gating)
    - engine-specific config schema (drives dynamic settings panel)
    - how to validate and resolve model identifiers for this engine

    Design contract:
    - ``config["model"]`` is always the canonical HF repo ID (e.g. "mlx-community/Qwen3-8B-4bit").
    - ``config["engine_settings"][engine_id]`` holds engine-specific overrides, including
      ``launch_model`` if the engine uses an alias that differs from the HF repo ID.
    - Engines must NEVER modify the config dict passed to ``build_command()``.
    """

    #: Stable machine identifier, used as the key in the engine registry.
    id: ClassVar[str]

    #: Human-readable display name.
    name: ClassVar[str]

    #: Set of capability strings this engine supports.  Used to gate UI features.
    #: Well-known capabilities: "tool_calls", "vision", "audio", "continuous_batching",
    #: "prefix_cache", "kv_quantization", "paged_cache", "reasoning", "metrics",
    #: "embedding", "rerank", "mtp", "ssd_cache".
    capabilities: ClassVar[frozenset[str]]

    #: How the engine is installed.  Drives the Install button visibility.
    #: One of: "pip" (installable via pip), "bundled" (always present, cannot install),
    #: "external" (external binary, not pip-managed).
    install_method: ClassVar[str] = "pip"

    #: Human-readable description shown in the Settings engine card.
    description: ClassVar[str] = ""

    #: True for engines shipped with the dashboard package (vllm-mlx, rapid-mlx).
    #: False for engines discovered via entry_points or user manifest files.
    is_builtin: ClassVar[bool] = True

    #: Path to use for the readiness health probe.
    #: Override to ``"/v1/models"`` for engines that don't expose ``/health``.
    health_path: ClassVar[str] = "/health"

    #: URL shown in the update notification for this engine (download/release page).
    release_url: ClassVar[str] = ""

    # ── Core abstract methods ──────────────────────────────────────────────────

    @abstractmethod
    def build_command(self, config: dict[str, Any]) -> list[str]:
        """Return the complete argv list to launch this engine.

        Args:
            config: Full merged dashboard config dict.  Read-only.

        Returns:
            List of strings suitable for ``subprocess.Popen(cmd, ...)``.
        """

    @abstractmethod
    def is_installed(self) -> bool:
        """Return True if this engine is available in the current environment."""

    @abstractmethod
    def get_version(self) -> str | None:
        """Return the installed version string, or None if not installed / indeterminate."""

    # ── Optional overrides ─────────────────────────────────────────────────────

    def config_schema(self) -> list[dict[str, Any]]:
        """Return the engine-specific settings fields for the dynamic settings panel.

        Each entry is a field descriptor dict with keys:
            key (str): config key under engine_settings[engine_id]
            label (str): display label
            type (str): "bool" | "int" | "float" | "str" | "select"
            default: default value
            options (list, type=="select"): available options
            min/max (number, type=="int"/"float"): range constraints
            help (str): tooltip/description

        Returns an empty list by default (engine has no extra settings).
        """
        return []

    def build_env(self, config: dict[str, Any]) -> dict[str, str] | None:  # noqa: ARG002
        """Return extra environment variables to add when launching this engine.

        Returns:
            None to inherit the parent process environment unchanged.
            A ``{name: value}`` dict to merge on top of ``os.environ`` before
            spawning the engine subprocess.  All values must be strings.

        Default implementation returns None (no overrides).
        Override in subclasses that need env-based configuration (e.g. Ollama).
        """
        return None

    def validate_model_id(self, model_id: str) -> bool:  # noqa: ARG002
        """Return True if *model_id* is a valid identifier for this engine.

        Default implementation always returns True.  Override for engines that
        only accept specific formats (e.g. short aliases).
        """
        return True

    def resolve_launch_model(self, config: dict[str, Any]) -> str:
        """Return the model token to pass on the command line.

        By default returns ``config["model"]`` (the canonical HF repo ID).
        Override if the engine uses a different alias scheme.  The dashboard
        always stores the canonical ID; this method bridges the gap at launch.
        """
        engine_settings = config.get("engine_settings", {}).get(self.id, {})
        return engine_settings.get("launch_model") or config.get("model", "")

    def default_engine_settings(self) -> dict[str, Any]:
        """Return the default values for this engine's engine_settings namespace.

        Used during config migration to populate missing keys.
        """
        return {field["key"]: field["default"] for field in self.config_schema()}

    def latest_version(self) -> str | None:
        """Return the latest available version from PyPI, or None if unavailable.

        Only meaningful for pip-installed engines.  Default tries PyPI using
        get_package_name() which defaults to the engine id.

        Filters out versions that have no compatible wheel for the current
        platform (Python version + OS + architecture), mirroring the
        same logic used in ``update_checker._pypi_latest()``.
        """
        if self.install_method != "pip":
            return None
        try:
            import json as _json
            import platform as _platform
            import sys as _sys
            import urllib.request as _urllib
            pkg = self.get_package_name()
            with _urllib.urlopen(
                f"https://pypi.org/pypi/{pkg}/json", timeout=5
            ) as resp:
                data = _json.loads(resp.read())

            py_major_minor = f"{_sys.version_info.major}{_sys.version_info.minor}"
            machine = _platform.machine().lower()
            system = _platform.system().lower()
            py_tag_prefix = f"cp{py_major_minor}"
            arch_tags: set[str] = set()
            if system == "darwin":
                arch_tags.add("macosx")
                if machine in ("arm64", "aarch64"):
                    arch_tags.add("arm64")
                elif machine in ("x86_64", "amd64"):
                    arch_tags.add("x86_64")
            elif system == "linux":
                arch_tags.add("linux")
                if machine in ("arm64", "aarch64"):
                    arch_tags.add("aarch64")
                elif machine in ("x86_64", "amd64"):
                    arch_tags.add("x86_64")

            def _wheel_compatible(url_info: dict) -> bool:
                fname = url_info.get("filename", "")
                if not fname.endswith(".whl"):
                    return False
                parts = fname[:-len(".whl")].split("-")
                if len(parts) < 5:
                    return False
                py_tag = parts[-3].lower()
                abi_tag = parts[-2].lower()
                platform_tag = parts[-1].lower()
                if platform_tag == "any" and abi_tag == "none":
                    pass
                else:
                    if system == "darwin" and "macosx" not in platform_tag:
                        return False
                    if system == "linux" and "linux" not in platform_tag and "manylinux" not in platform_tag:
                        return False
                    if arch_tags and not any(a in platform_tag for a in arch_tags):
                        return False
                if "abi3" in abi_tag:
                    if not py_tag.startswith("cp") or int(py_tag[2:4]) < 38:
                        return False
                else:
                    if py_tag == "py3":
                        pass
                    elif not py_tag.startswith(py_tag_prefix):
                        return False
                return True

            for url_info in data.get("urls", []):
                if url_info.get("packagetype") != "bdist_wheel":
                    continue
                if not _wheel_compatible(url_info):
                    continue
                return data.get("info", {}).get("version")
            return None
        except Exception:
            return None

    def get_package_name(self) -> str:
        """Return the PyPI package name for this engine.

        Defaults to engine.id. Override in subclasses when the PyPI name
        differs from the engine id (e.g. "my-engine" vs "my_engine").
        """
        return self.id

    def install_command(self) -> list[str]:
        """Return the argv list to install this engine.

        Uses sys.executable to guarantee the same Python environment as the
        management server — never a globally resolved pip or python.
        """
        return [sys.executable, "-m", "pip", "install", "--upgrade", self.get_package_name()]

    def uninstall_command(self) -> list[str]:
        """Return the argv list to uninstall this engine, or raise NotImplementedError.

        Default runs ``pip uninstall -y`` for pip-installed engines.
        Override in subclasses that need different removal logic
        (e.g. ``rm -rf`` for git-cloned engines, ``brew uninstall``).
        Raises ``NotImplementedError`` for bundled engines.
        """
        if self.install_method == "bundled":
            raise NotImplementedError(f"Engine {self.id!r} is bundled and cannot be uninstalled.")
        if self.install_method == "pip":
            return [sys.executable, "-m", "pip", "uninstall", "-y", self.get_package_name()]
        raise NotImplementedError(
            f"Engine {self.id!r} has no automated uninstaller — remove manually."
        )

    def upgrade_command(self) -> list[str] | None:
        """Return a shell command to upgrade this engine, or None if not supported.

        Override in subclasses that support automated upgrades via system
        package managers (e.g. Homebrew).  Only called for installed engines.
        """
        return None

    def _which(self, cmd: str) -> str | None:
        """Locate *cmd* on PATH; returns None if not found."""
        return shutil.which(cmd)

    def __repr__(self) -> str:
        installed = "(installed)" if self.is_installed() else "(not installed)"
        return f"<{self.__class__.__name__} id={self.id!r} {installed}>"
