"""Tests for the citizen safety API (Abhaya equivalent)."""
from __future__ import annotations


def _report_payload(**overrides):
    payload = {
        "report_type": "harassment",
        "district": "default-district",
        "incident_date": "2026-08-20",
        "location_text": "Bus stand, Vellore",
        "description": "Stalking by auto driver",
        "severity": "high",
    }
    payload.update(overrides)
    return payload


def test_helpline_endpoint_returns_number(client):
    """Public helpline number, no auth required."""
    r = client.get("/api/v1/safety/helpline")
    assert r.status_code == 200
    data = r.json()
    assert "helpline_number" in data
    assert data["anonymous"] is True
    assert "languages" in data


def test_anonymous_report_no_auth_required(client):
    """Anonymous report endpoint requires no authentication."""
    r = client.post("/api/v1/safety/report", json={
        "report_type": "harassment",
        "district": "default-district",
        "incident_date": "2026-08-20",
        "location_text": "Bus stand, Vellore",
        "description": "Stalking by auto driver",
        "severity": "high",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "pending_sp_review"
    assert "next_action" in data


def test_h3_rate_limit_triggers_429_after_threshold(client):
    """Kishore-review item 6: switching /report's rate limiter from an
    in-process dict to SqliteRateLimiter must not change the externally
    visible behavior -- still 10/min, still a 429 with the same detail
    shape once exceeded.
    """
    statuses = []
    for _ in range(12):
        r = client.post("/api/v1/safety/report", json=_report_payload())
        statuses.append(r.status_code)
    assert 429 in statuses, f"expected a 429 among {statuses}"
    idx = statuses.index(429)
    # Everything before the limit was hit succeeded.
    assert all(s == 201 for s in statuses[:idx])
    r_last = client.post("/api/v1/safety/report", json=_report_payload())
    assert r_last.status_code == 429
    body = r_last.json()
    assert "Rate limit exceeded for /report" in body["detail"]
    assert "max 10/min" in body["detail"]


def test_h3_rate_limit_is_per_route(client):
    """A route hitting its own limit must not affect a different route's
    (separate) bucket -- /helpline/call has its own counter from /report.
    """
    for _ in range(10):
        r = client.post("/api/v1/safety/report", json=_report_payload())
        assert r.status_code == 201
    over = client.post("/api/v1/safety/report", json=_report_payload())
    assert over.status_code == 429

    # /helpline/call is a different route: still allowed.
    r_helpline = client.post(
        "/api/v1/safety/helpline/call",
        json={
            "caller_district": "default-district",
            "report_type": "harassment",
            "severity": "high",
            "description": "unaffected by /report's limit",
        },
    )
    assert r_helpline.status_code == 201
