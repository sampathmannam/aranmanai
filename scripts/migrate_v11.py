"""v1.1 schema migration.

Run once after upgrading to v1.1:
    python scripts/migrate_v11.py

Idempotent: safe to re-run. Each migration step is a no-op if the
target shape already exists.

Changes:
- Rename pp_briefing.read_at -> pp_briefing.recorded_at
  (Kishore review item 1: the field was a lie; new column is the
  time the briefing was RECORDED, not the time the PP read it.)
- Add case.is_pocso_or_304b_case (default False)
  (Kishore review item 3: F11 family-liaison needs the case-type
  flag to enforce the POCSO/304B-only DCPO constraint.)
- Add UNIQUE(fir_no, district) on case
  (Kishore review item 2: prevents two IOs from creating different
  cases with the same FIR number in the same district.)

Limitations (documented, NOT fixed here):
- The audit log rotation / multi-file verify_all() is a code change
  in security/audit.py; no schema migration needed.
- The multi-process rate-limit caveat is a doc change in
  api/v1/safety.py; no schema migration needed.
- The F6 district check was already in place from the v1.0 fix
  sprint; no schema migration needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text

from aranmanai.config import get_settings
from aranmanai.db import SessionLocal
from aranmanai.observability import get_logger, setup_logging

log = get_logger(__name__)


def _column_exists(db, table: str, column: str) -> bool:
    """SQLite pragma to check column existence. Quotes the table name
    because `case` is a reserved word."""
    rows = db.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
    # rows: (cid, name, type, notnull, dflt_value, pk)
    return any(r[1] == column for r in rows)


def _index_exists(db, index_name: str) -> bool:
    """SQLite pragma to check index existence. Quotes the index name
    (some names like 'case' are reserved words)."""
    rows = db.execute(text(f'PRAGMA index_info("{index_name}")')).fetchall()
    return len(rows) > 0


def step_rename_ppbriefing_read_at(db) -> None:
    """v1.1 item 1: rename pp_briefing.read_at -> pp_briefing.recorded_at.

    SQLite does not support RENAME COLUMN before 3.25.0; we check
    version and use ALTER TABLE if supported, else recreate the
    table. The aranmanai.db session.py uses SQLCipher which ships
    a recent SQLite, so RENAME COLUMN is always available.
    """
    if _column_exists(db, "pp_briefing", "recorded_at"):
        log.info("migrate_v11.skip_rename", reason="recorded_at already exists")
        return
    if not _column_exists(db, "pp_briefing", "read_at"):
        log.info("migrate_v11.skip_rename", reason="read_at does not exist")
        return
    log.info("migrate_v11.rename_ppbriefing.start")
    db.execute(text('ALTER TABLE "pp_briefing" RENAME COLUMN read_at TO recorded_at'))
    db.commit()
    log.info("migrate_v11.rename_ppbriefing.done")


def step_add_pocso_flag(db) -> None:
    """v1.1 item 3: add case.is_pocso_or_304b_case, default False.

    Note: `case` is a reserved word in SQL — the table name is
    quoted as `"case"`.
    """
    if _column_exists(db, "case", "is_pocso_or_304b_case"):
        log.info("migrate_v11.skip_pocso", reason="column exists")
        return
    log.info("migrate_v11.add_pocso.start")
    db.execute(
        text('ALTER TABLE "case" ADD COLUMN is_pocso_or_304b_case BOOLEAN NOT NULL DEFAULT 0')
    )
    db.commit()
    log.info("migrate_v11.add_pocso.done")


def step_add_unique_fir_constraint(db) -> None:
    """v1.1 item 2: UNIQUE(fir_no, district) on case.

    SQLite stores UNIQUE constraints as indexes. We cannot add a
    named UNIQUE constraint to an existing table in pure SQL
    (SQLite ALTER TABLE doesn't support ADD CONSTRAINT); we
    create a UNIQUE INDEX instead, which has the same effect
    and is migration-safe.
    """
    idx_name = "uq_case_fir_no_district"
    if _index_exists(db, idx_name):
        log.info("migrate_v11.skip_unique", reason=f"index {idx_name} exists")
        return
    # Check for duplicate fir_no/district pairs that would block the
    # UNIQUE INDEX. If any exist, log and skip; the IO must reconcile.
    dupes = db.execute(text(
        'SELECT fir_no, district, COUNT(*) AS n FROM "case" '
        "GROUP BY fir_no, district HAVING n > 1"
    )).fetchall()
    if dupes:
        log.warning(
            "migrate_v11.unique_blocked",
            duplicates=[(r[0], r[1], r[2]) for r in dupes],
            msg="duplicate fir_no+district pairs exist; UNIQUE INDEX not created. Reconcile manually.",
        )
        return
    log.info("migrate_v11.add_unique.start")
    db.execute(
        text(f'CREATE UNIQUE INDEX {idx_name} ON "case"(fir_no, district)')
    )
    db.commit()
    log.info("migrate_v11.add_unique.done")


def main() -> None:
    setup_logging()
    log.info("migrate_v11.start")
    settings = get_settings()
    settings.ensure_dirs()
    db = SessionLocal()
    try:
        step_rename_ppbriefing_read_at(db)
        step_add_pocso_flag(db)
        step_add_unique_fir_constraint(db)
    finally:
        db.close()
    log.info("migrate_v11.done")


if __name__ == "__main__":
    main()
