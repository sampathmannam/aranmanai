"""Unit tests for the cross-process-safe SQLite rate limiter.

Kishore-review item 6 fix: `aranmanai.api.v1.safety` used to rate-limit
via an in-process dict + threading.Lock, explicitly broken under a
multi-worker deployment (N workers = N independent buckets = effective
limit multiplied by N). `SqliteRateLimiter` replaces that with a shared
SQLite file every worker process reads/writes. These tests exercise the
limiter directly; `test_citizen_safety.py` covers it through the API.
"""
from __future__ import annotations

import pytest


def test_hit_allows_up_to_limit_then_rejects(tmp_path):
    from aranmanai.security.rate_limit import SqliteRateLimiter

    limiter = SqliteRateLimiter(tmp_path / "rate.sqlite3")
    results = [limiter.hit("1.2.3.4", "/report", 3) for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_hit_is_isolated_per_ip(tmp_path):
    from aranmanai.security.rate_limit import SqliteRateLimiter

    limiter = SqliteRateLimiter(tmp_path / "rate.sqlite3")
    for _ in range(3):
        assert limiter.hit("1.1.1.1", "/report", 3) is True
    # A different IP on the same route gets its own bucket.
    assert limiter.hit("2.2.2.2", "/report", 3) is True


def test_hit_is_isolated_per_route(tmp_path):
    from aranmanai.security.rate_limit import SqliteRateLimiter

    limiter = SqliteRateLimiter(tmp_path / "rate.sqlite3")
    for _ in range(3):
        assert limiter.hit("1.1.1.1", "/report", 3) is True
    # Same IP, different route: separate bucket.
    assert limiter.hit("1.1.1.1", "/patrol/dispatch", 3) is True


def test_cross_process_safety_two_independent_instances_share_the_limit(tmp_path):
    """The real regression test the old in-process dict never had.

    Two SEPARATE `SqliteRateLimiter` Python objects -- never sharing any
    in-memory state, no shared dict, no shared lock -- pointed at the
    SAME db_path must still enforce ONE combined limit across both,
    because the counter lives in the SQLite file, not in either
    object's memory. This is exactly the multi-worker-process scenario:
    each gunicorn/uvicorn worker constructs its own limiter instance,
    and they must all share the same underlying counter store.

    Under the OLD in-process dict design, "worker A" and "worker B"
    would each get their own independent bucket, so 2 workers x
    limit=5 would let 10 requests through instead of 5 -- the exact bug
    this task exists to fix.
    """
    from aranmanai.security.rate_limit import SqliteRateLimiter

    db_path = tmp_path / "shared_rate.sqlite3"
    worker_a = SqliteRateLimiter(db_path)
    worker_b = SqliteRateLimiter(db_path)
    assert worker_a is not worker_b  # genuinely separate objects

    limit = 5
    allowed = 0
    # Interleave hits across the two "workers", the way two real worker
    # processes handling requests from the same client IP would.
    for i in range(10):
        limiter = worker_a if i % 2 == 0 else worker_b
        if limiter.hit("9.9.9.9", "/helpline/call", limit):
            allowed += 1

    assert allowed == limit, (
        f"expected exactly {limit} allowed across both instances, got {allowed} -- "
        "the shared SQLite limit must be enforced across independently "
        "constructed instances, not per-instance"
    )


def test_window_resets_after_window_elapses(tmp_path, monkeypatch):
    """A new window (different window_start) gets a fresh counter."""
    import aranmanai.security.rate_limit as rl

    limiter = rl.SqliteRateLimiter(tmp_path / "rate.sqlite3", window_sec=60)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(rl.time, "time", lambda: fake_now[0])

    for _ in range(3):
        assert limiter.hit("5.5.5.5", "/report", 3) is True
    assert limiter.hit("5.5.5.5", "/report", 3) is False

    # Jump to the next window.
    fake_now[0] += 60
    assert limiter.hit("5.5.5.5", "/report", 3) is True


def test_cleanup_drops_stale_window_rows(tmp_path):
    """Opportunistic cleanup bounds table growth (mirrors the old TTL idea)."""
    from aranmanai.security.rate_limit import (
        _CLEANUP_MAX_WINDOWS_AGE,
        DEFAULT_WINDOW_SEC,
        SqliteRateLimiter,
    )

    limiter = SqliteRateLimiter(tmp_path / "rate.sqlite3")
    conn = limiter._connect()
    try:
        conn.execute(
            "INSERT INTO rate_buckets (ip, route, window_start, count) VALUES (?, ?, ?, ?)",
            ("stale-ip", "/report", 0, 1),
        )
        conn.commit()
        current_window_start = (_CLEANUP_MAX_WINDOWS_AGE + 10) * DEFAULT_WINDOW_SEC
        limiter._cleanup(conn, current_window_start)
        remaining = conn.execute("SELECT COUNT(*) FROM rate_buckets").fetchone()[0]
    finally:
        conn.close()
    assert remaining == 0


@pytest.mark.parametrize("limit", [1, 10, 60])
def test_hit_boundary_exactly_at_limit(tmp_path, limit):
    from aranmanai.security.rate_limit import SqliteRateLimiter

    limiter = SqliteRateLimiter(tmp_path / "rate.sqlite3")
    for _ in range(limit):
        assert limiter.hit("7.7.7.7", "/x", limit) is True
    assert limiter.hit("7.7.7.7", "/x", limit) is False
