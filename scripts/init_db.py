"""Initialize the database (create all tables) and seed the first admin user.

Run once on first install:
    python scripts/init_db.py

This is idempotent: safe to re-run.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aranmanai.config import get_settings
from aranmanai.db import SessionLocal, init_db
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger, setup_logging
from aranmanai.security import encrypt_field, hash_password

log = get_logger(__name__)


def ensure_admin(db) -> str:
    """Create the bootstrap admin if no users exist. Returns username."""
    existing = db.query(User).count()
    if existing > 0:
        log.info("init_db.admin_skipped", users=existing)
        return ""
    settings = get_settings()
    admin_username = "admin"
    admin_password = "Aranmanai!Dev!2026"  # CHANGE IN PRODUCTION
    admin = User(
        username=admin_username,
        hashed_password=hash_password(admin_password),
        name_encrypted=encrypt_field("Bootstrap Admin"),
        role=UserRole.ADMIN,
        district=settings.district,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    log.warning(
        "init_db.admin_created",
        username=admin_username,
        default_password=admin_password,
        msg="CHANGE THIS PASSWORD IMMEDIATELY",
    )
    return admin_username


def main() -> None:
    setup_logging()
    settings = get_settings()
    settings.ensure_dirs()
    log.info("init_db.start", db_path=str(settings.db_path))
    init_db()
    db = SessionLocal()
    try:
        admin = ensure_admin(db)
        if admin:
            print("\n*** Bootstrap admin created ***")
            print(f"    username: {admin}")
            print("    password: Aranmanai!Dev!2026  (CHANGE IMMEDIATELY)")
            print(f"    district: {settings.district}\n")
    finally:
        db.close()
    log.info("init_db.done")


if __name__ == "__main__":
    main()
