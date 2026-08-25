"""Integration tests for case API endpoints."""
from __future__ import annotations


def test_create_and_get_case(client):
    payload = {
        "fir_no": "INT-001/2026",
        "district": "test-district",
        "bns_sections": ["BNS 308"],
        "bnss_sections": ["154 BNSS"],
        "facts_text": "Test facts for the case.",
    }
    r = client.post("/api/v1/cases", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    case_id = data["id"]
    # Kishore review item 5: FIR-number normalizer canonicalizes dashes to
    # "/" and strips leading zeros, so "INT-001/2026" -> "INT/1/2026".
    assert data["fir_no"] == "INT/1/2026"
    assert data["status"] == "open"
    assert data["stage"] == "investigation"

    r2 = client.get(f"/api/v1/cases/{case_id}")
    assert r2.status_code == 200
    assert r2.json()["fir_no"] == "INT/1/2026"


def test_list_cases_filtered_by_district(client):
    client.post("/api/v1/cases", json={"fir_no": "A/2026", "district": "test-district"})
    client.post("/api/v1/cases", json={"fir_no": "B/2026", "district": "other-district"})
    r = client.get("/api/v1/cases?district=test-district")
    assert r.status_code == 200
    cases = r.json()
    firs = {c["fir_no"] for c in cases}
    assert "A/2026" in firs
    assert "B/2026" not in firs


def test_update_case_advances_stage(client):
    r = client.post("/api/v1/cases", json={"fir_no": "UPD/2026", "district": "test-district"})
    case_id = r.json()["id"]
    r2 = client.patch(f"/api/v1/cases/{case_id}", json={"stage": "charge_sheet", "next_hearing": "2026-09-15T10:00:00"})
    assert r2.status_code == 200
    assert r2.json()["stage"] == "charge_sheet"
    assert r2.json()["next_hearing"] is not None


def test_get_case_404(client):
    r = client.get("/api/v1/cases/nonexistent-id")
    assert r.status_code == 404


def test_create_case_requires_auth(tmp_env, test_user):
    from fastapi.testclient import TestClient
    from aranmanai.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        # No auth header
        r = c.post("/api/v1/cases", json={"fir_no": "X/2026", "district": "test-district"})
        assert r.status_code == 401


def test_witness_create_with_encrypted_name(client):
    r = client.post("/api/v1/cases", json={"fir_no": "WIT/2026", "district": "test-district"})
    case_id = r.json()["id"]
    r2 = client.post("/api/v1/witnesses", json={
        "case_id": case_id,
        "name": "Test Witness",
        "contact": "+91-1234567890",
        "type": "eyewitness",
        "category": "supportive",
    })
    assert r2.status_code == 201
    w = r2.json()
    assert w["name"] == "Test Witness"  # decrypted on read
    assert w["category"] == "supportive"


def test_witness_categorize_to_hostile_then_back(client):
    r = client.post("/api/v1/cases", json={"fir_no": "CAT/2026", "district": "test-district"})
    case_id = r.json()["id"]
    w = client.post("/api/v1/witnesses", json={
        "case_id": case_id, "name": "W", "type": "eyewitness", "category": "neutral",
    }).json()
    wid = w["id"]
    # Move to hostile
    r2 = client.patch(f"/api/v1/witnesses/{wid}/category?category=hostile&reason=Threat+from+accused")
    assert r2.status_code == 200
    assert r2.json()["category"] == "hostile"
    # Back to supportive
    r3 = client.patch(f"/api/v1/witnesses/{wid}/category?category=supportive")
    assert r3.json()["category"] == "supportive"
    assert r3.json()["hostile_reason"] is None
