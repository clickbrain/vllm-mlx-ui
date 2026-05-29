# SPDX-License-Identifier: Apache-2.0
"""Tests for engine management bug fixes (v0.8.16).

Covers:
- _BUILTINS order: VllmMlxEngine and RapidMlxEngine appear before AppleFMEngine / ExternalApiEngine
- ExternalApiEngine excluded from _try_engine_fallback
- _start_or_mark_external() calls set_server_healthy() for openai-compatible
- LmStudioEngine._is_daemon_running() TTL cache
- AppleFMEngine.check_warnings() rate-limit advisory only when installed
- AppleFMEngine.check_requirements() no longer runs brew tap subprocess
- registry.py _cached_latest_version() caches network calls
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ── Registry _BUILTINS order ──────────────────────────────────────────────────


class TestBuiltinsOrder:
    def test_rapid_mlx_before_apple_fm(self):
        from vllm_mlx.dashboard.engines.registry import _BUILTINS

        ids = [e.id for e in _BUILTINS]
        assert ids.index("rapid-mlx") < ids.index("apple-fm"), (
            "rapid-mlx must come before apple-fm in _BUILTINS"
        )

    def test_rapid_mlx_before_external_api(self):
        from vllm_mlx.dashboard.engines.registry import _BUILTINS

        ids = [e.id for e in _BUILTINS]
        assert ids.index("rapid-mlx") < ids.index("openai-compatible"), (
            "rapid-mlx must come before openai-compatible in _BUILTINS"
        )

    def test_first_engine_is_rapid_mlx(self):
        from vllm_mlx.dashboard.engines.registry import _BUILTINS

        assert _BUILTINS[0].id == "rapid-mlx", "rapid-mlx must be the first engine (primary local engine)"

    def test_vllm_mlx_is_hidden(self):
        """vllm-mlx must be present in _BUILTINS but marked hidden for config migration."""
        from vllm_mlx.dashboard.engines.registry import _BUILTINS

        ids = [e.id for e in _BUILTINS]
        assert "vllm-mlx" in ids, "vllm-mlx must remain in _BUILTINS for config migration"
        vllm_engine = next(e for e in _BUILTINS if e.id == "vllm-mlx")
        assert getattr(vllm_engine, "hidden", False) is True, "vllm-mlx must have hidden=True"


# ── _try_engine_fallback excludes openai-compatible ──────────────────────────


class TestEngineFallback:
    def test_skips_external_api_engine(self):
        """_try_engine_fallback must never select openai-compatible as fallback."""
        from vllm_mlx.dashboard.app import _try_engine_fallback

        calls: list[str] = []

        def fake_start(cfg):
            calls.append(cfg.get("engine_id"))
            return True, "ok"

        fake_sm = MagicMock()
        fake_sm.set_server_healthy = MagicMock()

        # Patch registry so only openai-compatible is "installed"
        fake_engines = {
            "openai-compatible": MagicMock(id="openai-compatible", is_installed=lambda: True),
        }
        with patch("vllm_mlx.dashboard.app.ENGINES", fake_engines, create=True):
            with patch("vllm_mlx.dashboard.engines.registry.ENGINES", fake_engines):
                cfg = {"engine_id": "lm-studio"}
                result_cfg, ok, msg = _try_engine_fallback(
                    cfg, "not installed",
                    load_config=lambda: dict(cfg),
                    save_config=lambda c: None,
                    start_server=fake_start,
                    sm=fake_sm,
                )
        # Should return original failure — openai-compatible was skipped
        assert not ok, "Should fail when only openai-compatible is available as fallback"
        assert "openai-compatible" not in calls

    def test_selects_vllm_mlx_over_external_api(self):
        """vllm-mlx should be preferred over openai-compatible for fallback."""
        from vllm_mlx.dashboard.app import _try_engine_fallback

        selected: list[str] = []

        def fake_start(cfg):
            selected.append(cfg.get("engine_id"))
            return True, "started"

        fake_sm = MagicMock()

        fake_engines = {
            "vllm-mlx": MagicMock(id="vllm-mlx", is_installed=lambda: True),
            "openai-compatible": MagicMock(id="openai-compatible", is_installed=lambda: True),
        }
        with patch("vllm_mlx.dashboard.engines.registry.ENGINES", fake_engines):
            cfg = {"engine_id": "lm-studio"}
            result_cfg, ok, msg = _try_engine_fallback(
                cfg, "not installed",
                load_config=lambda: {"engine_id": "vllm-mlx"},
                save_config=lambda c: None,
                start_server=fake_start,
                sm=fake_sm,
            )
        assert ok
        assert selected == ["vllm-mlx"], "vllm-mlx should be selected, not openai-compatible"


# ── _start_or_mark_external ───────────────────────────────────────────────────


class TestStartOrMarkExternal:
    def test_external_engine_calls_set_server_healthy(self):
        from vllm_mlx.dashboard.app import _start_or_mark_external

        fake_start = MagicMock(return_value=(True, "started"))
        fake_sm = MagicMock()
        fake_sm.set_server_healthy = MagicMock()

        ok, msg = _start_or_mark_external(
            {"engine_id": "openai-compatible"}, fake_start, fake_sm
        )
        assert ok is True
        fake_sm.set_server_healthy.assert_called_once()
        fake_start.assert_not_called()

    def test_local_engine_calls_start_server(self):
        from vllm_mlx.dashboard.app import _start_or_mark_external

        fake_start = MagicMock(return_value=(True, "started"))
        fake_sm = MagicMock()

        ok, msg = _start_or_mark_external(
            {"engine_id": "vllm-mlx"}, fake_start, fake_sm
        )
        assert ok is True
        fake_start.assert_called_once()
        fake_sm.set_server_healthy.assert_not_called()


# ── LmStudioEngine daemon TTL cache ──────────────────────────────────────────


class TestLmStudioDaemonCache:
    def setup_method(self):
        """Reset module-level cache before each test."""
        import vllm_mlx.dashboard.engines.lmstudio as _lms_mod
        _lms_mod._daemon_cache = None

    def test_cache_hit_avoids_subprocess(self):
        import vllm_mlx.dashboard.engines.lmstudio as _lms_mod
        from vllm_mlx.dashboard.engines.lmstudio import LmStudioEngine

        engine = LmStudioEngine()
        call_count = 0

        def fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.returncode = 0
            return m

        with patch.object(engine, "_find_lms", return_value="/usr/local/bin/lms"):
            with patch("subprocess.run", side_effect=fake_run):
                r1 = engine._is_daemon_running()
                r2 = engine._is_daemon_running()  # should hit cache

        assert r1 is True
        assert r2 is True
        assert call_count == 1, "subprocess.run should be called only once due to caching"

    def test_cache_expires_after_ttl(self):
        import vllm_mlx.dashboard.engines.lmstudio as _lms_mod
        from vllm_mlx.dashboard.engines.lmstudio import LmStudioEngine, _DAEMON_CACHE_TTL

        engine = LmStudioEngine()
        call_count = 0

        def fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.returncode = 0
            return m

        with patch.object(engine, "_find_lms", return_value="/usr/local/bin/lms"):
            with patch("subprocess.run", side_effect=fake_run):
                engine._is_daemon_running()
                # Expire the cache manually
                _lms_mod._daemon_cache = (time.monotonic() - _DAEMON_CACHE_TTL - 1, True)
                engine._is_daemon_running()  # should re-run subprocess

        assert call_count == 2, "subprocess.run should fire again after TTL expiry"

    def test_no_lms_binary_returns_false(self):
        import vllm_mlx.dashboard.engines.lmstudio as _lms_mod
        from vllm_mlx.dashboard.engines.lmstudio import LmStudioEngine

        engine = LmStudioEngine()
        with patch.object(engine, "_find_lms", return_value=None):
            result = engine._is_daemon_running()
        assert result is False


# ── AppleFMEngine check_warnings rate-limit advisory ─────────────────────────


class TestAppleFMWarnings:
    def test_rate_limit_advisory_shown_when_installed(self):
        from vllm_mlx.dashboard.engines.apple_fm import AppleFMEngine

        engine = AppleFMEngine()
        with patch.object(engine, "is_installed", return_value=True):
            warnings = engine.check_warnings()
        rate_limit_warnings = [w for w in warnings if "rate limit" in w.lower()]
        assert len(rate_limit_warnings) == 1, "Rate-limit advisory should appear when apfel is installed"

    def test_rate_limit_advisory_hidden_when_not_installed(self):
        from vllm_mlx.dashboard.engines.apple_fm import AppleFMEngine

        engine = AppleFMEngine()
        with patch.object(engine, "is_installed", return_value=False):
            warnings = engine.check_warnings()
        rate_limit_warnings = [w for w in warnings if "rate limit" in w.lower()]
        assert len(rate_limit_warnings) == 0, "Rate-limit advisory should NOT appear when apfel is not installed"


# ── AppleFMEngine check_requirements no brew tap subprocess ──────────────────


class TestAppleFMRequirements:
    def test_no_brew_tap_subprocess(self):
        from vllm_mlx.dashboard.engines.apple_fm import AppleFMEngine
        import subprocess

        engine = AppleFMEngine()
        brew_calls: list[str] = []

        original_run = subprocess.run

        def spy_run(args, *a, **kw):
            if isinstance(args, list) and "brew" in args and "tap" in args:
                brew_calls.append(" ".join(args))
            return original_run(args, *a, **kw)

        with patch("subprocess.run", side_effect=spy_run):
            engine.check_requirements()

        assert len(brew_calls) == 0, f"check_requirements must not run 'brew tap': {brew_calls}"


# ── registry _cached_latest_version TTL cache ─────────────────────────────────


class TestCachedLatestVersion:
    def setup_method(self):
        import vllm_mlx.dashboard.engines.registry as _reg
        _reg._latest_version_cache.clear()

    def test_cache_hit_avoids_second_call(self):
        from vllm_mlx.dashboard.engines.registry import _cached_latest_version

        engine = MagicMock()
        engine.id = "test-engine"
        engine.latest_version = MagicMock(return_value="1.2.3")

        r1 = _cached_latest_version(engine)
        r2 = _cached_latest_version(engine)

        assert r1 == "1.2.3"
        assert r2 == "1.2.3"
        assert engine.latest_version.call_count == 1, "latest_version() should be called only once"

    def test_exception_does_not_propagate(self):
        from vllm_mlx.dashboard.engines.registry import _cached_latest_version

        engine = MagicMock()
        engine.id = "bad-engine"
        engine.latest_version = MagicMock(side_effect=RuntimeError("network error"))

        result = _cached_latest_version(engine)
        assert result is None, "Should return None on network failure, not raise"

    def test_cache_expires_after_ttl(self):
        import vllm_mlx.dashboard.engines.registry as _reg
        from vllm_mlx.dashboard.engines.registry import _cached_latest_version, _LATEST_VERSION_TTL

        engine = MagicMock()
        engine.id = "ttl-engine"
        engine.latest_version = MagicMock(return_value="2.0.0")

        _cached_latest_version(engine)
        # Manually expire cache
        _reg._latest_version_cache["ttl-engine"] = (time.monotonic() - _LATEST_VERSION_TTL - 1, "1.0.0")
        _cached_latest_version(engine)

        assert engine.latest_version.call_count == 2, "Should re-fetch after TTL expiry"
