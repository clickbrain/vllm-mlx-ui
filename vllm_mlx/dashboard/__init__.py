# SPDX-License-Identifier: Apache-2.0
"""vllm-mlx Dashboard — browser-based UI for managing the inference server."""

# Dashboard UI version — reads from the installed vllm-mlx-ui package metadata,
# which is set by pyproject.toml at build time.
# NOTE: do NOT read from "vllm-mlx" here — that is the upstream engine package
# (waybarrios/vllm-mlx) and has its own independent version number.
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("vllm-mlx-ui")
except Exception:
    __version__ = "0.3.0"  # fallback for editable / dev installs
