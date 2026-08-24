"""Pytest fixtures: temp DB, mock LLM, test client."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(scope="function")
def tmp_env(monkeypatch) -> Iterator[Path]:
    """Set up a clean temp dir as the data dir. Use ARANMANAI_DB_KEY
    with a fixed dev key so the DB is deterministic across tests.
    """
    tmp = Path(tempfile.mkdtemp(prefix="aranmanai-test-"))
    monkeypatch.setenv("ARANMANAI_DB_PATH", str(tmp / "test.db"))
    monkeypatch.setenv("ARANMANAI_DB_KEY", "test-key-32-chars-aaaaaaaaaaaaaa")
    monkeypatch.setenv("ARANMANAI_LLM_BACKEND", "mock")
    monkeypatch.setenv("ARANMANAI_LLM_MODEL_PATH", str(tmp / "model.gguf"))
    monkeypatch.setenv("ARANMANAI_AUDIT_LOG_PATH", str(tmp / "audit.log"))
    monkeypatch.setenv("ARANMANAI_CHROMA_PERSIST_DIR", str(tmp / "chroma"))
    monkeypatch.setenv("ARANMANAI_MOCK_CCTNS_DATA_DIR", str(tmp / "cctns"))
    monkeypatch.setenv("ARANMANAI_MOCK_ESAKSHYA_DATA_DIR", str(tmp / "esakshya"))
    monkeypatch.setenv("ARANMANAI_MOCK_ICJS_DATA_DIR", str(tmp / "icjs"))
    monkeypatch.setenv("ARANMANAI_LOG_FILE", "")
    monkeypatch.setenv("ARANMANAI_LOG_FORMAT", "text")
    # Clear the cached settings to pick up env changes
    from aranmanai.config.settings import get_settings
    get_settings.cache_clear()
    # Also reset the cached DB engine so each test gets a fresh engine
    # bound to the new tmp db path.
    from aranmanai.db.session import reset_engine
    reset_engine()
    try:
        yield tmp
    finally:
        reset_engine()
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="function")
def db_session(tmp_env) -> Iterator:
    """Initialize the DB and yield a session. Use this in any test that
    needs the database.
    """
    from aranmanai.db import init_db, SessionLocal
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_user(db_session) -> "User":  # type: ignore[name-defined]
    """Create a test admin user."""
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import hash_password, encrypt_field
    user = User(
        username="test_admin",
        hashed_password=hash_password("test_password_123"),
        name_encrypted=encrypt_field("Test Admin"),
        role=UserRole.ADMIN,
        district="test-district",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_token(test_user) -> str:
    """Generate a JWT for the test_user."""
    from aranmanai.security import generate_token
    return generate_token(test_user.id, {"role": test_user.role.value, "district": test_user.district})


@pytest.fixture
def client(tmp_env, test_user, auth_token) -> Iterator:
    """FastAPI TestClient with auth token pre-set."""
    from fastapi.testclient import TestClient
    from aranmanai.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth_token}"
        yield c
