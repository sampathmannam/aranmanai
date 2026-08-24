"""Witness CRUD + categorization."""
from __future__ import annotations


def _create_case(client, headers) -> int:
    r = client.post("/cases", headers=headers, json={
        "case_id": "W-001", "sections": ["376 IPC"], "offence": "pocso", "district": "Vellore",
    })
    return r.json()["id"]


def test_create_witness(client, auth_headers):
    cid = _create_case(client, auth_headers)
    r = client.post(f"/cases/{cid}/witnesses", headers=auth_headers, json={
        "name": "Witness A", "type": "victim", "language": "Tamil",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["category"] == "Neutral"  # default
    assert body["prep_status"] == "untouched"


def test_categorize_witness_as_hostile(client, auth_headers):
    cid = _create_case(client, auth_headers)
    r = client.post(f"/cases/{cid}/witnesses", headers=auth_headers, json={"name": "W2", "type": "eyewitness"})
    wid = r.json()["id"]
    r = client.patch(f"/cases/{cid}/witnesses/{wid}", headers=auth_headers, json={
        "category": "Hostile",
        "hostile_reason": "Family of accused; threatened",
    })
    assert r.status_code == 200
    assert r.json()["category"] == "Hostile"


def test_list_witnesses_by_category(client, auth_headers):
    cid = _create_case(client, auth_headers)
    for cat in ("Supportive", "Hostile", "Neutral"):
        r = client.post(f"/cases/{cid}/witnesses", headers=auth_headers, json={"name": f"W-{cat}"})
        wid = r.json()["id"]
        if cat != "Neutral":
            client.patch(f"/cases/{cid}/witnesses/{wid}", headers=auth_headers, json={"category": cat})
    r = client.get(f"/cases/{cid}/witnesses?category=Hostile", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "W-Hostile"
