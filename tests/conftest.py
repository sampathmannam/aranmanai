"""Pytest fixtures: minimal + working.

Each test that needs the client gets a fresh test client + fresh DB
schema. The DB is bound to a single test session file, with drop_all
+ create_all run between tests under a lock.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient


# Set env vars ONCE at conftest import time, before any src.aranmanai.* import.
_TEST_TMP = Path(tempfile.mkdtemp(prefix="aranmanai_session_"))
(_TEST_TMP / "data").mkdir()
os.environ.setdefault("DATA_DIR", str(_TEST_TMP / "data"))
os.environ.setdefault("DB_PATH", str(_TEST_TMP / "data" / "aranmanai.db"))
os.environ.setdefault("CHROMA_DIR", str(_TEST_TMP / "data" / "chroma"))
os.environ.setdefault("MODELS_DIR", str(_TEST_TMP / "models"))
os.environ.setdefault("BACKUPS_DIR", str(_TEST_TMP / "data" / "backups"))
os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("CCTNS_MODE", "mock")
os.environ.setdefault("ESAKSHYA_MODE", "mock")
os.environ.setdefault("ICJS_MODE", "mock")


@pytest.fixture()
def temp_dir() -> Generator[Path, None, None]:
    """Backwards-compat fixture: returns the session test tmp dir.
    Tests that need isolation should use the `client` fixture which
    drops + recreates the schema per-test."""
    yield _TEST_TMP


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Fresh test client per test. Drops + recreates the schema.
    Cleans up the engine connection on teardown so the next test
    can open the file fresh."""
    from src.aranmanai import db as dbmod
    from src.aranmanai.db import Base
    from src.aranmanai import models  # noqa: F401

    # Wipe any prior test's data
    dbmod.engine.dispose()
    Base.metadata.drop_all(bind=dbmod.engine)
    Base.metadata.create_all(bind=dbmod.engine)

    from src.aranmanai.main import app
    with TestClient(app) as c:
        yield c

    # Teardown: dispose so the next test gets a clean file handle
    dbmod.engine.dispose()


@pytest.fixture()
def admin_token(client) -> str:
    """Bootstrap admin user via direct DB write, then login via API."""
    from src.aranmanai import db as dbmod
    from src.aranmanai.models import User
    from src.aranmanai.security import hash_password
    pwd_hash = hash_password("adminpass123")
    with dbmod.session_scope() as db:
        existing = db.query(User).filter(User.name == "admin").first()
        if existing is None:
            db.add(User(
                name="admin", role="Admin", district="Vellore", password_hash=pwd_hash,
            ))
    r = client.post("/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}
