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
import re
import threading
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from filelock import FileLock, Timeout

from aranmanai.observability import get_logger

log = get_logger(__name__)

# C-4 fix: in-process thread lock to serialise appends.
# Prevents the "two threads read the same _last_hash, both write
# with the same prev_hash" race. Held INSIDE the per-instance
# cross-process FileLock (see AuditLog.append): the file lock is the
# real multi-writer guard, the thread lock is belt-and-suspenders for
# threads within one process (and sidesteps having to separately prove
# filelock's own thread-safety for one FileLock shared across threads).
_audit_lock = threading.Lock()

# Cross-process append lock timeout (seconds). Bounded so a wedged
# holder can't hang a request forever; on expiry we deliberately let
# Timeout propagate rather than dropping a compliance-critical write.
_AUDIT_LOCK_TIMEOUT_SEC = 10

# Genesis hash — the prev_hash of the very first audit entry.
# Doesn't need to be secret; just a stable starting point.
GENESIS_HASH = "0" * 64

# H-5 fix: defense-in-depth bound on actor_id length. Real actor_ids are
# either User.id (a UUID string, ~36 chars) or a login username (up to
# 64 chars per LoginRequest's Field(max_length=64), recorded as actor_id
# on LOGIN_FAILED before the user row -- and thus User.id -- is known).
# 128 leaves generous headroom for either without allowing unbounded input.
_MAX_ACTOR_ID_LEN = 128

# Control characters (C0 + DEL): never legitimate in an identity string.
# json.dumps() would escape these safely, but silently accepting them
# into a DPDP Sec 8(3) compliance log undermines its evidentiary value --
# reject as clearly-invalid identity data instead.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _validate_actor_id(actor_id: str) -> None:
    """Validate actor_id before it is written into the audit chain.

    H-5 fix (defense-in-depth): AuditLog.append() previously accepted
    any string as actor_id with zero validation. Nothing stopped a
    caller from passing an empty string, an absurdly long string, or a
    string containing control characters as the identity of "who did
    this" in a hash-chained, DPDP Sec 8(3) compliance-critical audit
    trail. Raises ValueError on any of those; callers should treat a
    ValueError here as a bug at the call site, not a recoverable
    condition.
    """
    if not actor_id or not actor_id.strip():
        raise ValueError("actor_id must not be empty or whitespace-only")
    if len(actor_id) > _MAX_ACTOR_ID_LEN:
        raise ValueError(
            f"actor_id exceeds max length of {_MAX_ACTOR_ID_LEN} chars "
            f"(got {len(actor_id)})"
        )
    if _CONTROL_CHAR_RE.search(actor_id):
        raise ValueError("actor_id must not contain control characters")


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

    # P1 AuditLog memoization: cache the constructed AuditLog per path.
    # Avoids re-reading the entire file on every API call (O(n^2) lifetime).
    _instances: ClassVar[dict] = {}

    def __new__(cls, log_path: Path):
        key = str(log_path.resolve())
        if key not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, log_path: Path) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()
        # Cross-process append lock. Sidecar file next to the log
        # (`<log>.lock`); the `.lock` suffix deliberately does NOT match
        # the `<log>.N` rotation pattern that verify_all() globs over, so
        # the auditor's rotation walk never mistakes it for a log file.
        # Constructed once per AuditLog instance (instances are path-keyed
        # and memoized in _instances) — never re-created per append().
        self._lock_path = self.log_path.with_name(self.log_path.name + ".lock")
        self._file_lock = FileLock(str(self._lock_path), timeout=_AUDIT_LOCK_TIMEOUT_SEC)
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

    def _read_last_hash_from_tail(self) -> str:
        """Read the last entry's hash by seeking from the end of the file.

        Unlike `_read_last_hash` (which scans the whole file — correct and
        needed for __init__/verify), this walks backward in bounded chunks
        to find only the last complete line, so it is O(1)-ish per append
        rather than O(n). It is called INSIDE the append lock on every
        append to get the *true* on-disk last hash — never trusting a
        possibly-stale in-memory `self._last_hash` that another process may
        have invalidated. Returns GENESIS_HASH for an empty/missing file.
        """
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return GENESIS_HASH
        chunk_size = 4096
        with self.log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            buffer = b""
            pos = file_size
            last_line: bytes | None = None
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                buffer = f.read(read_size) + buffer
                # A complete last line needs a newline separating it from
                # earlier content. Strip any trailing newlines first so a
                # file ending in "\n" doesn't yield an empty final line.
                stripped = buffer.rstrip(b"\n")
                nl = stripped.rfind(b"\n")
                if nl != -1:
                    last_line = stripped[nl + 1:]
                    break
                # No newline yet and we've reached the start: the whole
                # buffer is the (single) last line.
                if pos == 0:
                    last_line = stripped
                    break
            if last_line is None:
                return GENESIS_HASH
            text = last_line.strip()
            if not text:
                return GENESIS_HASH
            try:
                entry = json.loads(text.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.warning("audit.invalid_tail_line", line=text[:100])
                return GENESIS_HASH
            return entry.get("hash", GENESIS_HASH)

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

        Concurrency (multi-process, e.g. `uvicorn ... --workers 4`):
        the whole critical section runs under a cross-process FileLock
        (outermost) with the in-process thread lock nested inside. The
        real fix for the multi-writer chain-corruption bug is that we
        re-read the TRUE last hash from disk (via the bounded tail read)
        on every append while the lock is held, instead of trusting the
        in-memory `self._last_hash`, which goes stale the instant a
        different process appends. `self._last_hash` is kept only as a
        same-process fast-path cache and is never used as prev_hash
        without the fresh tail-read happening first inside the lock.

        On FileLock timeout we let filelock.Timeout propagate rather than
        silently dropping the write: a lost DPDP §8(3) audit entry is a
        worse failure mode than a request erroring out.

        P1 M-3 fix: open binary mode for portable fsync on Windows.
        Text-mode fsync is a partial no-op on Windows because Python's
        text wrapper uses WriteFile not write.

        H-5 fix: actor_id is validated before we ever try to take the
        lock, so a bad caller fails fast without perturbing the chain
        or blocking other appenders.
        """
        _validate_actor_id(actor_id)
        line_bytes: bytes
        try:
            # Intentionally nested (not a single combined `with`): the file
            # lock MUST be the outermost guard and the thread lock the
            # innermost. noqa SIM117 — the nesting expresses that ordering.
            with self._file_lock:  # cross-process (outermost)  # noqa: SIM117
                with _audit_lock:  # in-process threads (innermost)
                    # Always read the fresh on-disk last hash inside the
                    # lock — never trust a possibly-stale cache.
                    prev_hash = self._read_last_hash_from_tail()
                    log_id = str(uuid.uuid4())
                    ts = datetime.now(UTC).isoformat()
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
                    new_hash = _hash_entry(prev_hash, entry_core)
                    full_entry = {**entry_core, "prev_hash": prev_hash, "hash": new_hash}
                    line_bytes = (json.dumps(full_entry, default=str) + "\n").encode("utf-8")
                    with self.log_path.open("ab") as f:
                        f.write(line_bytes)
                        f.flush()
                        os.fsync(f.fileno())  # now durable on Linux + Windows
                    # Same-process fast-path cache only. Correctness never
                    # depends on this — the next append re-reads from disk.
                    self._last_hash = new_hash
        except Timeout:
            # Bounded wait exceeded (holder wedged/crashed uncleanly).
            # Propagate — do NOT drop a compliance-critical audit write.
            log.error(
                "audit.lock_timeout",
                log_path=str(self.log_path),
                timeout_sec=_AUDIT_LOCK_TIMEOUT_SEC,
            )
            raise
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
        """Verify the chain integrity of the current file. Returns (ok, message).

        v1.1: use `verify_all()` to walk rotated files. This method
        verifies a single file; rotation breaks the chain from the
        caller's perspective (each rotated file is its own chain
        starting at GENESIS).
        """
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

    def verify_all(self) -> tuple[bool, str]:
        """Verify the chain across rotated files.

        v1.1: rotation-aware verify. Walks the current file
        (`self.log_path`) and any sibling rotated files
        (`audit.log.1`, `audit.log.2`, ...). Each file is verified
        independently — rotation is not tampering, the chain just
        restarts at GENESIS. The DPDP auditor can now verify a 6-month
        audit history that has been rotated weekly without getting a
        false-positive "chain broken" after the first rotation.

        Sorted order: rotated files first (oldest `.N` to newest),
        then the current file. The current file's first entry's
        `prev_hash` is GENESIS, so a successful verify on each file
        in turn is a clean result.
        """
        base = self.log_path
        parent = base.parent
        # Find rotated files: audit.log.1, audit.log.2, ..., audit.log.9
        # (in practice a rotation tool may produce higher N, but
        # single-digit N is the v1.1 assumption).
        rotated: list[Path] = []
        for n in range(1, 20):
            p = parent / f"{base.name}.{n}"
            if p.exists():
                rotated.append(p)
            else:
                break
        # Oldest first
        rotated.sort(key=lambda p: int(p.name.split(".")[-1]), reverse=True)
        files_to_check = [*rotated, base]
        total = 0
        for f in files_to_check:
            prev_hash = GENESIS_HASH
            count = 0
            with f.open("r", encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as e:
                        return False, f"{f.name} line {line_num}: invalid JSON: {e}"
                    entry_prev = entry.pop("prev_hash", None)
                    entry_hash = entry.pop("hash", None)
                    if entry_prev != prev_hash:
                        return False, f"{f.name} line {line_num}: prev_hash mismatch"
                    computed = _hash_entry(prev_hash, entry)
                    if computed != entry_hash:
                        return False, f"{f.name} line {line_num}: hash mismatch"
                    prev_hash = entry_hash
                    count += 1
            total += count
        return True, f"chain OK across {len(files_to_check)} file(s), {total} entries verified"

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
