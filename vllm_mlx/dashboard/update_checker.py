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
import threading
import time
from typing import NamedTuple

import requests
import logging
logger = logging.getLogger(__name__)

_CACHE_TTL = 3600  # seconds

# Module-level cache — written by background threads, read by UI thread.
# Protected by _cache_lock for thread-safe access.
_cache: dict = {}
_cache_lock = threading.Lock()

# Upgrade progress: set by mgmt_server._do_upgrade so the frontend can poll.
# Values: 'idle' | 'upgrading' | 'restarting' | 'done' | 'error:<msg>'
upgrade_status: str = "idle"


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
    """Return the installed version of a Python package, or 'unknown'.

    Prefers a proper `.dist-info` in the running venv's site-packages over any
    `.egg-info` found by importlib.metadata when scanning the working directory.
    This prevents stale editable-install egg-info files from shadowing the real
    installed version (a known footgun when both vllm-mlx and vllm-mlx-ui share
    the same top-level `vllm_mlx` namespace).
    """
    import sys
    import importlib.metadata as _meta
    normalized = package.lower().replace("-", "_")
    try:
        # Prefer a distribution whose metadata lives inside the running venv,
        # falling back to any distribution if nothing venv-local is found.
        site_pkgs = {p for p in sys.path if "site-packages" in p}
        best: str | None = None
        for dist in _meta.distributions():
            name = (dist.metadata.get("Name") or "").lower().replace("-", "_")
            if name != normalized:
                continue
            ver = dist.metadata.get("Version") or ""
            dist_path = str(getattr(dist, "_path", ""))
            if any(sp in dist_path for sp in site_pkgs) and ".dist-info" in dist_path:
                # This is the real venv installation — use it immediately.
                return ver
            if best is None:
                best = ver
        return best or "unknown"
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return "unknown"


def _pypi_latest(package: str) -> str:
    """Return the latest version of a PyPI package that has a wheel for the current platform.

    Uses the PyPI JSON API to find the newest version that ships a bdist_wheel
    compatible with the running Python version and machine architecture.  Falls
    back to the simple index (version string only) when the detailed JSON is
    unavailable, which may produce false positives on source-only releases.
    """
    import platform
    import sys

    try:
        r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=6)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        return "unknown"

    py_major_minor = f"{sys.version_info.major}{sys.version_info.minor}"
    machine = platform.machine().lower()
    system = platform.system().lower()

    # Build a set of PyPI platform tags that match this machine.
    # We keep it simple: match on the interpreter tag (cpXY) and OS/arch.
    # abi3 wheels (cp38-abi3) are accepted for any Python >= 3.8.
    py_tag_prefix = f"cp{py_major_minor}"
    arch_tags: set[str] = set()
    if system == "darwin":
        arch_tags.add("macosx")
        if machine == "arm64" or machine == "aarch64":
            arch_tags.add("arm64")
            arch_tags.add("aarch64")
        elif machine in ("x86_64", "amd64"):
            arch_tags.add("x86_64")
    elif system == "linux":
        arch_tags.add("linux")
        if machine in ("arm64", "aarch64"):
            arch_tags.add("aarch64")
        elif machine in ("x86_64", "amd64"):
            arch_tags.add("x86_64")

    def _wheel_compatible(url_info: dict) -> bool:
        """Return True when the wheel matches this platform."""
        fname = url_info.get("filename", "")
        if not fname.endswith(".whl"):
            return False
        # filename pattern: {pkg}-{ver}-{py_tag}-{abi}-{platform}.whl
        parts = fname[:-len(".whl")].split("-")
        if len(parts) < 5:
            return False
        py_tag = parts[-3].lower()
        abi_tag = parts[-2].lower()
        platform_tag = parts[-1].lower()
        # Accept pure-Python wheels (none-any) — they work everywhere.
        if platform_tag == "any" and abi_tag == "none":
            pass  # platform is fine, still check Python version below
        else:
            # Check OS/arch match
            if system == "darwin" and "macosx" not in platform_tag:
                return False
            if system == "linux" and "linux" not in platform_tag and "manylinux" not in platform_tag:
                return False
            if arch_tags and not any(a in platform_tag for a in arch_tags):
                return False
        # Accept abi3 wheels built for cp38+ (they run on any Python >= 3.8)
        if "abi3" in abi_tag:
            if not py_tag.startswith("cp") or int(py_tag[2:4]) < 38:
                return False
        else:
            # Accept 'py3' / 'py3-none' style tags — they mean "any Python 3.x"
            if py_tag == "py3":
                pass
            elif not py_tag.startswith(py_tag_prefix):
                return False
        return True

    # Walk versions newest-first (PyPI info["version"] is the latest by default,
    # but we still scan all URLs to confirm wheel availability).
    latest_compatible: str | None = None
    for url_info in data.get("urls", []):
        if url_info.get("packagetype") != "bdist_wheel":
            continue
        if not _wheel_compatible(url_info):
            continue
        ver = data.get("info", {}).get("version", "")
        if ver:
            latest_compatible = ver
            break

    if latest_compatible:
        return latest_compatible

    # No compatible wheel found for this platform.  Do NOT report an update —
    # pip will fail to install it (it would try to build from source and die).
    logger.info(
        "No compatible wheel for %s on %s/%s — suppressing update notification",
        package, system, machine,
    )
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
        logger.warning("Operation failed", exc_info=True)
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
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
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
        logger.warning("Operation failed", exc_info=True)
    return ""


def _version_gt(latest: str, installed: str) -> bool:
    """Return True if latest semver is strictly greater than installed."""
    if latest in ("unknown", "") or installed in ("unknown", ""):
        return False
    try:
        from packaging.version import Version
        return Version(latest) > Version(installed)
    except Exception as e:
        logger.warning("Operation failed: %s", e, exc_info=True)
        # Fallback: parse semver tuples for numeric comparison
        def _parse(ver: str) -> tuple[int, ...]:
            parts = ver.lstrip("v").split(".")
            result: list[int] = []
            for p in parts:
                try:
                    result.append(int(p))
                except ValueError:
                    break
            return tuple(result) or (0,)
        return _parse(latest) > _parse(installed)


def _homebrew_formula_version() -> str | None:
    """Return the Homebrew-installed formula version from `brew info --json`.

    Using brew as the primary source is authoritative regardless of which
    Python process is running (e.g. an old cellar venv that persisted after
    a `brew upgrade`, or a dev editable install that shadows the real version).

    Falls back to parsing sys.prefix so the function still works when the
    `brew` CLI is unavailable (CI, Docker, pip-only installs).
    """
    # Primary: ask brew directly — works even if running from old/deleted cellar
    try:
        import json
        result = subprocess.run(
            ["brew", "info", "--json", "vllm-mlx-ui"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            installed = data[0].get("installed", [])
            if installed:
                ver = installed[0].get("version", "")
                if ver and not ver.startswith("HEAD-"):
                    return ver
    except Exception:
        logger.warning("Operation failed", exc_info=True)

    # Fallback: parse from sys.prefix (only works when process runs inside cellar)
    import sys
    import re
    prefix = sys.prefix
    m = re.search(r"[Cc]ellar/vllm-mlx-ui/([0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)", prefix)
    if m:
        return m.group(1)
    return None


def _detect_install_method() -> str:
    """Return 'homebrew', 'pip', or 'unknown'."""
    import sys
    # Check sys.prefix first — most reliable when running inside a Homebrew cellar
    prefix = sys.prefix.lower()
    if "homebrew" in prefix or "cellar" in prefix or "linuxbrew" in prefix:
        return "homebrew"
    binary = shutil.which("vllm-mlx-ui") or ""
    if "homebrew" in binary.lower() or "cellar" in binary.lower():
        return "homebrew"
    # Check HOMEBREW_PREFIX env (set by Homebrew shell integration)
    import os
    if os.environ.get("HOMEBREW_PREFIX"):
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
    with _cache_lock:
        if not force and _cache.get("ts", 0) + _CACHE_TTL > time.time():
            return _cache.get("results", [])

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _check_ui():
        from vllm_mlx.dashboard import __version__ as _ui_ver
        ui_latest = _github_latest_tag("clickbrain", "vllm-mlx-ui")
        # For stable (tarball) Homebrew installs the version is a semver like
        # "0.3.35" — compare that directly against the latest tag.
        # For HEAD-based installs the version contains a commit SHA: fall back
        # to commit-SHA comparison so nightly users still get update dots.
        ui_installed_commit = _homebrew_installed_commit()
        if ui_installed_commit:
            # HEAD install: compare commit SHAs
            ui_latest_commit = _github_latest_commit_sha("clickbrain", "vllm-mlx-ui")
            ui_update = (
                ui_latest_commit not in ("unknown", "")
                and ui_installed_commit != ui_latest_commit
            )
            installed_display = f"v{_ui_ver} ({ui_installed_commit})"
            latest_display = f"commit {ui_latest_commit}"
        else:
            # Stable semver install: prefer the cellar version (actual UI build)
            # over __version__ (pip package, which may have been upgraded separately
            # leaving the JS assets from an older formula tarball).
            cellar_ver = _homebrew_formula_version()
            installed_ver = cellar_ver or _ui_ver
            ui_update = _version_gt(ui_latest, installed_ver)
            installed_display = f"v{installed_ver}"
            if cellar_ver and cellar_ver != _ui_ver:
                installed_display += f" (pip: v{_ui_ver})"
            latest_display = f"v{ui_latest}" if ui_latest != "unknown" else installed_ver
        return PackageInfo(
            name="vllm-mlx-ui (dashboard)",
            installed=installed_display,
            latest=latest_display,
            update_available=ui_update,
            url="https://github.com/clickbrain/vllm-mlx-ui/releases",
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

    # Add engine update checks dynamically from the registry.
    # pip engines: check PyPI; external engines: call latest_version() if available.
    try:
        from vllm_mlx.dashboard.engines.registry import ENGINES
        for _engine in list(ENGINES.values()):
            # vllm-mlx is bundled and already handled by _check_vllm above.
            if _engine.install_method == "bundled":
                continue
            # Only report on engines the user has actually installed.
            try:
                if not _engine.is_installed():
                    continue
            except Exception:
                continue

            _ename = _engine.name

            def _make_engine_checker(_e=_engine, _e_name=_ename):
                def _check_engine():
                    try:
                        if _e.install_method == "pip":
                            pkg = _e.get_package_name()
                            inst = _installed_version(pkg)
                            latest = _pypi_latest(pkg)
                            url = getattr(_e, "release_url", None) or f"https://pypi.org/project/{pkg}/#history"
                        else:
                            inst = _e.get_version() or "unknown"
                            latest = _e.latest_version()
                            if not latest:
                                return None  # no update info available for this external engine
                            url = getattr(_e, "release_url", "")
                        return PackageInfo(
                            name=f"{_e_name} (engine)",
                            installed=inst,
                            latest=latest if latest != "unknown" else inst,
                            update_available=_version_gt(latest, inst),
                            url=url,
                        )
                    except Exception as exc:
                        logger.warning("Engine update check failed for %s: %s", _e_name, exc, exc_info=True)
                        return None
                return _check_engine

            checkers.append(_make_engine_checker())

            # ── Model update check (for engines that support it) ──────────
            try:
                if hasattr(_engine, "hf_model_latest") and callable(_engine.hf_model_latest):
                    _mname = _engine.name
                    _meng = _engine
                    def _make_model_checker(_e=_meng, _en=_mname):
                        def _check_model():
                            try:
                                installed = _e._model_get_version() if hasattr(_e, "_model_get_version") else None
                                latest = _e.hf_model_latest()
                                if not installed or not latest:
                                    return None
                                updated = False
                                if hasattr(_e, "model_update_available") and callable(_e.model_update_available):
                                    updated = _e.model_update_available()
                                return PackageInfo(
                                    name=f"{_en} (model weights)",
                                    installed=str(installed),
                                    latest=str(latest),
                                    update_available=updated,
                                    url=getattr(_e, "release_url", ""),
                                )
                            except Exception as exc:
                                logger.warning("Model update check failed for %s: %s", _en, exc, exc_info=True)
                                return None
                        return _check_model
                    checkers.append(_make_model_checker())
            except Exception as exc:
                logger.warning("Model update check setup failed: %s", exc)

    except Exception as exc:
        logger.warning("Could not load engine registry for update checks: %s", exc)

    results: list[PackageInfo] = [None] * len(checkers)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max(4, len(checkers))) as pool:
        futures = {pool.submit(fn): i for i, fn in enumerate(checkers)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                logger.warning("Operation failed", exc_info=True)
    results = [r for r in results if r is not None]

    with _cache_lock:
        _cache = {"ts": time.time(), "results": results}
    return results


def get_cached_updates() -> list[PackageInfo] | None:
    """Return cached update results without making any network calls.

    Returns ``None`` if the cache is cold (never fetched or expired).
    Callers that need up-to-date data should use ``check_updates()`` instead.
    """
    with _cache_lock:
        if _cache.get("ts", 0) + _CACHE_TTL > time.time():
            return list(_cache.get("results", []))
    return None


def bust_cache() -> None:
    """Invalidate the update cache so the next check_updates() hits the network."""
    global _cache
    with _cache_lock:
        _cache = {}


def engine_upgrade_commands(pip_bin: str) -> list[list[str]]:
    """Return argv lists to upgrade each installed engine (best-effort).

    Each command is an argv list suitable for ``subprocess.run()`` — no shell
    quoting, no ``&&`` chains, no ambiguity.  Pip engines are upgraded via
    ``pip install --upgrade <pkg>``; other engines use their
    ``upgrade_command()`` method directly.
    """
    cmds: list[list[str]] = []
    try:
        from vllm_mlx.dashboard.engines.registry import ENGINES, _registry_lock
        with _registry_lock:
            engines_snapshot = dict(ENGINES)
        for engine in engines_snapshot.values():
            try:
                if not engine.is_installed():
                    continue
            except Exception:
                continue

            if engine.install_method == "pip":
                pkg = engine.get_package_name()
                if pkg:
                    cmds.append([pip_bin, "install", "--upgrade", pkg])

            try:
                cmd = engine.upgrade_command()
            except Exception:
                cmd = None
            if cmd:
                cmds.append(cmd)
    except Exception:
        logger.warning("Failed to discover engine upgrades", exc_info=True)
    return cmds


def _resolve_pip_bin(python_exe: str) -> str:
    """Resolve the pip binary for the same Python environment."""
    from pathlib import Path as _Path
    venv_bin = _Path(python_exe).parent
    pip = str(venv_bin / "pip")
    if not _Path(pip).exists():
        pip = str(venv_bin / "pip3")
    if not _Path(pip).exists():
        pip = shutil.which("pip3") or "pip3"
    return pip


def upgrade_command() -> list[str]:
    """Return the shell command to upgrade the installation."""
    import sys
    from pathlib import Path as _Path

    method = _detect_install_method()

    # Resolve pip from the *running* Python — guarantees we upgrade packages
    # inside the correct venv (brew cellar or dev) rather than a system pip.
    pip = _resolve_pip_bin(sys.executable)

    if method == "homebrew":
        # Force-update the tap's git repo so brew sees the new formula immediately.
        # brew upgrade alone may not detect new versions for hours due to
        # Homebrew's auto-update throttle or stale tap caches.
        tap_dir = None
        # Try to find the tap using brew --repo
        try:
            result = subprocess.run(
                ["brew", "--repo", "clickbrain/vllm-mlx-ui"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                tap_dir = _Path(result.stdout.strip())
        except Exception:
            pass
        # Fallback: try common Homebrew locations
        if not tap_dir or not tap_dir.exists():
            for candidate in [
                Path.home() / ".homebrew" / "Library" / "Taps",
                Path("/opt/homebrew/Library/Taps"),
                Path("/usr/local/Homebrew/Library/Taps"),
            ]:
                candidate = candidate / "clickbrain" / "homebrew-vllm-mlx-ui"
                if candidate.exists():
                    tap_dir = candidate
                    break
        git_pull = f"cd {tap_dir} && git fetch origin && git checkout main && git pull origin main"
        base = (
            f"{git_pull} && brew upgrade vllm-mlx-ui"
            f" && {pip} install --upgrade vllm-mlx mlx-lm huggingface-hub vllm"
        )
        return ["sh", "-c", base]
    # dev / conda / pip install path — upgrade deps unconditionally first.
    # The UI itself is not on PyPI; users running from source pull via git.
    return ["sh", "-c", f"{pip} install --upgrade vllm-mlx mlx-lm huggingface-hub vllm"]


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
        logger.warning("Operation failed", exc_info=True)

    # Hard-exit this Streamlit subprocess immediately.
    # app.py's finally block detects RELAUNCH_FLAG and starts the new process
    # only after this process is fully gone — no port conflicts.
    os._exit(0)
