# SPDX-License-Identifier: Apache-2.0
"""
Update checker for vllm-mlx-ui and its key dependencies.

Checks for newer versions of:
- vllm-mlx-ui (this project)  — compares installed commit hash vs latest commit on main
- vllm-mlx (upstream engine)  — compares installed version vs latest GitHub tag
- huggingface-hub             — compares installed version vs PyPI

Results are cached in a module-level dict for 1 hour to avoid hammering GitHub/PyPI.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import NamedTuple

import requests

_CACHE_TTL = 3600  # seconds

# Module-level cache — written by background threads, read by UI thread.
# Avoids touching st.session_state from non-Streamlit threads (which produces
# "missing ScriptRunContext" warnings on every call).
_cache: dict = {}


class PackageInfo(NamedTuple):
    """Metadata for a single trackable package's update state.

    Attributes:
        name: Human-readable display name (e.g. "vllm-mlx (inference engine)").
        installed: Currently installed version string or commit SHA.
        latest: Latest available version string or commit SHA.
        update_available: True when an upgrade is ready to install.
        url: Link to the project's releases page or changelog.
    """

    name: str
    installed: str
    latest: str
    update_available: bool
    url: str


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
    Results are cached in a module-level dict for _CACHE_TTL seconds.
    Pass force=True to bypass the cache.
    Checks run in parallel so the total wait is ~3 seconds max.
    Safe to call from background threads — does not touch st.session_state.
    """
    global _cache
    if not force and _cache.get("ts", 0) + _CACHE_TTL > time.time():
        return _cache.get("results", [])

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _check_ui():
        ui_installed_commit = _homebrew_installed_commit()
        ui_latest_commit = _github_latest_commit_sha("clickbrain", "vllm-mlx-ui")
        ui_update = (
            bool(ui_installed_commit)
            and ui_latest_commit not in ("unknown", "")
            and ui_installed_commit != ui_latest_commit
        )
        from vllm_mlx.dashboard import __version__ as _ui_ver
        return PackageInfo(
            name="vllm-mlx-ui (dashboard)",
            installed=f"v{_ui_ver} ({ui_installed_commit or 'pip'})",
            latest=f"commit {ui_latest_commit}",
            update_available=ui_update,
            url="https://github.com/clickbrain/vllm-mlx-ui/commits/main",
        )

    def _check_vllm():
        vllm_installed = _installed_version("vllm-mlx")
        vllm_latest = _github_latest_tag("waybarrios", "vllm-mlx")
        update_available = _version_gt(vllm_latest, vllm_installed)
        return PackageInfo(
            name="vllm-mlx (inference engine)",
            installed=vllm_installed,
            latest=vllm_latest if vllm_latest != "unknown" else vllm_installed,
            update_available=update_available,
            url="https://github.com/waybarrios/vllm-mlx/releases",
        )

    def _check_hfhub():
        inst = _installed_version("huggingface-hub")
        latest = _pypi_latest("huggingface-hub")
        return PackageInfo(
            name="huggingface-hub",
            installed=inst,
            latest=latest,
            update_available=_version_gt(latest, inst),
            url="https://pypi.org/project/huggingface-hub/#history",
        )

    # Run all checks in parallel — total wait is max(individual timeouts) ≈ 3s
    checkers = [_check_ui, _check_vllm, _check_hfhub]
    results: list[PackageInfo] = [None] * len(checkers)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): i for i, fn in enumerate(checkers)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                pass
    results = [r for r in results if r is not None]

    _cache = {"ts": time.time(), "results": results}
    return results


def upgrade_command() -> list[str]:
    """Return the shell command to upgrade the installation."""
    method = _detect_install_method()
    if method == "homebrew":
        # brew update pulls the latest tap (third-party taps are git repos —
        # they are NOT updated by the JSON API download that brew upgrade does).
        # brew upgrade then installs the newest stable release.
        return ["sh", "-c", "brew update && brew upgrade vllm-mlx-ui"]
    # pip / install.sh path — upgrade the dashboard and all key dependencies
    pip = shutil.which("pip3") or "pip3"
    return [
        "sh", "-c",
        f"{pip} install --upgrade "
        f"git+https://github.com/clickbrain/vllm-mlx-ui.git#egg=vllm-mlx[ui] "
        f"&& {pip} install --upgrade huggingface-hub",
    ]


def relaunch() -> None:
    """
    Signal app.py to start a fresh vllm-mlx-ui process, then exit.

    Writes RELAUNCH_FLAG so app.py's finally block starts a new process.
    Writes AUTO_START_FLAG if the inference server is running so the new
    process reconnects to it automatically.

    Does NOT start the new process here — that way app.py starts it only
    after the old Streamlit is fully gone, avoiding port 8501 conflicts.
    """
    import os

    try:
        from vllm_mlx.dashboard.server_manager import (
            get_server_status, AUTO_START_FLAG, RELAUNCH_FLAG, STATE_DIR,
        )
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        status = get_server_status()
        if status.get("running"):
            AUTO_START_FLAG.write_text("1")
        else:
            AUTO_START_FLAG.unlink(missing_ok=True)
        RELAUNCH_FLAG.write_text("1")
    except Exception:
        pass

    # Hard-exit this Streamlit subprocess immediately.
    # app.py's finally block detects RELAUNCH_FLAG and starts the new process
    # only after this process is fully gone — no port conflicts.
    os._exit(0)
