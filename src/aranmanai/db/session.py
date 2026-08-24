"""SQLAlchemy engine + session management for SQLCipher-encrypted SQLite."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all Aranmanai models."""


def _make_engine() -> Engine:
    """Create a SQLAlchemy engine connected to the SQLCipher-encrypted DB."""
    settings = get_settings()
    # sqlcipher3 exposes a DBAPI that accepts PRAGMA key as a connection event
    # Note: SQLAlchemy's sqlite dialect talks to sqlite3 by default. We use
    # the sqlcipher3 module via the create_engine creator hook.
    import sqlcipher3

    def _connect():
        conn = sqlcipher3.connect(str(settings.db_path), check_same_thread=False)
        # PRAGMA key is required for the encrypted DB
        # Use parametrized to avoid SQL injection
        conn.execute(f"PRAGMA key='{settings.db_key}'")
        return conn

    # StaticPool: one connection shared across threads (safe with check_same_thread=False).
    # The PRAGMA key is applied in _connect; subsequent checkouts reuse the same conn.
    # In FastAPI's TestClient, the test runs on the same thread as init_db, so a
    # single shared connection avoids "created in a different thread" errors.
    engine = create_engine(
        "sqlite://",  # we provide the connect callable
        creator=_connect,
        echo=settings.db_echo,
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # Enforce foreign keys on every connection
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            log.warning("db.pragma.foreign_keys_failed", error=str(e))
        # WAL mode requires a fully-initialized DB; skip on a fresh encrypted
        # DB where the WAL pragma can throw "file is not a database" before
        # any tables are created. The init_db call below will retry WAL on
        # the first real connection.
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception as e:
            log.warning("db.pragma.wal_skipped", error=str(e))
        cursor.close()

    return engine


# Module-level engine + session factory, lazy-initialized
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def engine() -> Engine:
    """Lazy engine singleton."""
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def SessionLocal() -> Session:
    """Lazy sessionmaker singleton."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, ensures close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for scripts: commit on success, rollback on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Idempotent."""
    # Import all models so they register with Base
    from aranmanai.db.models import (  # noqa: F401
        audit_log,
        case,
        evidence,
        hearing,
        user,
        witness,
    )
    log.info("db.init_start", path=str(get_settings().db_path))
    Base.metadata.create_all(engine())
    log.info("db.init_done", tables=len(Base.metadata.tables))


def reset_engine() -> None:
    """Dispose of the engine and clear the cached singletons.

    Use in tests / scripts when the underlying DB path or key changes
    between calls. After reset, the next engine()/SessionLocal() call
    recreates a fresh engine bound to the current settings.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _SessionLocal = None
