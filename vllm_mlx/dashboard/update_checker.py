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

# Module-level cache — written by background threads, read by UI thread.
# Avoids touching st.session_state from non-Streamlit threads (which produces
# "missing ScriptRunContext" warnings on every call).
_cache: dict = {}


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
        return PackageInfo(
            name="vllm-mlx (inference engine)",
            installed=vllm_installed,
            latest=vllm_latest,
            update_available=_version_gt(vllm_latest, vllm_installed),
            url="https://github.com/waybarrios/vllm-mlx/releases",
        )

    def _check_mlxlm():
        inst = _installed_version("mlx-lm")
        latest = _pypi_latest("mlx-lm")
        return PackageInfo(
            name="mlx-lm",
            installed=inst,
            latest=latest,
            update_available=_version_gt(latest, inst),
            url="https://pypi.org/project/mlx-lm/#history",
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
    checkers = [_check_ui, _check_vllm, _check_mlxlm, _check_hfhub]
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
        return ["brew", "upgrade", "--fetch-HEAD", "vllm-mlx-ui"]
    # pip / install.sh path
    return [
        shutil.which("pip3") or "pip3",
        "install", "--upgrade",
        "git+https://github.com/clickbrain/vllm-mlx-ui.git#egg=vllm-mlx[ui]",
    ]


def _find_binary() -> list[str]:
    """
    Return the command to relaunch vllm-mlx-ui as a list of strings.
    Tries multiple strategies so the binary is found even when the
    Streamlit subprocess has a stripped-down PATH.
    """
    import sys

    # 1. Current process PATH (works in most environments)
    found = shutil.which("vllm-mlx-ui")
    if found:
        return [found]

    # 2. Common Homebrew locations (macOS Apple Silicon and Intel)
    for candidate in [
        "/opt/homebrew/bin/vllm-mlx-ui",
        "/usr/local/bin/vllm-mlx-ui",
    ]:
        if shutil.os.path.isfile(candidate) and shutil.os.access(candidate, shutil.os.X_OK):
            return [candidate]

    # 3. Same bin directory as the current Python interpreter
    from pathlib import Path
    sibling = Path(sys.executable).parent / "vllm-mlx-ui"
    if sibling.exists():
        return [str(sibling)]

    # 4. Last resort: re-run as a Python module (always works but skips
    #    Homebrew's PATH manipulation)
    return [sys.executable, "-m", "vllm_mlx.dashboard.app"]


def relaunch() -> None:
    """
    Start a fresh vllm-mlx-ui process and terminate the current one.
    Called after a successful upgrade.  If the inference server is currently
    running, writes a flag file so the new process auto-starts it.
    """
    import os

    # Write auto-start flag if the inference server is running right now
    try:
        from vllm_mlx.dashboard.server_manager import get_server_status, AUTO_START_FLAG, STATE_DIR
        status = get_server_status()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if status.get("running"):
            AUTO_START_FLAG.write_text("1")
        else:
            AUTO_START_FLAG.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = _find_binary()

    # IMPORTANT: start_new_session=True puts the new process in its own
    # process group so it is NOT killed when we os._exit() the current one.
    # Redirect stdio so it has no inherited file descriptors.
    subprocess.Popen(
        cmd,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(8)   # give the new process time to bind its ports
    os._exit(0)     # hard-exit the current Streamlit process only
