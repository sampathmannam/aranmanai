"""Tests for scripts/backup.py.

scripts/backup.py had never actually worked: it imported from a dead
first-draft package layout (src.aranmanai.config/logging_config, both
long superseded) and separately called tempfile.BytesIO(), which does
not exist (BytesIO lives in io, not tempfile). Both bugs meant every
backup/restore invocation crashed immediately, regardless of the other.
These tests exercise the fixed script directly, including a full
backup+restore round-trip against isolated tmp paths (never the real
configured data dir).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backup.py"


def _load_backup_module():
    """Import scripts/backup.py by path (it's a standalone script, not
    part of the installed aranmanai package)."""
    spec = importlib.util.spec_from_file_location("aranmanai_backup_script", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def backup_mod():
    return _load_backup_module()


def test_key_bytes_rejects_short_key(backup_mod):
    with pytest.raises(SystemExit):
        backup_mod._key_bytes("too-short")


def test_key_bytes_rejects_empty_key(backup_mod):
    with pytest.raises(SystemExit):
        backup_mod._key_bytes("")


def test_key_bytes_accepts_valid_key(backup_mod):
    key = "a" * 32
    assert backup_mod._key_bytes(key) == b"a" * 32


def test_encrypt_decrypt_round_trip(backup_mod):
    key = "b" * 40
    plaintext = b"some tar.gz bytes, pretend this is a real archive payload"
    encrypted = backup_mod._encrypt(plaintext, key)
    assert encrypted != plaintext
    decrypted = backup_mod._decrypt(encrypted, key)
    assert decrypted == plaintext


def test_decrypt_wrong_key_fails(backup_mod):
    from cryptography.exceptions import InvalidTag

    encrypted = backup_mod._encrypt(b"secret data", "c" * 32)
    with pytest.raises(InvalidTag):
        backup_mod._decrypt(encrypted, "d" * 32)


def test_gather_files_excludes_backups_dir(tmp_path, backup_mod):
    data_dir = tmp_path / "data"
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True)
    (data_dir / "aranmanai.db").write_bytes(b"db content")
    (backups_dir / "old_backup.tar.gz.enc").write_bytes(b"a prior backup")

    files = backup_mod._gather_files(data_dir, exclude_dir=backups_dir)
    names = {p.name for p in files}
    assert "aranmanai.db" in names
    assert "old_backup.tar.gz.enc" not in names


def test_gather_files_skips_sqlite_sidecars(tmp_path, backup_mod):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "aranmanai.db").write_bytes(b"db")
    (data_dir / "aranmanai.db-wal").write_bytes(b"wal")
    (data_dir / "aranmanai.db-shm").write_bytes(b"shm")

    files = backup_mod._gather_files(data_dir)
    names = {p.name for p in files}
    assert names == {"aranmanai.db"}


def test_tar_gz_round_trip(tmp_path, backup_mod):
    src = tmp_path / "file.txt"
    src.write_text("hello aranmanai")
    tar_bytes = backup_mod._make_tar_gz([(src, "aranmanai_data/file.txt")])

    dest = tmp_path / "restored"
    backup_mod._extract_tar_gz(tar_bytes, dest)
    restored = dest / "aranmanai_data" / "file.txt"
    assert restored.exists()
    assert restored.read_text() == "hello aranmanai"


def test_do_backup_and_restore_round_trip(tmp_path, monkeypatch, backup_mod):
    """Full do_backup() -> do_restore() round trip against isolated tmp
    paths -- never the real configured data dir. Confirms restored file
    content is byte-identical to the source."""
    data_dir = tmp_path / "data"
    backups_dir = data_dir / "backups"
    data_dir.mkdir()
    (data_dir / "aranmanai.db").write_bytes(b"pretend encrypted sqlite bytes")

    monkeypatch.setenv("ARANMANAI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARANMANAI_BACKUPS_DIR", str(backups_dir))
    monkeypatch.setenv("ARANMANAI_BACKUP_ENCRYPTION_KEY", "e" * 40)
    monkeypatch.setenv("ARANMANAI_DB_KEY", "test-key-32-chars-aaaaaaaaaaaaaa")
    monkeypatch.setenv("ARANMANAI_JWT_SECRET", "test-jwt-32-chars-aaaaaaaaaaaaaa")
    from aranmanai.config.settings import get_settings
    get_settings.cache_clear()

    backup_path = backup_mod.do_backup(keep=7)
    assert backup_path.exists()
    assert backup_path.stat().st_size > 0

    restore_target = tmp_path / "restored"
    backup_mod.do_restore(backup_path, restore_target)
    restored_db = restore_target / "aranmanai_data" / "aranmanai.db"
    assert restored_db.exists()
    assert restored_db.read_bytes() == b"pretend encrypted sqlite bytes"

    get_settings.cache_clear()


def test_do_backup_rotates_old_backups(tmp_path, monkeypatch, backup_mod):
    """do_backup(keep=N) must remove the oldest-named archives beyond N.

    Pre-seeds fake prior backups with distinct names (rotation sorts by
    filename, which embeds the timestamp) rather than calling do_backup()
    repeatedly -- _now_stamp() is second-resolution, so rapid sequential
    calls in a test can collide on the same filename and overwrite each
    other, which would make this test flaky for reasons unrelated to
    whether rotation itself works.
    """
    data_dir = tmp_path / "data2"
    backups_dir = data_dir / "backups"
    data_dir.mkdir()
    backups_dir.mkdir(parents=True)
    (data_dir / "aranmanai.db").write_bytes(b"content")
    for stamp in ("20260101_000000", "20260102_000000", "20260103_000000"):
        (backups_dir / f"aranmanai_{stamp}.tar.gz.enc").write_bytes(b"old backup")

    monkeypatch.setenv("ARANMANAI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARANMANAI_BACKUPS_DIR", str(backups_dir))
    monkeypatch.setenv("ARANMANAI_BACKUP_ENCRYPTION_KEY", "f" * 40)
    monkeypatch.setenv("ARANMANAI_DB_KEY", "test-key-32-chars-aaaaaaaaaaaaaa")
    monkeypatch.setenv("ARANMANAI_JWT_SECRET", "test-jwt-32-chars-aaaaaaaaaaaaaa")
    from aranmanai.config.settings import get_settings
    get_settings.cache_clear()

    # One new backup + 3 pre-seeded = 4 total; keep=2 must remove the 2 oldest.
    backup_mod.do_backup(keep=2)

    remaining = sorted(p.name for p in backups_dir.glob("aranmanai_*.tar.gz.enc"))
    assert len(remaining) == 2
    # The two oldest pre-seeded stamps must be gone; the newest pre-seeded
    # stamp and the just-created backup must remain.
    assert "aranmanai_20260101_000000.tar.gz.enc" not in remaining
    assert "aranmanai_20260102_000000.tar.gz.enc" not in remaining
    assert "aranmanai_20260103_000000.tar.gz.enc" in remaining

    get_settings.cache_clear()
