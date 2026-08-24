"""Court Monitoring System endpoints."""
from __future__ import annotations

import datetime


def _create_case_with_hearing_and_hostile_witness(client, headers):
    """Helper: create case, hearing, 1 hostile witness."""
    r = client.post("/cases", headers=headers, json={
        "case_id": "CMS-001", "sections": ["376 IPC"], "offence": "pocso", "district": "Vellore",
        "acquittal_risk": 0.7, "status": "hearing", "stage": "trial",
    })
    case_id = r.json()["id"]
    # Create hostile witness
    r = client.post(f"/cases/{case_id}/witnesses", headers=headers, json={"name": "Hostile W", "type": "eyewitness"})
    wid = r.json()["id"]
    client.patch(f"/cases/{case_id}/witnesses/{wid}", headers=headers, json={
        "category": "Hostile", "hostile_reason": "Family of accused",
    })
    # Create hearing today
    today = int(datetime.datetime.now(tz=datetime.timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0).timestamp())
    r = client.post(f"/cases/{case_id}/hearings", headers=headers, json={"date": today, "stage": "trial"})
    return case_id, wid


def test_daily_calendar_returns_today_hearings(client, auth_headers):
    case_id, _ = _create_case_with_hearing_and_hostile_witness(client, auth_headers)
    today = int(datetime.datetime.now(tz=datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    r = client.get(f"/cms/daily-calendar?date={today}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_hearings"] == 1
    assert body["total_cases_at_risk"] == 1  # 1 hostile witness


def test_cases_at_risk_includes_high_risk(client, auth_headers):
    case_id, _ = _create_case_with_hearing_and_hostile_witness(client, auth_headers)
    r = client.get("/cms/cases-at-risk?limit=5&min_hostile=1", headers=auth_headers)
    assert r.status_code == 200
    cases = r.json()
    assert any(c["id"] == case_id for c in cases)


def test_bottlenecks_returns_stale_cases(client, auth_headers):
    """Set last_update to > 60 days ago and verify bottleneck appears."""
    import time
    from src.aranmanai.db import session_scope
    from src.aranmanai.models import Case
    # Create a case
    r = client.post("/cases", headers=auth_headers, json={
        "case_id": "STALE-001", "sections": [], "offence": "all", "district": "Vellore",
    })
    cid = r.json()["id"]
    # Force last_update to 100 days ago
    with session_scope() as db:
        c = db.get(Case, cid)
        c.last_update = int(time.time()) - 100 * 86400
    r = client.get(f"/cms/bottlenecks?threshold_days=60", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["bottleneck_count"] >= 1
    assert any(c2["id"] == cid for c2 in body["items"])


def test_witness_prep_returns_questions_for_hostile_witness(client, auth_headers):
    case_id, wid = _create_case_with_hearing_and_hostile_witness(client, auth_headers)
    r = client.post("/cms/witness-prep", headers=auth_headers, json={
        "witness_id": wid, "case_id": case_id, "focus": "cross-exam",
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["likely_questions"]) >= 3
    assert len(body["suggested_talking_points"]) >= 3
    assert any("hostile" in q["rationale"].lower() for q in body["likely_questions"])


def test_queue_stats_returns_aggregate_counts(client, auth_headers):
    _create_case_with_hearing_and_hostile_witness(client, auth_headers)
    r = client.get("/cms/queue-stats", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_cases"] >= 1
    assert body["hostile_witness_count"] >= 1
    assert "by_status" in body
    assert "by_stage" in body


def test_daily_calendar_requires_auth(client):
    r = client.get("/cms/daily-calendar?date=0")
    assert r.status_code == 401
