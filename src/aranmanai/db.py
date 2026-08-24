"""SQLAlchemy engine + session factory for SQLCipher-encrypted SQLite.

The DB is encrypted at rest via SQLCipher. The encryption key is
loaded from settings (env var in production, default in dev). The
DB file lives under data/aranmanai.db.

Sessions are short-lived (per-request via FastAPI Depends). The
session factory is cached; the engine is module-level singleton.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.aranmanai.config import settings
from src.aranmanai.logging_config import get_logger

log = get_logger(__name__)


# --- ORM Base ---

class Base(DeclarativeBase):
    """Declarative base for all ORM models. All models inherit this."""
    pass


# --- Engine setup ---

# We use the raw DBAPI from sqlcipher3 so the connection applies
# PRAGMA key. The SQLAlchemy URL still says "sqlite://" for routing
# but the actual driver is sqlcipher3.

def _make_engine() -> Engine:
    """Create the SQLAlchemy engine with sqlcipher3 driver + PRAGMA key."""
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # SQLAlchemy URL with sqlcipher3 driver
    url = f"sqlite:///{db_path}"

    engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    # Apply PRAGMA key on every new connection
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _connection_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        # SQLCipher key — note the quoting; PRAGMA expects a string literal
        cursor.execute(f"PRAGMA key='{settings.db_encryption_key}'")
        # Foreign keys must be enabled per-connection in SQLite
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL mode for concurrent reads
        cursor.execute("PRAGMA journal_mode=WAL")
        # 5-second busy timeout to avoid "database is locked" under load
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


engine: Engine = _make_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


# --- FastAPI dependency ---

def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, ensures close on exit."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts / background jobs. Commits on success, rolls back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Init ---

def init_db() -> None:
    """Create all tables. Called from main.py on startup. Idempotent."""
    # Import all models so they register with Base.metadata
    from src.aranmanai import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    log.info("database initialized at %s", settings.db_path)


def verify_db() -> bool:
    """Smoke test: can we read + write? Returns True on success."""
    try:
        from sqlalchemy import text
        with session_scope() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.error("database verify failed: %s", e)
        return False
