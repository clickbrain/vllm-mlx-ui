# SPDX-License-Identifier: Apache-2.0
"""Engine abstraction layer for vllm-mlx-ui.

Provides a uniform interface for managing multiple inference engine backends
(vllm-mlx, rapid-mlx, etc.) without coupling the dashboard to any one engine.
"""
from .base import BaseEngine
from .registry import get_engine, list_engines, ENGINES

__all__ = ["BaseEngine", "get_engine", "list_engines", "ENGINES"]
