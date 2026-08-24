"""Backup Aranmanai data to an encrypted archive.

Backs up the SQLCipher DB + ChromaDB + mock state-platform JSONs into a
single timestamped tar.gz, encrypted with the BACKUP_ENCRYPTION_KEY
(from settings) using AES-256-GCM. Also rotates old backups to keep
disk usage bounded.

Usage:
    python scripts/backup.py
    python scripts/backup.py --keep 7  # keep last 7 backups
    python scripts/backup.py --restore backups/aranmanai_20260824_120000.tar.gz.enc

Run as a scheduled task (cron / Task Scheduler) daily. With Windows
Task Scheduler:
    Action: python C:\path\to\scripts\backup.py
    Trigger: Daily, 02:00
    Run as: SYSTEM
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Make src importable when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.aranmanai.config import settings
from src.aranmanai.logging_config import configure_logging, get_logger

log = get_logger(__name__)

BACKUP_PREFIX = "aranmanai_"


def _now_stamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def _key_bytes() -> bytes:
    """Derive a 32-byte key from the BACKUP_ENCRYPTION_KEY (must be >= 32 chars)."""
    raw = settings.backup_encryption_key.encode("utf-8")
    if len(raw) < 32:
        raw = raw + b"\x00" * (32 - len(raw))
    return raw[:32]


def _encrypt(plaintext: bytes) -> bytes:
    """AES-256-GCM encrypt. Output: 12-byte nonce || ciphertext+tag."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(_key_bytes())
    ct = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct


def _decrypt(blob: bytes) -> bytes:
    """AES-256-GCM decrypt. Input: 12-byte nonce || ciphertext+tag."""
    if len(blob) < 28:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    aesgcm = AESGCM(_key_bytes())
    return aesgcm.decrypt(nonce, ct, associated_data=None)


def _gather_files(src_dir: Path) -> list[Path]:
    """All files under src_dir, recursively. Skips .wal/.shm SQLite sidecars
    (they are recreated on open) and the chroma chroma.sqlite3 (same reason)."""
    out: list[Path] = []
    for p in src_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in (".wal", ".shm"):
            continue
        if p.name == "chroma.sqlite3":
            continue
        out.append(p)
    return out


def _make_tar_gz(files_with_arcnames: list[tuple[Path, str]]) -> bytes:
    """Create a gzipped tar from [(absolute_path, archive_name), ...]."""
    buf = tempfile.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for src, arc in files_with_arcnames:
            tf.add(str(src), arcname=arc, recursive=False)
    return buf.getvalue()


def _extract_tar_gz(blob: bytes, dest_dir: Path) -> None:
    """Extract a gzipped tar into dest_dir."""
    with tarfile.open(fileobj=tempfile.BytesIO(blob), mode="r:gz") as tf:
        tf.extractall(path=str(dest_dir), filter="data")


def do_backup(keep: int = 7) -> Path:
    """Create a backup. Returns the path of the backup file."""
    configure_logging()
    settings.ensure_dirs()
    src_data = settings.data_dir
    if not src_data.exists():
        raise SystemExit(f"data dir does not exist: {src_data}")
    files = _gather_files(src_data)
    if not files:
        log.warning("no files to back up under %s", src_data)
    log.info("backup.start n_files=%s from=%s", len(files), src_data)

    arc_root = "aranmanai_data"
    payload_files = [(p, f"{arc_root}/{p.relative_to(src_data).as_posix()}") for p in files]
    payload_files.append((settings.pyproject_path if settings.pyproject_path.exists() else None, f"{arc_root}/pyproject.toml"))

    # Filter out None entries (missing pyproject)
    payload_files = [(p, a) for p, a in payload_files if p is not None]

    tar_gz = _make_tar_gz(payload_files)
    encrypted = _encrypt(tar_gz)
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
    configure_logging()
    target = target_dir or settings.data_dir
    if not backup_path.exists():
        raise SystemExit(f"backup file not found: {backup_path}")
    log.info("restore.start from=%s to=%s", backup_path, target)
    blob = backup_path.read_bytes()
    tar_gz = _decrypt(blob)
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
