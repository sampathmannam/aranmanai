"""End-to-end pilot flow test.

Simulates a 3-month pilot: create a case, register witnesses, run AI
services, log a hearing, compute risk, snapshot the SP dashboard.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def test_full_pilot_flow(client):
    """End-to-end: 1 case, 2 witnesses (1 hostile), 1 hearing, AI services, dashboard."""
    # 1. Create case
    r = client.post("/api/v1/cases", json={
        "fir_no": "PILOT/2026",
        "district": "test-district",
        "bns_sections": ["BNS 308"],
        "bnss_sections": ["154 BNSS"],
        "facts_text": "Accused threatened complainant with knife at bus stand.",
    })
    assert r.status_code == 201
    case_id = r.json()["id"]

    # 2. Register 2 witnesses
    w1 = client.post("/api/v1/witnesses", json={
        "case_id": case_id, "name": "Witness 1", "type": "eyewitness", "category": "supportive",
    }).json()
    w2 = client.post("/api/v1/witnesses", json={
        "case_id": case_id, "name": "Witness 2", "type": "eyewitness", "category": "hostile",
        "hostile_reason": "Threat from accused family",
    }).json()

    # 3. Schedule hearing for today
    today = datetime.utcnow().isoformat()
    h = client.post("/api/v1/hearings", json={
        "case_id": case_id, "date": today, "stage": "hearing",
    })
    assert h.status_code == 201

    # 4. Cross-exam prep for hostile witness
    r2 = client.post(
        f"/api/v1/witnesses/{w2['id']}/cross-exam-prep",
        params={"case_facts": "Knife threat at bus stand", "language": "en"},
    )
    assert r2.status_code == 200
    assert len(r2.json()["questions"]) > 0

    # 5. Risk score
    r3 = client.post("/api/v1/risk/score", json={
        "case_id": case_id,
        "case_facts": "Knife threat",
        "evidence_strength": "MEDIUM",
        "witness_count": 2,
        "hostile_witness_count": 1,
        "fsl_status": "sent",
        "bnss_173_compliant": True,
        "lapses": [{"key": "hostile_witness", "tier": "FATAL", "description": "hostile"}],
        "language": "en",
    })
    assert r3.status_code == 200
    assert r3.json()["advisory_only"] is True

    # 6. SP dashboard
    r4 = client.get("/api/v1/cms/sp-dashboard?district=test-district")
    assert r4.status_code == 200
    snap = r4.json()
    assert snap["today_hearings"] >= 1  # the hearing is today
    assert snap["critical_hearings"] >= 1  # hostile witness → critical
    assert snap["hostile_witnesses_needing_prep"] >= 1

    # 7. Investigation recommendations
    r5 = client.post("/api/v1/ai/investigation-recommendations", json={
        "case_id": case_id,
        "lapses": [
            {"key": "hostile_witness", "tier": "FATAL", "description": "hostile witness not yet prepped"},
        ],
        "case_facts": "Knife threat at bus stand",
        "evidence_list": ["knife recovered"],
        "witness_list": ["Witness 1 (supportive)", "Witness 2 (hostile)"],
        "language": "en",
    })
    assert r5.status_code == 200
    assert len(r5.json()["recommendations"]) > 0
