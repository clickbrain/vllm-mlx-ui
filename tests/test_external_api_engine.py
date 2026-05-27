# SPDX-License-Identifier: Apache-2.0
"""Tests for ExternalApiEngine adapter."""

import sys
from unittest.mock import patch

import pytest

from vllm_mlx.dashboard.engines.external_api import ExternalApiEngine


@pytest.fixture
def engine():
    return ExternalApiEngine()


# ── Identity & metadata ────────────────────────────────────────────────────────


class TestIdentity:
    def test_id(self, engine):
        assert engine.id == "openai-compatible"

    def test_name(self, engine):
        assert "OpenAI" in engine.name or "API" in engine.name

    def test_install_method_is_external(self, engine):
        assert engine.install_method == "external"

    def test_always_installed(self, engine):
        """is_installed() must always return True — there is no binary to check."""
        assert engine.is_installed() is True

    def test_version_string(self, engine):
        v = engine.get_version()
        assert v is not None and len(v) > 0

    def test_capabilities_include_tool_calls(self, engine):
        assert "tool_calls" in engine.capabilities


# ── build_command ─────────────────────────────────────────────────────────────


class TestBuildCommand:
    def test_returns_a_sleep_command(self, engine):
        """External API engine must return a no-op command (not a real server)."""
        cmd = engine.build_command({})
        assert isinstance(cmd, list)
        assert len(cmd) >= 1

    def test_command_is_python_based(self, engine):
        """The no-op command should use the current Python executable."""
        cmd = engine.build_command({})
        assert cmd[0] == sys.executable

    def test_build_command_ignores_config(self, engine):
        """build_command() must accept any config dict without raising."""
        cfg1 = {}
        cfg2 = {"model": "gpt-4o", "host": "0.0.0.0", "port": 8080}
        assert engine.build_command(cfg1) == engine.build_command(cfg2)


# ── config_schema ─────────────────────────────────────────────────────────────


class TestConfigSchema:
    def test_returns_list(self, engine):
        schema = engine.config_schema()
        assert isinstance(schema, list)

    def test_has_base_url_field(self, engine):
        keys = {f["key"] for f in engine.config_schema()}
        assert "base_url" in keys

    def test_has_api_key_field(self, engine):
        keys = {f["key"] for f in engine.config_schema()}
        assert "api_key" in keys

    def test_has_models_field(self, engine):
        keys = {f["key"] for f in engine.config_schema()}
        assert "models" in keys

    def test_base_url_default_is_openai(self, engine):
        schema = {f["key"]: f for f in engine.config_schema()}
        assert "openai.com" in schema["base_url"]["default"]

    def test_all_fields_have_type_str(self, engine):
        for field in engine.config_schema():
            assert field.get("type") == "str", f"Field {field['key']} type is not 'str'"


# ── default_engine_settings ────────────────────────────────────────────────────


class TestDefaultEngineSettings:
    def test_returns_dict(self, engine):
        assert isinstance(engine.default_engine_settings(), dict)

    def test_base_url_present(self, engine):
        settings = engine.default_engine_settings()
        assert "base_url" in settings

    def test_api_key_present_and_empty(self, engine):
        settings = engine.default_engine_settings()
        assert "api_key" in settings
        assert settings["api_key"] == ""

    def test_models_present(self, engine):
        settings = engine.default_engine_settings()
        assert "models" in settings

    def test_schema_keys_match_defaults(self, engine):
        """Every key in config_schema must have a matching default_engine_settings key."""
        schema_keys = {f["key"] for f in engine.config_schema()}
        default_keys = set(engine.default_engine_settings().keys())
        assert schema_keys == default_keys


# ── get_discovered_models ──────────────────────────────────────────────────────


class TestGetDiscoveredModels:
    def test_returns_list(self, engine):
        result = engine.get_discovered_models()
        assert isinstance(result, list)

    def test_returns_empty_list(self, engine):
        """External API has no local model discovery."""
        assert engine.get_discovered_models() == []
