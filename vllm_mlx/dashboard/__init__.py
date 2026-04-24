# SPDX-License-Identifier: Apache-2.0
"""vllm-mlx Dashboard — browser-based UI for managing the inference server."""

# Dashboard UI version — reads from installed vllm-mlx-ui package metadata.
# This matches the package name in pyproject.toml exactly.
# Fallback to hardcoded string for editable/dev installs.
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("vllm-mlx-ui")
except Exception:
    __version__ = "0.3.30"
