"""Security: bcrypt password hashing, JWT, hash-chained audit log."""
from __future__ import annotations

import time

import pytest

from src.aranmanai import db as dbmod
from src.aranmanai.db import init_db, session_scope
from src.aranmanai.models import User
from src.aranmanai.security import (
    create_access_token,
    decode_token,
    hash_password,
    record_audit,
    verify_audit_chain,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    pwd = "correct horse battery staple"
    h = hash_password(pwd)
    assert h != pwd
    assert verify_password(pwd, h) is True
    assert verify_password("wrong-password", h) is False


def test_create_and_decode_jwt():
    token, ttl = create_access_token(user_id=42, role="SP", district="Vellore")
    assert isinstance(token, str)
    assert ttl == 60  # default from settings
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "SP"
    assert payload["district"] == "Vellore"


def test_audit_hash_chain_walks_cleanly(temp_dir):
    init_db()
    unique = "chain_unique_abc"
    with session_scope() as db:
        u = User(name="chain_test", role="IO", district="Vellore", password_hash="x")
        db.add(u); db.flush()
        for i in range(5):
            record_audit(
                db, actor_id=u.id, action=f"{unique}.action.{i}",
                subject_type="case", subject_id=f"c-{i}",
                fields_used=["a", "b"],
            )
    is_valid, n = verify_audit_chain(db)
    assert is_valid is True
    # n is the number of valid entries walked before the first break (or total if all valid)
    assert n >= 5


def test_audit_chain_detects_tampering(temp_dir):
    init_db()
    unique = "tamper_unique_xyz"
    with session_scope() as db:
        u = User(name="tamper_test", role="IO", district="Vellore", password_hash="x")
        db.add(u); db.flush()
        for i in range(3):
            record_audit(
                db, actor_id=u.id, action=f"{unique}.action.{i}",
                subject_type="case", subject_id=f"c-{i}",
            )
    # Tamper: change the 2nd audit entry's action
    with session_scope() as db:
        from src.aranmanai.models import AuditLog
        e = db.query(AuditLog).filter(AuditLog.action.like(f"{unique}.%")).order_by(AuditLog.id.asc()).offset(1).first()
        e.action = f"{unique}.tampered"
    is_valid, n = verify_audit_chain(db)
    # Chain breaks somewhere — what we care about is that tampering was detected
    assert is_valid is False
    # And the total number of entries we added is still 3 (tampering doesn't delete)
    with session_scope() as db:
        from src.aranmanai.models import AuditLog
        total = db.query(AuditLog).filter(AuditLog.action.like(f"{unique}.%")).count()
    assert total == 3


def test_audit_genesis_hash_is_zeros(temp_dir):
    """The audit entry with prev_hash = 64 zeros is the genesis entry.

    Every audit chain starts with a genesis entry whose prev_hash is
    all zeros. This invariant must hold no matter when the entry is
    written — verify by writing an entry and checking that exactly one
    genesis entry exists (the one with our action, if we're the only
    writer, or the first entry chronologically)."""
    init_db()
    with session_scope() as db:
        u = User(name="genesis_test", role="IO", district="Vellore", password_hash="x")
        db.add(u); db.flush()
        record_audit(
            db, actor_id=u.id, action="genesis_unique_qrs.test",
            subject_type="case", subject_id="g-0",
        )
    from src.aranmanai.models import AuditLog
    with session_scope() as db:
        # The genesis entry is the one whose prev_hash is all zeros.
        # There should be exactly one.
        genesis = db.query(AuditLog).filter(AuditLog.prev_hash == "0" * 64).all()
        assert len(genesis) == 1, f"expected exactly 1 genesis entry, got {len(genesis)}"
        # And that genesis entry is the one we just wrote (we're the first writer)
        assert genesis[0].action == "genesis_unique_qrs.test"
