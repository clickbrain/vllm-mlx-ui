# SPDX-License-Identifier: Apache-2.0
"""vllm-mlx Dashboard — browser-based UI for managing the inference server."""

# Version is kept in sync with the package version in pyproject.toml.
# Both the engine (vllm_mlx) and the dashboard read from the same source.
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("vllm-mlx")
except Exception:
    __version__ = "0.3.0"  # fallback for editable / dev installs
