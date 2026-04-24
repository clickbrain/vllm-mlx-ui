# SPDX-License-Identifier: Apache-2.0
"""vllm-mlx Dashboard — browser-based UI for managing the inference server."""

# Dashboard UI version — hardcoded string, updated with every release.
# importlib.metadata is NOT used here because both this package and the upstream
# engine (waybarrios/vllm-mlx) share the package name "vllm-mlx", so metadata
# lookup returns whichever was installed last and is unreliable.
# When bumping a release: update pyproject.toml version AND this string together.
__version__ = "0.3.27"
