"""Hash-chained audit log. DPDP §8(3) compliance.

Every audit entry includes:
- log_id (UUID)
- timestamp (ISO 8601 UTC)
- actor_id (user who performed the action)
- action (one of AuditAction enum)
- subject_id (case_id, witness_id, etc — the data subject under DPDP)
- fields_used (list of field names read or written)
- success (bool)
- error (str, optional)
- prev_hash (SHA256 of previous entry, or genesis hash for first)
- hash (SHA256 of this entry's contents + prev_hash)

The chain is verified by reading the file and recomputing each hash.
Any tampering breaks the chain.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from aranmanai.observability import get_logger

log = get_logger(__name__)

# C-4 fix: in-process thread lock to serialise appends.
# Prevents the "two threads read the same _last_hash, both write
# with the same prev_hash" race. For multi-process deployments,
# migrate to SQLite (atomic writes via row-level locking) - the chain
# logic stays the same.
_audit_lock = threading.Lock()

# Genesis hash — the prev_hash of the very first audit entry.
# Doesn't need to be secret; just a stable starting point.
GENESIS_HASH = "0" * 64


class AuditAction(str, Enum):
    """Enumeration of auditable actions. Aligned with DPDP §8(3)."""

    # Reads
    READ_CASE = "read.case"
    READ_WITNESS = "read.witness"
    READ_HEARING = "read.hearing"
    READ_EVIDENCE = "read.evidence"
    READ_AUDIT = "read.audit"

    # Writes
    CREATE_CASE = "create.case"
    UPDATE_CASE = "update.case"
    DELETE_CASE = "delete.case"
    CREATE_WITNESS = "create.witness"
    UPDATE_WITNESS = "update.witness"
    DELETE_WITNESS = "delete.witness"
    CREATE_HEARING = "create.hearing"
    UPDATE_HEARING = "update.hearing"

    # AI
    AI_FIR_DRAFT = "ai.fir_draft"
    AI_CHARGESHEET_DRAFT = "ai.chargesheet_draft"
    AI_CROSS_EXAM_PREP = "ai.cross_exam_prep"
    AI_INVESTIGATION_RECOMMENDATIONS = "ai.investigation_recommendations"
    AI_COMPLAINT_INTAKE = "ai.complaint_intake"
    AI_RISK_SCORE = "ai.risk_score"

    # Auth
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"

    # F10: Case lifecycle (transfers, IO/PP changes)
    TRANSFER_CASE = "case.transfer"
    CHANGE_IO = "case.change_io"
    CHANGE_PP = "case.change_pp"
    FILE_CHARGESHEET = "case.chargesheet_filed"
    GRANT_BAIL = "case.bail"

    # F12: Helpline upstream integration (1091/181)
    HELPLINE_UPSTREAM = "safety.helpline_upstream"
    HELPLINE_FAMILY_LIAISON = "case.family_liaison"

    # F14: Deputation
    CREATE_DEPUTATION = "deputation.create"
    END_DEPUTATION = "deputation.end"

    # Data subject rights (DPDP §12)
    EXPORT_DATA = "dpdp.export"
    DELETE_DATA = "dpdp.delete"


def _hash_entry(prev_hash: str, payload: dict[str, Any]) -> str:
    """Compute SHA256 hash for an entry. Deterministic via JSON sort_keys."""
    s = json.dumps({"prev": prev_hash, **payload}, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_chain(prev_hash: str, entry: dict[str, Any]) -> str:
    """Public helper: hash one entry given prev_hash and entry dict."""
    return _hash_entry(prev_hash, entry)


class AuditLog:
    """Append-only hash-chained audit log.

    Storage: line-delimited JSON (one entry per line). Easy to verify, append,
    and tail. For production, swap with Postgres or SQLite; the chain logic
    stays the same.
    """

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        """Read the last hash from the log file. GENESIS_HASH if empty."""
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return GENESIS_HASH
        last_hash = GENESIS_HASH
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    last_hash = entry.get("hash", GENESIS_HASH)
                except json.JSONDecodeError:
                    log.warning("audit.invalid_line", line=line[:100])
                    continue
        return last_hash

    def append(
        self,
        action: AuditAction,
        actor_id: str,
        subject_id: str | None = None,
        fields_used: list[str] | None = None,
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append a new entry. Returns the new entry's log_id.

        C-4 fix: held under _audit_lock to serialise concurrent appends
        from multiple threads. For multi-process deployments, migrate
        to SQLite (the chain logic is unchanged).
        """
        with _audit_lock:
            log_id = str(uuid.uuid4())
            ts = datetime.now(timezone.utc).isoformat()
            entry_core: dict[str, Any] = {
                "log_id": log_id,
                "timestamp": ts,
                "actor_id": actor_id,
                "action": action.value,
                "subject_id": subject_id,
                "fields_used": fields_used or [],
                "success": success,
                "error": error,
                "metadata": metadata or {},
            }
            new_hash = _hash_entry(self._last_hash, entry_core)
            full_entry = {**entry_core, "prev_hash": self._last_hash, "hash": new_hash}

            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(full_entry, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())  # M-3 partial: durability of the fsync
            self._last_hash = new_hash
        log.info(
            "audit.appended",
            log_id=log_id,
            action=action.value,
            actor_id=actor_id,
            subject_id=subject_id,
            success=success,
        )
        return log_id

    def verify(self) -> tuple[bool, str]:
        """Verify the chain integrity. Returns (ok, message)."""
        prev_hash = GENESIS_HASH
        count = 0
        with self.log_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    return False, f"line {line_num}: invalid JSON: {e}"
                entry_prev = entry.pop("prev_hash", None)
                entry_hash = entry.pop("hash", None)
                if entry_prev != prev_hash:
                    return False, f"line {line_num}: prev_hash mismatch"
                computed = _hash_entry(prev_hash, entry)
                if computed != entry_hash:
                    return False, f"line {line_num}: hash mismatch"
                prev_hash = entry_hash
                count += 1
        return True, f"chain OK, {count} entries verified"

    def tail(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last n entries (most recent first)."""
        entries: list[dict[str, Any]] = []
        if not self.log_path.exists():
            return entries
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return list(reversed(entries[-n:]))
