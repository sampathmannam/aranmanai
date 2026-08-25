"""Unit tests for the hash-chained audit log."""
from __future__ import annotations

import json
import multiprocessing
import uuid
from pathlib import Path

import pytest


def _mp_append_worker(log_path_str: str, actor: str, count: int) -> None:
    """Module-level, picklable worker for the cross-process regression test.

    Must be top-level (not a nested closure/lambda) because multiprocessing
    uses the 'spawn' start method on Windows, which re-imports this module
    and pickles the target by qualified name. Constructs its OWN AuditLog
    (a separate OS process has its own _last_hash cache and its own
    FileLock handle — exactly the multi-worker uvicorn scenario) and
    appends `count` entries to the shared path.
    """
    from aranmanai.security.audit import AuditAction, AuditLog

    log = AuditLog(Path(log_path_str))
    for i in range(count):
        log.append(AuditAction.READ_CASE, actor_id=actor, subject_id=f"{actor}-{i}")


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


def test_c4_audit_chain_survives_concurrent_writes(tmp_env):
    """C-4: concurrent in-process (thread) appends must verify cleanly.

    Relocated from test_kishore_endpoints.py and rewritten to use an
    isolated tmp path instead of the real configured audit log. This
    exercises the in-process thread lock; the genuine cross-process
    regression is test_c4_audit_chain_survives_multiprocess_writes below.
    """
    import threading

    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")

    def spam():
        for i in range(20):
            log.append(AuditAction.READ_CASE, actor_id="race-test", subject_id=f"c-{i}")

    threads = [threading.Thread(target=spam) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok, msg = log.verify()
    assert ok, f"chain broken: {msg}"


def test_c4_audit_chain_survives_multiprocess_writes(tmp_path):
    """C-4 (real bug): multiple OS PROCESSES appending to the same log
    concurrently must still produce an unbroken chain.

    This is the test that actually exercises the multi-worker uvicorn
    deployment. Each process has its own in-memory _last_hash cache and
    its own threading.Lock, so without the cross-process FileLock + the
    fresh on-disk tail-read inside it, two processes read the same last
    hash and both append with the same prev_hash — corrupting the chain.
    A pure-threading test can never catch this (shared address space).

    Uses plain tmp_path and a module-level worker so it pickles under the
    'spawn' start method (the default on Windows).
    """
    from aranmanai.security import AuditLog

    log_path = tmp_path / "audit.log"
    n_procs = 4
    per_proc = 25

    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_mp_append_worker, args=(str(log_path), f"proc-{p}", per_proc))
        for p in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    for p in procs:
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    # Fresh instance reads the combined on-disk result.
    verifier = AuditLog(log_path)
    ok, msg = verifier.verify()
    assert ok, f"chain broken after concurrent multiprocess writes: {msg}"
    assert f"{n_procs * per_proc} entries" in msg, f"unexpected entry count: {msg}"


def test_h5_actor_id_valid_uuid_happy_path(tmp_env):
    """H-5: a real User.id-shaped UUID actor_id keeps working."""
    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")
    actor = str(uuid.uuid4())
    log_id = log.append(AuditAction.READ_CASE, actor_id=actor, subject_id="c-1")
    assert log_id
    entries = log.tail(1)
    assert entries[0]["actor_id"] == actor


def test_h5_actor_id_valid_username_happy_path(tmp_env):
    """H-5: login-failed style actor_id (raw username, not yet a User.id)
    up to the 64-char LoginRequest max must keep working.
    """
    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")
    username = "u" * 64
    log_id = log.append(AuditAction.LOGIN_FAILED, actor_id=username, subject_id=username, success=False)
    assert log_id


@pytest.mark.parametrize(
    "bad_actor_id",
    [
        "",
        "   ",
        "\t\n",
        "x" * 129,
        "actor\x00id",
        "actor\x1fid",
        "actor\x7fid",
    ],
)
def test_h5_actor_id_rejects_invalid(tmp_env, bad_actor_id):
    """H-5: empty/whitespace-only, over-length, and control-char actor_ids
    must be rejected before anything is written to the compliance log.
    """
    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")
    with pytest.raises(ValueError):
        log.append(AuditAction.READ_CASE, actor_id=bad_actor_id, subject_id="c-1")
    # Nothing was written — the chain is still empty / unaffected.
    ok, msg = log.verify()
    assert ok
    assert "0 entries" in msg


def test_h5_actor_id_max_length_boundary_accepted(tmp_env):
    """H-5: exactly the max length (128 chars) is accepted, not rejected."""
    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")
    actor = "x" * 128
    log_id = log.append(AuditAction.READ_CASE, actor_id=actor, subject_id="c-1")
    assert log_id


def test_v11_audit_verify_all_walks_rotated_files(tmp_env):
    """v1.1: verify_all() returns OK even when the log has been rotated.

    Relocated from test_kishore_endpoints.py and rewritten to use an
    isolated tmp path. The original operated on the real configured audit
    log and unlink()'d a rotated copy of it — destroying real history if
    ever run against a production path.
    """
    from aranmanai.security import AuditAction, AuditLog

    log = AuditLog(tmp_env / "audit.log")
    # Append 5 entries to the current file
    for i in range(5):
        log.append(AuditAction.READ_CASE, actor_id="rotate-test", subject_id=f"r-{i}")

    # Simulate rotation: copy current → audit.log.1, then truncate current
    current = log.log_path
    rotated = current.with_suffix(current.suffix + ".1")
    rotated.write_bytes(current.read_bytes())
    current.write_bytes(b"")

    # The file was truncated out from under `log`, so resync its cache
    # directly rather than mutating the shared class-level _instances dict
    # (the instance is memoized on this same path). A fresh append must now
    # start a new chain from GENESIS in the emptied current file.
    log._last_hash = log._read_last_hash()
    for i in range(3):
        log.append(AuditAction.READ_CASE, actor_id="rotate-test", subject_id=f"r-new-{i}")

    # verify() on the current file alone: passes (new chain from GENESIS)
    ok_curr, _ = log.verify()
    assert ok_curr, "current file alone must verify"

    # verify_all() must walk both files and pass
    ok_all, msg_all = log.verify_all()
    assert ok_all, f"verify_all() must pass across rotated files: {msg_all}"
    assert "2 file(s)" in msg_all or "2 files" in msg_all, f"expected 2 files, got: {msg_all}"
