"""Unit tests for config + settings."""
from __future__ import annotations

import pytest


def test_settings_loads_with_defaults(tmp_env):
    from aranmanai.config import get_settings
    s = get_settings()
    assert s.app_name == "Aranmanai"
    assert s.version == "0.1.0"
    assert s.environment in ("development", "staging", "production")


def test_settings_caches_singleton(tmp_env):
    from aranmanai.config import get_settings
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_env_override(tmp_env, monkeypatch):
    monkeypatch.setenv("ARANMANAI_PORT", "9999")
    from aranmanai.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.port == 9999


def test_settings_ensure_dirs(tmp_env):
    from aranmanai.config import get_settings
    s = get_settings()
    s.ensure_dirs()
    assert s.db_path.parent.exists()
    assert s.chroma_persist_dir.exists()
    assert s.audit_log_path.parent.exists()


def test_settings_is_production(tmp_env, monkeypatch):
    monkeypatch.setenv("ARANMANAI_ENVIRONMENT", "production")
    from aranmanai.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.is_production() is True


def test_llm_backend_validation(tmp_env, monkeypatch):
    monkeypatch.setenv("ARANMANAI_LLM_BACKEND", "invalid_value")
    from aranmanai.config import get_settings
    get_settings.cache_clear()
    with pytest.raises(Exception):  # pydantic validation error
        get_settings()
