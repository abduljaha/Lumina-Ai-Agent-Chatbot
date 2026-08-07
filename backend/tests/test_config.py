"""Tests for the configuration system."""
from __future__ import annotations

from app.core.config import get_settings


def test_settings_defaults() -> None:
    """Test that settings have sensible defaults."""
    settings = get_settings()
    assert settings.app_name == "Lumina AI"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.access_token_expire_minutes > 0
    assert settings.vector_db_type in ("faiss", "chroma")


def test_settings_cors_parsing() -> None:
    """Test CORS origins parsing."""
    settings = get_settings()
    assert isinstance(settings.cors_origins, list)
    assert len(settings.cors_origins) > 0


def test_settings_fallback_models() -> None:
    """Test fallback models is a list."""
    settings = get_settings()
    assert isinstance(settings.fallback_models, list)
