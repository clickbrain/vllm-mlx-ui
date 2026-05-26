# SPDX-License-Identifier: Apache-2.0
"""Tests for Ds4M5Engine adapter and model version checking."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from vllm_mlx.dashboard.engines.base import BaseEngine
from vllm_mlx.dashboard.engines.ds4_m5 import Ds4M5Engine

GGUF_DIR = "/fake/gguf"


class _FakeEngine(BaseEngine):
    """Minimal concrete BaseEngine subclass for testing default methods."""
    id = "test"
    name = "Test"
    capabilities = frozenset()

    def build_command(self, config):
        return []

    def is_installed(self):
        return False

    def get_version(self):
        return None


@pytest.fixture
def engine():
    return Ds4M5Engine()


# ── BaseEngine.get_discovered_models() ────────────────────────────────


class TestBaseEngineGetDiscoveredModels:
    def test_returns_empty_list_by_default(self):
        """BaseEngine returns [] for get_discovered_models()."""
        e = _FakeEngine()
        assert e.get_discovered_models() == []


# ── Ds4M5Engine.get_discovered_models() ────────────────────────────────


class TestGetDiscoveredModels:
    @patch("vllm_mlx.dashboard.engines.ds4_m5._gguf_dir")
    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_no_gguf_dir(self, mock_listdir, mock_isdir, mock_dir, engine):
        mock_dir.return_value = GGUF_DIR
        mock_isdir.return_value = False

        result = engine.get_discovered_models()
        assert result == []
        mock_listdir.assert_not_called()

    @patch("vllm_mlx.dashboard.engines.ds4_m5._gguf_dir")
    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("os.path.getsize")
    def test_single_gguf(self, mock_size, mock_listdir, mock_isdir, mock_dir, engine):
        mock_dir.return_value = GGUF_DIR
        mock_isdir.return_value = True
        mock_listdir.return_value = ["DeepSeek-V4-Flash-Q2-imatrix.gguf"]
        mock_size.return_value = 85 * 1024 ** 3

        result = engine.get_discovered_models()

        assert len(result) == 1
        item = result[0]
        assert item["id"] == "ds4:DeepSeek-V4-Flash-Q2-imatrix.gguf"
        assert item["name"] == "DeepSeek-V4-Flash-Q2-imatrix.gguf"
        assert item["path"] == f"{GGUF_DIR}/DeepSeek-V4-Flash-Q2-imatrix.gguf"
        assert item["size_gb"] == 85.0
        assert item["engine"] == "ds4-m5"
        assert item["cached"] is True

    @patch("vllm_mlx.dashboard.engines.ds4_m5._gguf_dir")
    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("os.path.getsize")
    def test_multiple_gguf_picks_first_sorted(self, mock_size, mock_listdir, mock_isdir, mock_dir, engine):
        mock_dir.return_value = GGUF_DIR
        mock_isdir.return_value = True
        mock_listdir.return_value = [
            "DeepSeek-V4-Flash-Q4-imatrix.gguf",
            "DeepSeek-V4-Flash-Q2-imatrix.gguf",
        ]
        mock_size.return_value = 85 * 1024 ** 3

        result = engine.get_discovered_models()

        assert len(result) == 1
        assert "Q2-imatrix" in result[0]["id"]

    @patch("vllm_mlx.dashboard.engines.ds4_m5._gguf_dir")
    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("os.path.getsize")
    def test_stat_failure_returns_size_zero(self, mock_size, mock_listdir, mock_isdir, mock_dir, engine):
        mock_dir.return_value = GGUF_DIR
        mock_isdir.return_value = True
        mock_listdir.return_value = ["model.gguf"]
        mock_size.side_effect = OSError("Permission denied")

        result = engine.get_discovered_models()

        assert len(result) == 1
        assert result[0]["size_gb"] == 0.0

    @patch("vllm_mlx.dashboard.engines.ds4_m5._gguf_dir")
    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_no_gguf_files_in_dir(self, mock_listdir, mock_isdir, mock_dir, engine):
        mock_dir.return_value = GGUF_DIR
        mock_isdir.return_value = True
        mock_listdir.return_value = ["readme.md", "config.json"]

        result = engine.get_discovered_models()
        assert result == []


# ── Ds4M5Engine._model_get_version() ────────────────────────────────────


class TestModelGetVersion:
    GGUF_PATH = f"{GGUF_DIR}/model.gguf"

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._find_gguf")
    def test_none_when_no_gguf(self, mock_find, engine):
        mock_find.return_value = None
        assert engine._model_get_version() is None

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._get_stored_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._find_gguf")
    @patch("os.path.getmtime")
    def test_returns_date_string(self, mock_mtime, mock_find, mock_stored, engine):
        mock_stored.return_value = {}
        mock_find.return_value = self.GGUF_PATH
        mock_mtime.return_value = 1747000000.0

        result = engine._model_get_version()
        assert result is not None
        assert len(result) == 10
        assert result.count("-") == 2

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._get_stored_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._find_gguf")
    @patch("os.path.getmtime")
    def test_oserror_returns_none(self, mock_mtime, mock_find, mock_stored, engine):
        mock_stored.return_value = {}
        mock_find.return_value = self.GGUF_PATH
        mock_mtime.side_effect = OSError("Bad file descriptor")

        assert engine._model_get_version() is None


# ── Ds4M5Engine.hf_model_latest() ───────────────────────────────────────


class TestHfModelLatest:
    @patch("urllib.request.urlopen")
    def test_returns_date_from_last_modified(self, mock_urlopen, engine):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "lastModified": "2025-06-15T10:30:00Z",
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = engine.hf_model_latest()
        assert result == "2025-06-15"

    @patch("urllib.request.urlopen")
    def test_returns_none_on_network_error(self, mock_urlopen, engine):
        mock_urlopen.side_effect = Exception("Network error")
        assert engine.hf_model_latest() is None

    @patch("vllm_mlx.dashboard.engines.ds4_m5._MODEL_HF_REPO", "")
    def test_returns_none_when_no_repo_configured(self, engine):
        assert engine.hf_model_latest() is None


# ── Ds4M5Engine.model_update_available() ────────────────────────────────


class TestModelUpdateAvailable:
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._model_get_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine.hf_model_latest")
    def test_true_when_newer_available(self, mock_latest, mock_installed, engine):
        mock_installed.return_value = "2025-01-01"
        mock_latest.return_value = "2025-06-15"
        assert engine.model_update_available() is True

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._model_get_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine.hf_model_latest")
    def test_false_when_same_version(self, mock_latest, mock_installed, engine):
        mock_installed.return_value = "2025-06-15"
        mock_latest.return_value = "2025-06-15"
        assert engine.model_update_available() is False

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._model_get_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine.hf_model_latest")
    def test_false_when_installed_newer(self, mock_latest, mock_installed, engine):
        mock_installed.return_value = "2025-12-01"
        mock_latest.return_value = "2025-06-15"
        assert engine.model_update_available() is False

    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine._model_get_version")
    @patch("vllm_mlx.dashboard.engines.ds4_m5.Ds4M5Engine.hf_model_latest")
    def test_false_when_either_version_missing(self, mock_latest, mock_installed, engine):
        mock_installed.return_value = None
        mock_latest.return_value = "2025-06-15"
        assert engine.model_update_available() is False

        mock_installed.return_value = "2025-01-01"
        mock_latest.return_value = None
        assert engine.model_update_available() is False


# ── Ds4M5Engine.model_upgrade_command() ─────────────────────────────────


class TestModelUpgradeCommand:
    @patch("vllm_mlx.dashboard.engines.ds4_m5._ds4_dir")
    @patch("os.path.isfile")
    def test_returns_command_when_script_found(self, mock_isfile, mock_dir, engine):
        mock_dir.return_value = "/fake/ds4"
        mock_isfile.side_effect = lambda p: p == "/fake/ds4/download_model.sh"

        cmd = engine.model_upgrade_command()
        assert cmd is not None
        cmd_str = " ".join(cmd)
        assert "download_model.sh" in cmd_str
        assert "q2-imatrix" in cmd_str or "q4-imatrix" in cmd_str

    @patch("vllm_mlx.dashboard.engines.ds4_m5._ds4_dir")
    @patch("os.path.isfile")
    def test_returns_none_when_script_not_found(self, mock_isfile, mock_dir, engine):
        mock_dir.return_value = "/fake/ds4"
        mock_isfile.return_value = False

        assert engine.model_upgrade_command() is None
