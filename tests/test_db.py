"""Database engine, PRAGMA key, init, session_scope."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from src.aranmanai import db as dbmod
from src.aranmanai.db import engine, init_db, session_scope, verify_db


def test_init_db_creates_all_tables(temp_dir):
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert {"user", "case", "witness", "hearing", "evidence", "audit_log"} <= tables


def test_verify_db_returns_true_after_init(temp_dir):
    init_db()
    assert verify_db() is True


def test_session_scope_commits_on_success(temp_dir):
    from src.aranmanai.models import User
    init_db()
    with session_scope() as db:
        u = User(name="test_user", role="IO", district="Vellore", password_hash="x")
        db.add(u)
    # Read back
    with session_scope() as db:
        u = db.query(User).filter(User.name == "test_user").one()
        assert u.role == "IO"


def test_session_scope_rolls_back_on_error(temp_dir):
    from src.aranmanai.models import User
    init_db()
    with pytest.raises(RuntimeError):
        with session_scope() as db:
            u = User(name="rollback_user", role="IO", district="Vellore", password_hash="x")
            db.add(u)
            db.flush()
            raise RuntimeError("simulated failure")
    # Should not exist
    with session_scope() as db:
        u = db.query(User).filter(User.name == "rollback_user").one_or_none()
        assert u is None


def test_wal_mode_enabled(temp_dir):
    init_db()
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert result is not None
    assert str(result).lower() == "wal"
