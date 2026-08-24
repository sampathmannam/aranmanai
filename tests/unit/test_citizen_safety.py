"""Tests for the citizen safety API (Abhaya equivalent)."""
from __future__ import annotations


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
