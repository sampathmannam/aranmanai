"""Case CRUD + scoping."""
from __future__ import annotations


def test_create_case(client, auth_headers):
    r = client.post("/cases", headers=auth_headers, json={
        "case_id": "TEST-001",
        "fir_no": "FIR-2026-001",
        "sections": ["376 IPC", "6 POCSO"],
        "offence": "pocso",
        "district": "Vellore",
        "court": "Sessions Court, Vellore",
        "facts_text": "Test case",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["case_id"] == "TEST-001"
    assert body["sections"] == ["376 IPC", "6 POCSO"]
    assert body["status"] == "open"
    assert body["stage"] == "investigation"


def test_create_case_duplicate_returns_409(client, auth_headers):
    payload = {
        "case_id": "DUP-001", "sections": ["376 IPC"], "offence": "pocso", "district": "Vellore",
    }
    r = client.post("/cases", headers=auth_headers, json=payload)
    assert r.status_code == 201
    r = client.post("/cases", headers=auth_headers, json=payload)
    assert r.status_code == 409


def test_list_cases(client, auth_headers):
    for i in range(3):
        client.post("/cases", headers=auth_headers, json={
            "case_id": f"LIST-{i}", "sections": [], "offence": "all", "district": "Vellore",
        })
    r = client.get("/cases?limit=10", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_case_by_external_id(client, auth_headers):
    client.post("/cases", headers=auth_headers, json={
        "case_id": "EXT-001", "sections": [], "offence": "all", "district": "Vellore",
    })
    r = client.get("/cases/by-case-id/EXT-001", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["case_id"] == "EXT-001"


def test_update_case_partial(client, auth_headers):
    r = client.post("/cases", headers=auth_headers, json={
        "case_id": "UPD-001", "sections": ["376 IPC"], "offence": "pocso", "district": "Vellore",
    })
    case_id = r.json()["id"]
    r = client.patch(f"/cases/{case_id}", headers=auth_headers, json={
        "acquittal_risk": 0.6, "status": "hearing", "stage": "trial",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["acquittal_risk"] == 0.6
    assert body["status"] == "hearing"
    assert body["stage"] == "trial"


def test_delete_case_admin(client, auth_headers):
    r = client.post("/cases", headers=auth_headers, json={
        "case_id": "DEL-001", "sections": [], "offence": "all", "district": "Vellore",
    })
    case_id = r.json()["id"]
    r = client.delete(f"/cases/{case_id}", headers=auth_headers)
    assert r.status_code == 204
    r = client.get(f"/cases/{case_id}", headers=auth_headers)
    assert r.status_code == 404


def test_create_case_requires_auth(client):
    r = client.post("/cases", json={"case_id": "NO-AUTH", "sections": [], "offence": "all", "district": "X"})
    assert r.status_code == 401
