# SPDX-License-Identifier: Apache-2.0
"""
Update checker for vllm-mlx-ui and its key dependencies.

Checks for newer versions of:
- vllm-mlx-ui (this project)  — compares installed commit hash vs latest commit on main
- vllm-mlx (upstream engine)  — compares installed version vs latest GitHub tag
- mlx-lm                      — compares installed version vs PyPI
- huggingface-hub             — compares installed version vs PyPI

Results are cached in session state for 1 hour to avoid hammering GitHub/PyPI.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import NamedTuple

import requests

_CACHE_TTL = 3600  # seconds


class PackageInfo(NamedTuple):
    name: str           # display name
    installed: str      # currently installed version / commit
    latest: str         # latest available version / commit
    update_available: bool
    url: str            # link to releases / changelog


def _installed_version(package: str) -> str:
    """Return the installed version of a Python package, or 'unknown'."""
    try:
        from importlib.metadata import version
        return version(package)
    except Exception:
        return "unknown"


def _pypi_latest(package: str) -> str:
    """Return the latest version of a PyPI package."""
    try:
        r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=6)
        r.raise_for_status()
        return r.json()["info"]["version"]
    except Exception:
        return "unknown"


def _github_latest_tag(owner: str, repo: str) -> str:
    """Return the latest release tag (without leading 'v') from GitHub."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/tags",
            timeout=6,
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        tags = r.json()
        if tags:
            return tags[0].get("name", "").lstrip("v")
    except Exception:
        pass
    return "unknown"


def _github_latest_commit_sha(owner: str, repo: str, branch: str = "main") -> str:
    """Return the short SHA of the latest commit on a branch."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}",
            timeout=6,
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        return r.json().get("sha", "")[:7]
    except Exception:
        return "unknown"


def _homebrew_installed_commit() -> str:
    """
    Return the short commit SHA embedded in the Homebrew formula version string
    (e.g. 'HEAD-c118ee2' → 'c118ee2').  Returns '' if not a Homebrew install.
    """
    try:
        result = subprocess.run(
            ["brew", "info", "--json", "vllm-mlx-ui"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return ""
        import json
        data = json.loads(result.stdout)
        installed = data[0].get("installed", [])
        if installed:
            ver = installed[0].get("version", "")  # e.g. "HEAD-c118ee2"
            if ver.startswith("HEAD-"):
                return ver.split("-", 1)[1]
    except Exception:
        pass
    return ""


def _version_gt(latest: str, installed: str) -> bool:
    """Return True if latest semver is strictly greater than installed."""
    if latest in ("unknown", "") or installed in ("unknown", ""):
        return False
    try:
        from packaging.version import Version
        return Version(latest) > Version(installed)
    except Exception:
        # Fallback: simple string compare after stripping 'v'
        return latest.lstrip("v") != installed.lstrip("v")


def _detect_install_method() -> str:
    """Return 'homebrew', 'pip', or 'unknown'."""
    binary = shutil.which("vllm-mlx-ui") or ""
    if "homebrew" in binary.lower() or "cellar" in binary.lower():
        return "homebrew"
    if binary:
        return "pip"
    return "unknown"


def check_updates(force: bool = False) -> list[PackageInfo]:
    """
    Return a list of PackageInfo for each tracked package.
    Results are cached in Streamlit session state for _CACHE_TTL seconds.
    Pass force=True to bypass the cache.
    """
    try:
        import streamlit as st
        cache = st.session_state.get("_update_cache", {})
        if not force and cache.get("ts", 0) + _CACHE_TTL > time.time():
            return cache.get("results", [])
    except Exception:
        cache = {}

    results: list[PackageInfo] = []

    # ── 1. vllm-mlx-ui (our UI project, Homebrew HEAD install) ────────────────
    ui_installed_commit = _homebrew_installed_commit()
    ui_latest_commit = _github_latest_commit_sha("clickbrain", "vllm-mlx-ui")
    ui_update = (
        bool(ui_installed_commit)
        and bool(ui_latest_commit)
        and ui_latest_commit not in ("unknown", "")
        and ui_installed_commit != ui_latest_commit
    )
    from vllm_mlx.dashboard import __version__ as _ui_ver
    results.append(PackageInfo(
        name="vllm-mlx-ui (dashboard)",
        installed=f"v{_ui_ver} ({ui_installed_commit or 'pip'})",
        latest=f"commit {ui_latest_commit}",
        update_available=ui_update,
        url="https://github.com/clickbrain/vllm-mlx-ui/commits/main",
    ))

    # ── 2. vllm-mlx (upstream inference engine) ───────────────────────────────
    vllm_installed = _installed_version("vllm-mlx")
    vllm_latest = _github_latest_tag("waybarrios", "vllm-mlx")
    results.append(PackageInfo(
        name="vllm-mlx (inference engine)",
        installed=vllm_installed,
        latest=vllm_latest,
        update_available=_version_gt(vllm_latest, vllm_installed),
        url="https://github.com/waybarrios/vllm-mlx/releases",
    ))

    # ── 3. mlx-lm ─────────────────────────────────────────────────────────────
    mlxlm_installed = _installed_version("mlx-lm")
    mlxlm_latest = _pypi_latest("mlx-lm")
    results.append(PackageInfo(
        name="mlx-lm",
        installed=mlxlm_installed,
        latest=mlxlm_latest,
        update_available=_version_gt(mlxlm_latest, mlxlm_installed),
        url="https://pypi.org/project/mlx-lm/#history",
    ))

    # ── 4. huggingface-hub ────────────────────────────────────────────────────
    hfhub_installed = _installed_version("huggingface-hub")
    hfhub_latest = _pypi_latest("huggingface-hub")
    results.append(PackageInfo(
        name="huggingface-hub",
        installed=hfhub_installed,
        latest=hfhub_latest,
        update_available=_version_gt(hfhub_latest, hfhub_installed),
        url="https://pypi.org/project/huggingface-hub/#history",
    ))

    try:
        import streamlit as st
        st.session_state["_update_cache"] = {"ts": time.time(), "results": results}
    except Exception:
        pass

    return results


def upgrade_command() -> list[str]:
    """Return the shell command to upgrade the installation."""
    method = _detect_install_method()
    if method == "homebrew":
        return ["brew", "upgrade", "--fetch-HEAD", "vllm-mlx-ui"]
    # pip / install.sh path
    return [
        shutil.which("pip3") or "pip3",
        "install", "--upgrade",
        "git+https://github.com/clickbrain/vllm-mlx-ui.git#egg=vllm-mlx[ui]",
    ]


def relaunch() -> None:
    """
    Start a fresh vllm-mlx-ui process and terminate the current one.
    Called after a successful upgrade.
    """
    import os
    import sys

    binary = shutil.which("vllm-mlx-ui")
    if binary:
        subprocess.Popen([binary])
    else:
        # Fallback: re-exec current Python with same args
        subprocess.Popen([sys.executable] + sys.argv)

    time.sleep(5)   # let the new process bind its port
    os._exit(0)     # hard-exit the current Streamlit process
