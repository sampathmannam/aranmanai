"""Cross-process-safe rate limiting via SQLite.

Kishore-review item 6 fix: the original citizen-safety rate limiter
(`aranmanai.api.v1.safety._rate_state` / `_check_rate`) was an
in-process `dict` guarded by a `threading.Lock`. That is explicitly
broken under a multi-worker deployment (`uvicorn --workers N` /
gunicorn): each worker process gets its own independent bucket dict,
so the effective per-IP limit becomes N times the configured limit
instead of the configured limit.

This module replaces that with `SqliteRateLimiter`, backed by a small
dedicated SQLite database file living alongside the audit log (no new
infrastructure dependency — this codebase already ships sqlite3 in the
stdlib and already uses `filelock`-style file-based coordination for
the audit log). SQLite's file-level locking makes the counter visible
and consistently updatable across every worker process that shares the
same DB file, which is exactly the property gunicorn/uvicorn multi-
worker deployments need.

Design:
- Fixed 60-second windows (not sliding). Each `(ip, route,
  window_start)` triple is one row with a hit counter.
- The increment-and-read happens in a single atomic SQL statement
  (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`), so two processes
  racing to record a hit in the same window can never both observe a
  pre-limit count when the true combined count is already over it.
- WAL mode + a bounded `timeout` on connect so concurrent readers/
  writers across processes don't deadlock or block a request forever.
- Opportunistic cleanup of old window rows on a small fraction of
  calls (mirrors the old `_cleanup_rate_state` idea of bounding
  storage growth, but without needing shared in-process state across
  workers to gate *when* to run it).
"""
from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path

# Fixed rate-limit window, in seconds.
DEFAULT_WINDOW_SEC = 60

# Opportunistic cleanup: instead of a shared "last cleanup" timestamp
# (which can't be shared cheaply across processes), each call rolls the
# dice; over enough requests, cleanup runs regularly without needing any
# cross-process coordination of its own.
_CLEANUP_PROBABILITY = 0.01

# Drop window rows once they're this many windows old. Comfortably past
# any window a client could still be rate-limited against.
_CLEANUP_MAX_WINDOWS_AGE = 5

# Bounded wait for SQLite's own busy handling before giving up, so a
# stuck/wedged writer in another process can't hang a request forever.
_CONNECT_TIMEOUT_SEC = 5


class SqliteRateLimiter:
    """Fixed-window rate limiter backed by a shared SQLite file.

    Deliberately holds no in-memory counters: every `hit()` call is a
    fresh, self-contained round trip to the SQLite file, so any number
    of independently-constructed `SqliteRateLimiter` instances (one per
    worker process, in production; one per Python object, in a test
    simulating that) pointed at the same `db_path` enforce one shared
    limit.
    """

    def __init__(self, db_path: Path, window_sec: int = DEFAULT_WINDOW_SEC) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.window_sec = window_sec
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=_CONNECT_TIMEOUT_SEC)
        # WAL mode: readers don't block writers and vice versa, which is
        # what makes cross-process access safe without long lock waits.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=%d" % (_CONNECT_TIMEOUT_SEC * 1000))
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_buckets (
                    ip TEXT NOT NULL,
                    route TEXT NOT NULL,
                    window_start INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (ip, route, window_start)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def hit(self, ip: str, route: str, limit: int) -> bool:
        """Record one hit for `(ip, route)` in the current window.

        Returns True if the hit is within `limit` (allowed), False if
        it pushed the window's count over `limit` (should be rejected
        with 429). The increment and the check happen atomically via a
        single `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`
        statement, so concurrent callers (threads or separate
        processes) can never both read a stale under-limit count.
        """
        now = time.time()
        window_start = int(now // self.window_sec) * self.window_sec
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO rate_buckets (ip, route, window_start, count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(ip, route, window_start)
                DO UPDATE SET count = count + 1
                RETURNING count
                """,
                (ip, route, window_start),
            )
            row = cur.fetchone()
            conn.commit()
            count = row[0] if row is not None else 1
            if random.random() < _CLEANUP_PROBABILITY:
                self._cleanup(conn, window_start)
            return count <= limit
        finally:
            conn.close()

    def _cleanup(self, conn: sqlite3.Connection, current_window_start: int) -> None:
        """Opportunistically drop stale window rows to bound table growth."""
        cutoff = current_window_start - (_CLEANUP_MAX_WINDOWS_AGE * self.window_sec)
        conn.execute("DELETE FROM rate_buckets WHERE window_start < ?", (cutoff,))
        conn.commit()
