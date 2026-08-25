r"""Backup Aranmanai data to an encrypted archive.

Backs up the SQLCipher DB + ChromaDB + mock state-platform JSONs into a
single timestamped tar.gz, encrypted with the BACKUP_ENCRYPTION_KEY
(from settings) using AES-256-GCM. Also rotates old backups to keep
disk usage bounded.

Usage:
    python scripts/backup.py backup
    python scripts/backup.py backup --keep 7  # keep last 7 backups
    python scripts/backup.py restore data/backups/aranmanai_20260824_120000.tar.gz.enc

Requires ARANMANAI_BACKUP_ENCRYPTION_KEY (32+ chars) set via env var or
.env -- generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Run as a scheduled task (cron / Task Scheduler) daily. With Windows
Task Scheduler:
    Action: python C:\path\to\scripts\backup.py backup
    Trigger: Daily, 02:00
    Run as: SYSTEM
"""
from __future__ import annotations

import argparse
import os
import sys
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

# Make the installed package importable when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aranmanai.config import get_settings
from aranmanai.observability import get_logger, setup_logging

log = get_logger(__name__)

BACKUP_PREFIX = "aranmanai_"


def _now_stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def _key_bytes(backup_encryption_key: str) -> bytes:
    """Derive a 32-byte key from ARANMANAI_BACKUP_ENCRYPTION_KEY.

    Requires a genuine 32+ char secret and rejects anything shorter --
    the previous implementation silently zero-padded short/missing keys,
    which is a real weakness (a blank key would encrypt every backup
    with a fixed all-zero key). Matches the fail-fast pattern already
    used for ARANMANAI_DB_KEY / ARANMANAI_JWT_SECRET in settings.py.
    """
    if not backup_encryption_key or len(backup_encryption_key) < 32:
        raise SystemExit(
            "ARANMANAI_BACKUP_ENCRYPTION_KEY must be set to a 32+ char secret "
            "via env var or .env file. Run "
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            "to generate one."
        )
    return backup_encryption_key.encode("utf-8")[:32]


def _encrypt(plaintext: bytes, backup_encryption_key: str) -> bytes:
    """AES-256-GCM encrypt. Output: 12-byte nonce || ciphertext+tag."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(_key_bytes(backup_encryption_key))
    ct = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct


def _decrypt(blob: bytes, backup_encryption_key: str) -> bytes:
    """AES-256-GCM decrypt. Input: 12-byte nonce || ciphertext+tag."""
    if len(blob) < 28:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    aesgcm = AESGCM(_key_bytes(backup_encryption_key))
    return aesgcm.decrypt(nonce, ct, associated_data=None)


def _gather_files(src_dir: Path, exclude_dir: Path | None = None) -> list[Path]:
    """All files under src_dir, recursively. Skips .wal/.shm SQLite sidecars
    (they are recreated on open), the chroma chroma.sqlite3 (same reason),
    and anything under exclude_dir -- backups_dir defaults to a
    subdirectory of data_dir, so without this a backup would recursively
    include every prior backup archive inside itself."""
    exclude_resolved = exclude_dir.resolve() if exclude_dir else None
    out: list[Path] = []
    for p in src_dir.rglob("*"):
        if not p.is_file():
            continue
        if exclude_resolved is not None and exclude_resolved in p.resolve().parents:
            continue
        # SQLite's real WAL-mode sidecar convention is "<db>-wal"/"<db>-shm"
        # (hyphen-appended to the full filename, not a ".wal"/".shm"
        # extension) -- p.suffix would never match these; a name-suffix
        # check is what's actually needed.
        if p.name.endswith(("-wal", "-shm")):
            continue
        if p.name == "chroma.sqlite3":
            continue
        out.append(p)
    return out


def _make_tar_gz(files_with_arcnames: list[tuple[Path, str]]) -> bytes:
    """Create a gzipped tar from [(absolute_path, archive_name), ...]."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for src, arc in files_with_arcnames:
            tf.add(str(src), arcname=arc, recursive=False)
    return buf.getvalue()


def _extract_tar_gz(blob: bytes, dest_dir: Path) -> None:
    """Extract a gzipped tar into dest_dir."""
    with tarfile.open(fileobj=BytesIO(blob), mode="r:gz") as tf:
        tf.extractall(path=str(dest_dir), filter="data")


def do_backup(keep: int = 7) -> Path:
    """Create a backup. Returns the path of the backup file."""
    setup_logging()
    settings = get_settings()
    src_data = settings.data_dir
    if not src_data.exists():
        raise SystemExit(f"data dir does not exist: {src_data}")
    files = _gather_files(src_data, exclude_dir=settings.backups_dir)
    if not files:
        log.warning("no files to back up under %s", src_data)
    log.info("backup.start n_files=%s from=%s", len(files), src_data)

    arc_root = "aranmanai_data"
    payload_files = [(p, f"{arc_root}/{p.relative_to(src_data).as_posix()}") for p in files]
    pyproject_path = _ROOT / "pyproject.toml"
    if pyproject_path.exists():
        payload_files.append((pyproject_path, f"{arc_root}/pyproject.toml"))

    tar_gz = _make_tar_gz(payload_files)
    encrypted = _encrypt(tar_gz, settings.backup_encryption_key)
    stamp = _now_stamp()
    out_path = settings.backups_dir / f"{BACKUP_PREFIX}{stamp}.tar.gz.enc"
    out_path.write_bytes(encrypted)
    log.info("backup.wrote path=%s size_bytes=%s", out_path, len(encrypted))

    # Rotate: keep last `keep` backups
    backups = sorted(settings.backups_dir.glob(f"{BACKUP_PREFIX}*.tar.gz.enc"), key=lambda p: p.name)
    for old in backups[:-keep]:
        old.unlink()
        log.info("backup.rotated removed=%s", old)

    return out_path


def do_restore(backup_path: Path, target_dir: Path | None = None) -> Path:
    """Restore from a backup. Returns the target dir."""
    setup_logging()
    settings = get_settings()
    target = target_dir or settings.data_dir
    if not backup_path.exists():
        raise SystemExit(f"backup file not found: {backup_path}")
    log.info("restore.start from=%s to=%s", backup_path, target)
    blob = backup_path.read_bytes()
    tar_gz = _decrypt(blob, settings.backup_encryption_key)
    target.mkdir(parents=True, exist_ok=True)
    _extract_tar_gz(tar_gz, target)
    log.info("restore.done target=%s", target)
    return target


def main() -> int:
    p = argparse.ArgumentParser(description="Aranmanai backup / restore")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="create a backup")
    b.add_argument("--keep", type=int, default=7, help="number of recent backups to keep")
    r = sub.add_parser("restore", help="restore from a backup")
    r.add_argument("backup", type=Path)
    r.add_argument("--to", type=Path, default=None)
    args = p.parse_args()

    if args.cmd == "backup":
        out = do_backup(keep=args.keep)
        print(f"OK: {out}")
        return 0
    elif args.cmd == "restore":
        out = do_restore(args.backup, args.to)
        print(f"OK: restored to {out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
