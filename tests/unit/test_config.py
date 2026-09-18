"""Unit tests for smp.core.config Settings and config validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from smp.core.config import Settings


class TestSettingsDefaults:
    """Tests for default Settings values."""

    def test_default_graph_path(self) -> None:
        settings = Settings()
        assert settings.graph_path == ".smp/graph.smpg"

    def test_default_vector_path(self) -> None:
        settings = Settings()
        assert settings.vector_path == ".smp/smp.smpv"

    def test_default_host(self) -> None:
        settings = Settings()
        assert settings.host == "0.0.0.0"

    def test_default_port(self) -> None:
        settings = Settings()
        assert settings.port == 8420

    def test_all_defaults_together(self) -> None:
        settings = Settings()
        assert settings.graph_path == ".smp/graph.smpg"
        assert settings.vector_path == ".smp/smp.smpv"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8420


class TestSettingsFromEnv:
    """Tests for Settings.from_env() method."""

    def test_from_env_returns_settings_instance(self) -> None:
        result = Settings.from_env()
        assert isinstance(result, Settings)

    @patch.dict(os.environ, {}, clear=True)
    def test_from_env_uses_defaults_when_no_env_vars(self) -> None:
        result = Settings.from_env()
        assert result.graph_path == ".smp/graph.smpg"
        assert result.vector_path == ".smp/smp.smpv"
        assert result.host == "0.0.0.0"
        assert result.port == 8420


class TestSettingsEnvOverrides:
    """Tests for environment variable overrides."""

    @patch.dict(os.environ, {"SMP_GRAPH_PATH": "/custom/graph.db"}, clear=True)
    def test_override_graph_path(self) -> None:
        result = Settings.from_env()
        assert result.graph_path == "/custom/graph.db"

    @patch.dict(os.environ, {"SMP_VECTOR_PATH": "/custom/vectors.db"}, clear=True)
    def test_override_vector_path(self) -> None:
        result = Settings.from_env()
        assert result.vector_path == "/custom/vectors.db"

    @patch.dict(os.environ, {"SMP_HOST": "127.0.0.1"}, clear=True)
    def test_override_host(self) -> None:
        result = Settings.from_env()
        assert result.host == "127.0.0.1"

    @patch.dict(os.environ, {"SMP_PORT": "9000"}, clear=True)
    def test_override_port_with_valid_int(self) -> None:
        result = Settings.from_env()
        assert result.port == 9000

    @patch.dict(os.environ, {"SMP_PORT": "8080"}, clear=True)
    def test_override_port_with_another_valid_int(self) -> None:
        result = Settings.from_env()
        assert result.port == 8080


class TestSettingsPortValidation:
    """Tests for port number validation."""

    @patch.dict(os.environ, {"SMP_PORT": "invalid"}, clear=True)
    def test_invalid_port_falls_back_to_default(self) -> None:
        result = Settings.from_env()
        assert result.port == 8420

    @patch.dict(os.environ, {"SMP_PORT": ""}, clear=True)
    def test_empty_port_string_uses_default(self) -> None:
        result = Settings.from_env()
        assert result.port == 8420

    @patch.dict(os.environ, {"SMP_PORT": "0"}, clear=True)
    def test_port_zero_is_valid(self) -> None:
        result = Settings.from_env()
        assert result.port == 0

    @patch.dict(os.environ, {"SMP_PORT": "65535"}, clear=True)
    def test_port_max_valid(self) -> None:
        result = Settings.from_env()
        assert result.port == 65535


class TestSettingsMultipleOverrides:
    """Tests for multiple environment variable overrides."""

    @patch.dict(
        os.environ,
        {
            "SMP_GRAPH_PATH": "/data/graph.smpg",
            "SMP_VECTOR_PATH": "/data/vectors.smpv",
            "SMP_HOST": "localhost",
            "SMP_PORT": "3000",
        },
        clear=True,
    )
    def test_all_overrides_applied_together(self) -> None:
        result = Settings.from_env()
        assert result.graph_path == "/data/graph.smpg"
        assert result.vector_path == "/data/vectors.smpv"
        assert result.host == "localhost"
        assert result.port == 3000


class TestSettingsEquality:
    """Tests for Settings equality comparison."""

    def test_equal_settings_are_equal(self) -> None:
        settings1 = Settings()
        settings2 = Settings()
        assert settings1 == settings2

    def test_different_graph_path_not_equal(self) -> None:
        settings1 = Settings(graph_path="/path/a")
        settings2 = Settings(graph_path="/path/b")
        assert settings1 != settings2

    def test_different_vector_path_not_equal(self) -> None:
        settings1 = Settings(vector_path="/path/a")
        settings2 = Settings(vector_path="/path/b")
        assert settings1 != settings2

    def test_different_host_not_equal(self) -> None:
        settings1 = Settings(host="127.0.0.1")
        settings2 = Settings(host="0.0.0.0")
        assert settings1 != settings2

    def test_different_port_not_equal(self) -> None:
        settings1 = Settings(port=8000)
        settings2 = Settings(port=9000)
        assert settings1 != settings2


class TestSettingsImmutability:
    """Tests for Settings immutability (frozen=True)."""

    def test_settings_is_frozen(self) -> None:
        settings = Settings()
        with pytest.raises(AttributeError):
            settings.graph_path = "/new/path"

    def test_settings_is_frozen_vector_path(self) -> None:
        settings = Settings()
        with pytest.raises(AttributeError):
            settings.vector_path = "/new/path"

    def test_settings_is_frozen_host(self) -> None:
        settings = Settings()
        with pytest.raises(AttributeError):
            settings.host = "localhost"

    def test_settings_is_frozen_port(self) -> None:
        settings = Settings()
        with pytest.raises(AttributeError):
            settings.port = 9000


class TestSettingsRepr:
    """Tests for Settings string representation."""

    def test_repr_contains_all_fields(self) -> None:
        settings = Settings()
        repr_str = repr(settings)
        assert "graph_path" in repr_str
        assert "vector_path" in repr_str
        assert "host" in repr_str
        assert "port" in repr_str

    def test_repr_shows_default_values(self) -> None:
        settings = Settings()
        repr_str = repr(settings)
        assert ".smp/graph.smpg" in repr_str
        assert "8420" in repr_str
