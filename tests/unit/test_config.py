"""Unit tests for config + settings."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

# A durable (non-OS-temp) audit path value for tests that construct
# Settings under `environment=production`, where the M-3 validator forbids
# temp-dir audit logs. Used only as a value (these tests build Settings
# directly and never write to disk), so nothing is created here.
_DURABLE_AUDIT_PATH = Path("data/_test_prod/audit.log")

# Secrets satisfying the db_key / jwt_secret validators (>=32 chars).
_TEST_SECRET_32 = "test-key-32-chars-aaaaaaaaaaaaaa"


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


def test_settings_is_production():
    # Constructed directly (not via get_settings/ensure_dirs) so this
    # touches no filesystem. Under production the M-3 validator forbids a
    # temp-dir audit log, so use a durable path.
    from aranmanai.config.settings import Settings

    s = Settings(
        _env_file=None,
        environment="production",
        db_key=_TEST_SECRET_32,
        jwt_secret=_TEST_SECRET_32,
        audit_log_path=_DURABLE_AUDIT_PATH,
    )
    assert s.is_production() is True


def test_audit_log_path_rejected_under_temp_in_production():
    """M-3: production must refuse an audit log under the OS temp dir."""
    from aranmanai.config.settings import Settings

    temp_audit = Path(tempfile.gettempdir()) / "aranmanai-evil" / "audit.log"
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            environment="production",
            db_key=_TEST_SECRET_32,
            jwt_secret=_TEST_SECRET_32,
            audit_log_path=temp_audit,
        )
    assert "temp" in str(exc_info.value).lower()


def test_audit_log_path_allowed_under_temp_in_development():
    """M-3: the temp-dir ban is production-only — dev/test may use temp
    (the hermetic suite isolates every run under the OS temp dir)."""
    from aranmanai.config.settings import Settings

    temp_audit = Path(tempfile.gettempdir()) / "aranmanai-dev" / "audit.log"
    s = Settings(
        _env_file=None,
        environment="development",
        db_key=_TEST_SECRET_32,
        jwt_secret=_TEST_SECRET_32,
        audit_log_path=temp_audit,
    )
    # Stored resolved (absolute), and under the temp root — allowed in dev.
    assert s.audit_log_path.is_absolute()


def test_ensure_dirs_probes_audit_writability(tmp_env, monkeypatch):
    """M-3: ensure_dirs() raises if the audit log dir isn't writable."""
    import os as _os

    from aranmanai.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    s.ensure_dirs()  # baseline: writable temp dir, must not raise

    # Force the writability probe to fail and confirm it raises clearly.
    monkeypatch.setattr(_os, "access", lambda *a, **k: False)
    with pytest.raises(RuntimeError) as exc_info:
        s.ensure_dirs()
    assert "not writable" in str(exc_info.value).lower()


def test_llm_backend_validation(tmp_env, monkeypatch):
    monkeypatch.setenv("ARANMANAI_LLM_BACKEND", "invalid_value")
    from aranmanai.config import get_settings
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
