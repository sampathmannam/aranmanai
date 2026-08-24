"""Unit tests for the hash-chained audit log."""
from __future__ import annotations

import json
from pathlib import Path


def test_audit_appends_and_verifies(tmp_env):
    from aranmanai.security import AuditAction, AuditLog
    log = AuditLog(tmp_env / "audit.log")
    log.append(AuditAction.LOGIN, actor_id="u1", subject_id="u1", success=True)
    log.append(AuditAction.LOGIN_FAILED, actor_id="u2", subject_id="u2", success=False, error="bad creds")
    log.append(AuditAction.CREATE_CASE, actor_id="u1", subject_id="case-1", fields_used=["fir_no", "district"])

    ok, msg = log.verify()
    assert ok is True
    assert "3 entries" in msg


def test_audit_detects_tampering(tmp_env):
    from aranmanai.security import AuditAction, AuditLog
    log = AuditLog(tmp_env / "audit.log")
    log.append(AuditAction.LOGIN, actor_id="u1")
    log.append(AuditAction.CREATE_CASE, actor_id="u1", subject_id="case-1")
    log.append(AuditAction.UPDATE_CASE, actor_id="u1", subject_id="case-1")

    # Tamper: rewrite the second line with a different action
    path = tmp_env / "audit.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["action"] = "evil.action"
    lines[1] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    log2 = AuditLog(path)
    ok, msg = log2.verify()
    assert ok is False
    assert "hash mismatch" in msg or "prev_hash" in msg


def test_audit_chain_resumes_across_instances(tmp_env):
    from aranmanai.security import AuditAction, AuditLog
    log1 = AuditLog(tmp_env / "audit.log")
    log1.append(AuditAction.LOGIN, actor_id="u1", subject_id="u1")
    last_hash = log1._last_hash
    # Re-open and append
    log2 = AuditLog(tmp_env / "audit.log")
    log2.append(AuditAction.CREATE_CASE, actor_id="u1", subject_id="c1")
    assert log2._last_hash != last_hash
    ok, _ = log2.verify()
    assert ok is True


def test_audit_tail_returns_last_n(tmp_env):
    from aranmanai.security import AuditAction, AuditLog
    log = AuditLog(tmp_env / "audit.log")
    for i in range(10):
        log.append(AuditAction.CREATE_CASE, actor_id=f"u{i}", subject_id=f"c{i}")
    last5 = log.tail(5)
    assert len(last5) == 5
    # Most recent first
    assert "u9" in last5[0]["actor_id"]


def test_audit_optional_fields(tmp_env):
    from aranmanai.security import AuditAction, AuditLog
    log = AuditLog(tmp_env / "audit.log")
    log.append(
        AuditAction.AI_FIR_DRAFT,
        actor_id="io-1",
        subject_id="draft-1",
        fields_used=["name", "facts", "sections_bns"],
        success=True,
        error=None,
        metadata={"model": "qwen-1.5b", "tokens": 1234},
    )
    entries = log.tail(1)
    e = entries[0]
    assert e["fields_used"] == ["name", "facts", "sections_bns"]
    assert e["metadata"]["model"] == "qwen-1.5b"
    assert e["success"] is True
