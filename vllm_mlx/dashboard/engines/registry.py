# SPDX-License-Identifier: Apache-2.0
"""Engine registry — maps engine IDs to their adapter instances.

All engine adapters must be registered here.  The registry is the single point
of truth used by the management server, config migration, and the UI endpoints.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .vllm_mlx import VllmMlxEngine
from .rapid_mlx import RapidMlxEngine

if TYPE_CHECKING:
    from .base import BaseEngine

logger = logging.getLogger(__name__)

# Ordered dict of id → instance.  Order determines the default sort in the UI.
ENGINES: dict[str, "BaseEngine"] = {
    engine.id: engine
    for engine in [
        VllmMlxEngine(),
        RapidMlxEngine(),
    ]
}


def get_engine(engine_id: str) -> "BaseEngine":
    """Return the engine adapter for *engine_id*.

    Raises:
        KeyError: if *engine_id* is not registered.
    """
    try:
        return ENGINES[engine_id]
    except KeyError:
        known = ", ".join(ENGINES)
        raise KeyError(
            f"Unknown engine {engine_id!r}. Known engines: {known}"
        ) from None


def list_engines() -> list[dict]:
    """Return summary dicts for all registered engines (for the /engines endpoint)."""
    result = []
    for engine in ENGINES.values():
        installed = False
        version = None
        try:
            installed = engine.is_installed()
            if installed:
                version = engine.get_version()
        except Exception as e:
            logger.warning("Engine probe failed for %s: %s", engine.id, e)
        result.append({
            "id": engine.id,
            "name": engine.name,
            "capabilities": sorted(engine.capabilities),
            "install_method": engine.install_method,
            "installed": installed,
            "version": version,
        })
    return result
