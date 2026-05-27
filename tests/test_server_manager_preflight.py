# SPDX-License-Identifier: Apache-2.0
"""Tests for server_manager.start_server() pre-flight engine checks."""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

import vllm_mlx.dashboard.server_manager as sm


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_config(engine_id="lm-studio", model="some/model"):
    return {"engine_id": engine_id, "model": model, "port": 19998, "host": "127.0.0.1"}


def _local_state_patches():
    """Return list of patch objects that suppress all real system-state reads."""
    return [
        patch.object(sm, "_get_pid", return_value=None),
        patch.object(sm, "_is_process_alive", return_value=False),
        patch.object(sm, "_port_in_use", return_value=False),
        patch.object(sm, "_ensure_state_dir"),
        patch.object(sm, "save_config"),
    ]


def _start_with_patches(extra_patches, config=None):
    """Enter all patches via ExitStack and call start_server()."""
    if config is None:
        config = _make_config()
    with contextlib.ExitStack() as stack:
        for p in extra_patches + _local_state_patches():
            stack.enter_context(p)
        return sm.start_server(config)


# ── Engine pre-flight check ────────────────────────────────────────────────────


class TestStartServerPreflightCheck:
    def _run(self, is_installed: bool, engine_id: str = "lm-studio"):
        mock_engine = MagicMock()
        mock_engine.is_installed.return_value = is_installed
        extra = [patch("vllm_mlx.dashboard.server_manager.get_engine", return_value=mock_engine)]
        return _start_with_patches(extra, config=_make_config(engine_id=engine_id))

    def test_returns_false_when_engine_not_installed(self):
        ok, msg = self._run(is_installed=False, engine_id="lm-studio")
        assert ok is False

    def test_error_message_names_the_engine(self):
        _, msg = self._run(is_installed=False, engine_id="lm-studio")
        assert "lm-studio" in msg

    def test_error_message_suggests_install_or_switch(self):
        _, msg = self._run(is_installed=False, engine_id="lm-studio")
        lower = msg.lower()
        assert "install" in lower or "switch" in lower

    def test_does_not_raise_file_not_found_error(self):
        """Pre-flight must prevent FileNotFoundError from escaping."""
        try:
            self._run(is_installed=False, engine_id="lm-studio")
        except FileNotFoundError:
            pytest.fail("FileNotFoundError escaped from start_server()")

    def test_unknown_engine_falls_through(self):
        """Unknown engine ID should not raise — fall through to _build_command."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        extra = [
            patch("vllm_mlx.dashboard.server_manager.get_engine", side_effect=KeyError("unknown")),
            patch.object(sm, "_build_command", return_value=["/bin/true"]),
            patch.object(sm, "_build_env", return_value=None),
            patch.object(sm, "_build_cwd", return_value=None),
            patch("subprocess.Popen", return_value=mock_proc),
            patch.object(sm, "_write_server_state"),
        ]
        # Should not raise; may succeed or fail based on env — just no KeyError
        try:
            ok, _ = _start_with_patches(extra, config=_make_config(engine_id="nonexistent"))
        except KeyError:
            pytest.fail("KeyError from get_engine() escaped start_server()")
        assert isinstance(ok, bool)


class TestStartServerPopen:
    def test_popen_file_not_found_returns_false_not_raise(self):
        """FileNotFoundError from subprocess.Popen must be caught and returned as (False, msg)."""
        mock_engine = MagicMock()
        mock_engine.is_installed.return_value = True  # passes pre-flight
        extra = [
            patch("vllm_mlx.dashboard.server_manager.get_engine", return_value=mock_engine),
            patch.object(sm, "_build_command", return_value=["nonexistent-binary", "--flag"]),
            patch.object(sm, "_build_env", return_value=None),
            patch.object(sm, "_build_cwd", return_value=None),
            patch("subprocess.Popen", side_effect=FileNotFoundError("no such binary")),
        ]
        try:
            ok, msg = _start_with_patches(extra)
        except FileNotFoundError:
            pytest.fail("FileNotFoundError escaped from start_server() Popen path")

        assert ok is False
        lower = msg.lower()
        assert "nonexistent-binary" in msg or "not found" in lower or "failed" in lower

    def test_popen_oserror_returns_false_not_raise(self):
        """Generic OSError from subprocess.Popen must also be handled."""
        mock_engine = MagicMock()
        mock_engine.is_installed.return_value = True
        extra = [
            patch("vllm_mlx.dashboard.server_manager.get_engine", return_value=mock_engine),
            patch.object(sm, "_build_command", return_value=["bad-binary"]),
            patch.object(sm, "_build_env", return_value=None),
            patch.object(sm, "_build_cwd", return_value=None),
            patch("subprocess.Popen", side_effect=OSError("permission denied")),
        ]
        try:
            ok, msg = _start_with_patches(extra)
        except OSError:
            pytest.fail("OSError escaped from start_server() Popen path")

        assert ok is False
