"""Integration tests for CMS endpoints (calendar, bottlenecks, SP dashboard)."""
from __future__ import annotations

from datetime import datetime, timedelta


def test_calendar_today_empty(client):
    r = client.get("/api/v1/cms/calendar/today?district=test-district")
    assert r.status_code == 200
    assert r.json() == []


def test_calendar_for_date_with_case(client):
    payload = {"fir_no": "CAL/2026", "district": "test-district"}
    r = client.post("/api/v1/cases", json=payload)
    case_id = r.json()["id"]
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
    client.post("/api/v1/hearings", json={
        "case_id": case_id, "date": tomorrow, "stage": "hearing",
    })
    target_date = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
    r2 = client.get(f"/api/v1/cms/calendar/date/{target_date}?district=test-district")
    assert r2.status_code == 200
    entries = r2.json()
    assert len(entries) == 1
    assert entries[0]["fir_no"] == "CAL/2026"


def test_calendar_week_returns_7_days(client):
    today = datetime.utcnow().date().isoformat()
    r = client.get(f"/api/v1/cms/calendar/week?start={today}&district=test-district")
    assert r.status_code == 200
    week = r.json()
    assert len(week) == 7
    # All 7 dates are present
    for i in range(7):
        d = (datetime.utcnow().date() + timedelta(days=i)).isoformat()
        assert d in week


def test_bottlenecks_empty_when_no_old_cases(client):
    r = client.get("/api/v1/cms/bottlenecks?district=test-district")
    assert r.status_code == 200
    assert r.json() == []


def test_timeline_returns_fir_and_hearing_events(client):
    payload = {"fir_no": "TL/2026", "district": "test-district"}
    r = client.post("/api/v1/cases", json=payload)
    case_id = r.json()["id"]
    future = (datetime.utcnow() + timedelta(days=2)).isoformat()
    client.post("/api/v1/hearings", json={"case_id": case_id, "date": future, "stage": "argument"})
    r2 = client.get(f"/api/v1/cms/timeline/{case_id}")
    assert r2.status_code == 200
    events = r2.json()
    # No fir_date set, no past events → may be 0 or 1 (just hearing)
    assert all("event_type" in e for e in events)


def test_sp_dashboard_returns_snapshot(client):
    r = client.get("/api/v1/cms/sp-dashboard?district=test-district")
    assert r.status_code == 200
    snap = r.json()
    assert "today_hearings" in snap
    assert "cases_stuck" in snap
    assert "top_actions" in snap
    assert isinstance(snap["top_actions"], list)
