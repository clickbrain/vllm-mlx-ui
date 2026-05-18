# SPDX-License-Identifier: Apache-2.0
"""Runtime flag capability probing for inference engine binaries.

Each engine binary evolves independently.  Flags that exist in one version
may not exist in another.  This module probes the binary's ``--help`` output
once per dashboard session and caches the result so ``build_command()`` can
guard optional flags before adding them to the launch command.

Probe policy
------------
* **Successful probe**: cached for the process lifetime (dashboard restart
  clears the cache, which naturally happens after an engine upgrade).
* **Failed probe** (binary not installed, timeout, empty output): not cached;
  the caller falls back to optimistic behaviour (adds the flag anyway) to
  preserve backward compatibility with versions that predate this module.
* **Security flags** (``--api-key``): if the probe succeeds but the flag is
  absent, a warning is emitted.  The flag is silently dropped because the
  proxy layer enforces auth independently.
"""
from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Successful probes cached here.  key: cmd tuple  value: frozenset of flags.
_CACHE: dict[tuple[str, ...], frozenset[str]] = {}


def probe_flags(cmd: tuple[str, ...]) -> frozenset[str] | None:
    """Run *cmd* + ``["--help"]`` and return every ``--flag`` found.

    Returns ``None`` if the subprocess fails or produces no output.
    Successful results are cached; failures are not (will retry next call).
    """
    if cmd in _CACHE:
        return _CACHE[cmd]
    try:
        result = subprocess.run(
            list(cmd) + ["--help"],
            capture_output=True, text=True, timeout=10,
        )
        text = (result.stdout + result.stderr).strip()
        if not text:
            return None  # binary not ready — don't cache
        flags = frozenset(re.findall(r"--[\w-]+", text))
        _CACHE[cmd] = flags
        logger.debug("flag_probe %s → %d flags cached", cmd[0], len(flags))
        return flags
    except Exception as exc:
        logger.debug("flag_probe failed for %s: %s", cmd, exc)
        return None  # don't cache failures


def supports(probe_cmd: tuple[str, ...], flag: str) -> bool | None:
    """Return whether *flag* is supported, or ``None`` if the probe failed.

    ``None`` means "unknown" — callers should add the flag optimistically.
    """
    flags = probe_flags(probe_cmd)
    if flags is None:
        return None
    return flag in flags


def add_if_supported(
    cmd: list[str],
    probe_cmd: tuple[str, ...],
    flag: str,
    extra: list[str] | None = None,
    *,
    warn_if_unsupported: str | None = None,
) -> bool:
    """Append *flag* (and optional *extra* args) to *cmd* when supported.

    If the probe failed the flag is added optimistically (backward-compatible).
    If *warn_if_unsupported* is set, emit a warning when the flag is confirmed
    unsupported and we are intentionally skipping it.

    Returns ``True`` if the flag was added.
    """
    result = supports(probe_cmd, flag)
    if result is None or result:
        # None = probe failed → optimistic; True = confirmed supported
        cmd.append(flag)
        if extra:
            cmd.extend(extra)
        return True
    # Confirmed unsupported
    if warn_if_unsupported:
        logger.warning(warn_if_unsupported)
    return False


def invalidate(probe_cmd: tuple[str, ...] | None = None) -> None:
    """Clear cached probe results.

    Call after an engine install or upgrade so the next ``build_command``
    picks up the newly installed binary's flag set.

    If *probe_cmd* is ``None``, clears the entire cache.
    """
    if probe_cmd is None:
        _CACHE.clear()
        logger.debug("flag_probe: full cache cleared")
    else:
        _CACHE.pop(probe_cmd, None)
        logger.debug("flag_probe: cache cleared for %s", probe_cmd)
