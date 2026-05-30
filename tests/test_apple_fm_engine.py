# SPDX-License-Identifier: Apache-2.0
"""Tests for AppleFMEngine adapter."""

import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from vllm_mlx.dashboard.engines.apple_fm import AppleFMEngine


@pytest.fixture
def engine():
    return AppleFMEngine()


# ── Identity & metadata ────────────────────────────────────────────────────────


class TestIdentity:
    def test_id(self, engine):
        assert engine.id == "apple-fm"

    def test_name_mentions_apple(self, engine):
        assert "Apple" in engine.name or "apple" in engine.name.lower()

    def test_install_method_is_brew(self, engine):
        # apple-fm runs a real local process (apfel serve) — install_method must
        # be "brew" so start_server() actually spawns the process.
        assert engine.install_method == "brew"

    def test_capabilities_include_tool_calls(self, engine):
        assert "tool_calls" in engine.capabilities

    def test_release_url_is_github(self, engine):
        assert "github.com" in engine.release_url


# ── build_command ─────────────────────────────────────────────────────────────


class TestBuildCommand:
    def test_uses_apfel_binary(self, engine):
        cmd = engine.build_command({"host": "127.0.0.1", "port": 8080})
        import os
        assert os.path.basename(cmd[0]) == "apfel"

    def test_includes_serve_flag(self, engine):
        # Must be --serve (flag), NOT "serve" (positional arg / chat prompt).
        cmd = engine.build_command({"host": "127.0.0.1", "port": 8080})
        assert "--serve" in cmd
        assert "serve" not in cmd  # bare positional would be passed as a chat prompt

    def test_passes_host(self, engine):
        cmd = engine.build_command({"host": "0.0.0.0", "port": 8080})
        assert "--host" in cmd
        idx = cmd.index("--host")
        assert cmd[idx + 1] == "0.0.0.0"

    def test_passes_port_as_string(self, engine):
        cmd = engine.build_command({"host": "127.0.0.1", "port": 9999})
        assert "--port" in cmd
        idx = cmd.index("--port")
        assert cmd[idx + 1] == "9999"

    def test_default_host_and_port(self, engine):
        """build_command with empty config should fall back to defaults."""
        cmd = engine.build_command({})
        assert "--host" in cmd
        assert "--port" in cmd


# ── is_installed ──────────────────────────────────────────────────────────────


class TestIsInstalled:
    def test_true_when_apfel_on_path(self, engine):
        with patch("shutil.which", return_value="/usr/local/bin/apfel"):
            assert engine.is_installed() is True

    def test_false_when_apfel_not_on_path(self, engine):
        with patch("shutil.which", return_value=None):
            assert engine.is_installed() is False


# ── get_version ───────────────────────────────────────────────────────────────


class TestGetVersion:
    def test_parses_version_from_stdout(self, engine):
        mock = MagicMock()
        mock.stdout = "apfel version 0.3.1\n"
        mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            assert engine.get_version() == "0.3.1"

    def test_parses_version_from_stderr(self, engine):
        mock = MagicMock()
        mock.stdout = ""
        mock.stderr = "apfel 1.0.0-beta"
        with patch("subprocess.run", return_value=mock):
            assert engine.get_version() == "1.0.0"

    def test_returns_none_on_exception(self, engine):
        with patch("subprocess.run", side_effect=FileNotFoundError("apfel not found")):
            assert engine.get_version() is None

    def test_returns_none_when_no_version_in_output(self, engine):
        mock = MagicMock()
        mock.stdout = "no version here"
        mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            assert engine.get_version() is None


# ── latest_version ────────────────────────────────────────────────────────────


class TestLatestVersion:
    def test_parses_tag_name(self, engine):
        import json
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"tag_name": "v1.2.3"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert engine.latest_version() == "1.2.3"

    def test_strips_v_prefix(self, engine):
        import json
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"tag_name": "v0.9.0"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert engine.latest_version() == "0.9.0"

    def test_returns_none_on_network_error(self, engine):
        with patch("urllib.request.urlopen", side_effect=OSError("network error")):
            assert engine.latest_version() is None


# ── install / uninstall / upgrade commands ───────────────────────────────────


class TestInstallCommands:
    def test_install_command_uses_brew(self, engine):
        cmd = engine.install_command()
        assert "brew" in cmd

    def test_upgrade_command_uses_brew_when_available(self, engine):
        with patch("shutil.which", return_value="/usr/local/bin/brew"):
            cmd = engine.upgrade_command()
        assert cmd is not None
        assert "brew" in cmd

    def test_upgrade_command_none_when_brew_missing(self, engine):
        with patch("shutil.which", return_value=None):
            cmd = engine.upgrade_command()
        assert cmd is None

    def test_uninstall_command_when_apfel_present(self, engine):
        with patch("shutil.which", return_value="/usr/local/bin/apfel"):
            cmd = engine.uninstall_command()
        assert "brew" in cmd and "uninstall" in cmd

    def test_uninstall_raises_when_apfel_missing(self, engine):
        with patch("shutil.which", return_value=None):
            with pytest.raises(NotImplementedError):
                engine.uninstall_command()


# ── get_fixed_model_display ───────────────────────────────────────────────────


class TestFixedModelDisplay:
    def test_returns_string(self, engine):
        result = engine.get_fixed_model_display()
        assert isinstance(result, str) and len(result) > 0

    def test_mentions_apple_or_ondevice(self, engine):
        result = engine.get_fixed_model_display().lower()
        assert "apple" in result or "on-device" in result or "3b" in result.lower()


# ── validate_model_id ─────────────────────────────────────────────────────────


class TestValidateModelId:
    def test_accepts_any_model_id(self, engine):
        """Apple FM only serves a single model — any model ID is valid."""
        for model in ["gpt-4", "llama-3", "apple/afm", ""]:
            assert engine.validate_model_id(model) is True


# ── get_discovered_models ─────────────────────────────────────────────────────


class TestGetDiscoveredModels:
    def test_returns_empty_list(self, engine):
        """Apple FM has a single fixed model — no discovery."""
        assert engine.get_discovered_models() == []


# ── check_requirements ────────────────────────────────────────────────────────


class TestCheckRequirements:
    def test_fails_on_non_arm(self, engine):
        with patch("platform.machine", return_value="x86_64"):
            issues = engine.check_requirements()
        assert any("Apple Silicon" in i or "M1" in i or "ARM" in i for i in issues)

    def test_no_error_on_arm64(self, engine):
        with (
            patch("platform.machine", return_value="arm64"),
            patch("platform.mac_ver", return_value=("26.0", ("", "", ""), "")),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            issues = engine.check_requirements()
        assert not any("Apple Silicon" in i for i in issues)

    def test_fails_on_macos_below_26(self, engine):
        with (
            patch("platform.machine", return_value="arm64"),
            patch("platform.mac_ver", return_value=("15.4", ("", "", ""), "")),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            issues = engine.check_requirements()
        assert any("26" in i or "macOS" in i for i in issues)
