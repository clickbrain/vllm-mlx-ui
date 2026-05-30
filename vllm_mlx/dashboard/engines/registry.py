# SPDX-License-Identifier: Apache-2.0
"""Engine registry — maps engine IDs to their adapter instances.

Built-in adapters are always registered first (rapid-mlx is the primary local engine).
On startup (and on ``reload()``) the registry also discovers:

1. **Python entry points** — any installed pip package that declares::

       [project.entry-points."vllm_mlx_ui.engines"]
       my-engine = "my_pkg.engine:MyEngine"

   The class must be a concrete subclass of ``BaseEngine``.

2. **JSON manifest files** — ``~/.config/vllm-mlx-ui/engines/*.json``
   (see ``engines/manifest.py`` for the schema).

Thread safety:
  The registry dict is protected by a ``threading.RLock``.  ``reload()`` builds
  a new dict off-lock then swaps it atomically under the lock, so readers (API
  handlers) never see a partially-built state.
"""
from __future__ import annotations

import contextlib
import logging
import time as _time
import threading
from typing import TYPE_CHECKING

from .apple_fm import AppleFMEngine
from .diffusion_mlx import DiffusionMlxEngine
from .ds4_m5 import Ds4M5Engine, is_m5_or_newer
from .external_api import ExternalApiEngine
from .lightning_mlx import LightningMlxEngine
from .llama_cpp import LlamaCppEngine
from .lmstudio import LmStudioEngine
from .ollama import OllamaEngine
from .rapid_mlx import RapidMlxEngine
from .vllm_mlx import VllmMlxEngine  # kept for config migration only (hidden=True)

if TYPE_CHECKING:
    from .base import BaseEngine

logger = logging.getLogger(__name__)

# ── Built-in engines (always present) ─────────────────────────────────────────
# Order matters: rapid-mlx is the primary local engine.  Hidden engines
# (VllmMlxEngine) are included in ENGINES for config migration but are
# excluded from the /engines API and UI engine picker via list_engines().
_BUILTINS: list[BaseEngine] = [
    RapidMlxEngine(),    # primary local engine — fast MLX inference for Apple Silicon
    LightningMlxEngine(), # MTPLX speculative decoding — best for MTPLX-packaged models
    OllamaEngine(),      # popular desktop app, reliable
    LmStudioEngine(),    # desktop GUI app
    LlamaCppEngine(),    # llama.cpp CLI
    Ds4M5Engine(),       # M5-optimised DeepSeek V4 Flash (best on M5+)
    DiffusionMlxEngine(), # Dream-architecture diffusion models (e.g. DiffuCoder)
    ExternalApiEngine(), # remote API proxy — requires user config, never auto-fallback
    AppleFMEngine(),     # macOS 26+ only — put last to avoid premature fallback
    VllmMlxEngine(),     # DEPRECATED — hidden, kept for config migration only
]

# ── Global registry state ─────────────────────────────────────────────────────
_registry_lock = threading.RLock()

# Ordered dict: engine_id → engine instance.  Readers must acquire _registry_lock.
ENGINES: dict[str, BaseEngine] = {e.id: e for e in _BUILTINS}


# ── Discovery helpers ─────────────────────────────────────────────────────────

def _discover_entry_points() -> list[BaseEngine]:
    """Load engines registered via importlib.metadata entry_points."""
    discovered: list[BaseEngine] = []
    try:
        from importlib.metadata import entry_points

        from .base import BaseEngine as _BaseEngine
        eps = entry_points(group="vllm_mlx_ui.engines")
        for ep in eps:
            try:
                cls = ep.load()
                if not (isinstance(cls, type) and issubclass(cls, _BaseEngine)):
                    logger.warning("Entry point %s is not a BaseEngine subclass — skipping", ep.name)
                    continue
                instance = cls()
                discovered.append(instance)
                logger.info("Discovered engine via entry_point: %s", instance.id)
            except Exception as exc:
                logger.warning("Failed to load entry point %s: %s", ep.name, exc, exc_info=True)
    except Exception as exc:
        logger.warning("Entry point discovery failed: %s", exc, exc_info=True)
    return discovered


def _discover_manifests() -> list[BaseEngine]:
    """Load engines from JSON manifests in ~/.config/vllm-mlx-ui/engines/."""
    try:
        from .manifest import discover_manifests
        return discover_manifests()
    except Exception as exc:
        logger.warning("Manifest discovery failed: %s", exc, exc_info=True)
        return []


def _build_registry() -> dict[str, BaseEngine]:
    """Build a fresh registry snapshot: builtins first, then discovered engines.

    Built-in IDs always win over discovered engines with the same ID.
    """
    registry: dict[str, BaseEngine] = {}

    # 1. Built-ins (highest priority)
    for engine in _BUILTINS:
        registry[engine.id] = engine

    # 2. Entry-point plugins
    for engine in _discover_entry_points():
        if engine.id in registry:
            logger.warning(
                "Discovered engine %r conflicts with existing ID — skipping (builtin wins)",
                engine.id,
            )
        else:
            registry[engine.id] = engine

    # 3. JSON manifest files
    for engine in _discover_manifests():
        if engine.id in registry:
            logger.warning(
                "Manifest engine %r conflicts with existing ID — skipping (first registration wins)",
                engine.id,
            )
        else:
            registry[engine.id] = engine

    return registry


# ── Public API ─────────────────────────────────────────────────────────────────

def reload() -> None:
    """Re-scan entry points and manifests, then atomically swap the registry.

    Safe to call from any thread.  Readers that hold a reference to the old
    ENGINES dict will finish uninterrupted; new reads see the updated registry.
    """
    global ENGINES
    new_registry = _build_registry()
    with _registry_lock:
        ENGINES = new_registry
    logger.info("Engine registry reloaded — %d engine(s) registered", len(new_registry))


def get_engine(engine_id: str) -> BaseEngine:
    """Return the engine adapter for *engine_id*.

    Raises:
        KeyError: if *engine_id* is not registered.
    """
    with _registry_lock:
        engines_snapshot = dict(ENGINES)
    try:
        return engines_snapshot[engine_id]
    except KeyError:
        known = ", ".join(engines_snapshot)
        raise KeyError(
            f"Unknown engine {engine_id!r}. Known engines: {known}"
        ) from None


# ── latest_version() TTL cache ────────────────────────────────────────────────
# latest_version() makes network calls (PyPI, GitHub API). Caching for 5 minutes
# prevents multiple slow network calls per /engines request.
_latest_version_cache: dict[str, tuple[float, str | None]] = {}
_latest_version_cache_lock = threading.Lock()
_LATEST_VERSION_TTL = 300.0  # 5 minutes


def _cached_latest_version(engine: "BaseEngine") -> str | None:
    now = _time.monotonic()
    eid = engine.id
    with _latest_version_cache_lock:
        if eid in _latest_version_cache:
            ts, version = _latest_version_cache[eid]
            if now - ts < _LATEST_VERSION_TTL:
                return version
    # Fetch outside the lock so other threads aren't blocked by network I/O.
    version = None
    with contextlib.suppress(Exception):
        version = engine.latest_version()
    with _latest_version_cache_lock:
        _latest_version_cache[eid] = (now, version)
    return version


def list_engines() -> list[dict]:
    """Return summary dicts for all registered engines (for the /engines endpoint).

    Hidden engines (e.g. deprecated vllm-mlx kept for config migration) are
    excluded from this list.
    """
    with _registry_lock:
        engines_snapshot = list(ENGINES.values())

    result = []
    for engine in engines_snapshot:
        if getattr(engine, "hidden", False):
            continue
        installed = False
        version = None
        try:
            installed = engine.is_installed()
            if installed:
                version = engine.get_version()
        except Exception as e:
            logger.warning("Engine probe failed for %s: %s", engine.id, e)
        # Get latest version — use cached value to avoid blocking network calls
        # on every /engines request (PyPI + GitHub lookups can be slow).
        latest = _cached_latest_version(engine)
        req_errors: list[str] = []
        try:
            req_errors = engine.check_requirements()
        except Exception as e:
            logger.warning("check_requirements failed for %s: %s", engine.id, e)
        req_warnings: list[str] = []
        try:
            req_warnings = engine.check_warnings()
        except Exception as e:
            logger.warning("check_warnings failed for %s: %s", engine.id, e)
        result.append({
            "id": engine.id,
            "name": engine.name,
            "description": getattr(engine, "description", ""),
            "capabilities": sorted(engine.capabilities),
            "install_method": engine.install_method,
            "is_builtin": getattr(engine, "is_builtin", True),
            "health_path": getattr(engine, "health_path", "/health"),
            "installed": installed,
            "version": version,
            "release_url": getattr(engine, "release_url", ""),
            "latest_version": latest,
            "fixed_model_display": engine.get_fixed_model_display() if installed else None,
            "requirements_errors": req_errors,
            "requirements_warnings": req_warnings,
        })
    # Sort: installed first, then not-installed.
    # DeepSeek V4 Flash (ds4-m5) sinks to the bottom on non-M5 hardware
    # so users on M1-M4 see it last (it's designed for M5+).
    _m5_hw = is_m5_or_newer()
    result.sort(key=lambda e: (
        2 if e["id"] == "ds4-m5" and not _m5_hw else 0 if e["installed"] else 1,
        e["id"],
    ))
    return result


# ── Initialise on import ───────────────────────────────────────────────────────
# Perform initial discovery at import time so the registry is fully populated
# before any API handler runs.  This is safe because the module is imported
# once, and the lock protects any concurrent reload() calls.
def _initial_load() -> None:
    global ENGINES
    try:
        new_registry = _build_registry()
        with _registry_lock:
            ENGINES = new_registry
    except Exception as exc:
        logger.warning("Initial engine registry load failed: %s", exc, exc_info=True)


_initial_load()

