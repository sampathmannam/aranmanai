"""Integration tests for AI assist endpoints (using mock LLM)."""
from __future__ import annotations


def test_complaint_intake_returns_structured(client):
    r = client.post("/api/v1/ai/complaint-intake", json={
        "raw_complaint": "Yesterday at the bus stand, an unknown person snatched my bag.",
        "complainant_name": "Ravi",
        "complainant_contact": "+91-9876543210",
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "draft_id" in data
    assert "structured" in data
    assert len(data["structured"]) > 0


def test_fir_draft_returns_draft(client):
    r = client.post("/api/v1/ai/fir-draft", json={
        "complainant_name": "Ravi",
        "complainant_contact": "+91-9876543210",
        "incident_time": "2026-08-15 14:30",
        "location": "Tambaram bus stand",
        "facts": "Accused approached and threatened with knife.",
        "sections_bns": ["BNS 308"],
        "sections_bnss": ["154 BNSS"],
        "police_station": "Tambaram PS",
        "district": "Chengalpattu",
        "io_name": "IO S. Krishnan",
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "fir_text" in data
    assert "draft_id" in data
    assert "io_approved" in data
    assert data["io_approved"] is False  # always requires IO approval


def test_investigation_recommendations(client):
    r = client.post("/api/v1/ai/investigation-recommendations", json={
        "case_id": "case-1",
        "lapses": [
            {"key": "fir_delay_unexplained", "tier": "FATAL", "description": "FIR filed 5 days after incident"},
            {"key": "hostile_witness_no_prep", "tier": "SERIOUS", "description": "Hostile witness not yet prepped"},
        ],
        "case_facts": "Test facts",
        "evidence_list": ["knife recovered"],
        "witness_list": ["W1 (hostile)"],
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "recommendations" in data
    assert len(data["recommendations"]) > 0


def test_risk_score_advisory_only(client):
    r = client.post("/api/v1/risk/score", json={
        "case_id": "case-risk-1",
        "case_facts": "POCSO case, weak evidence, 2 hostile witnesses",
        "evidence_strength": "WEAK",
        "witness_count": 3,
        "hostile_witness_count": 2,
        "fsl_status": "overdue",
        "bnss_173_compliant": False,
        "lapses": [{"key": "hostile_witness_no_prep", "tier": "FATAL", "description": "x"}],
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["advisory_only"] is True
    assert data["score"] > 0.5  # high risk expected
    assert data["band"] in ("low", "medium", "high")
    assert "narrative" in data
    assert len(data["contributing_factors"]) > 0


def test_cross_exam_prep_stores_questions_on_witness(client):
    r = client.post("/api/v1/cases", json={"fir_no": "PREP/2026", "district": "test-district"})
    case_id = r.json()["id"]
    w = client.post("/api/v1/witnesses", json={
        "case_id": case_id, "name": "W", "type": "eyewitness", "category": "hostile",
    }).json()
    wid = w["id"]
    r2 = client.post(f"/api/v1/witnesses/{wid}/cross-exam-prep?case_facts=Theft+at+bus+stand&language=en")
    assert r2.status_code == 200
    data = r2.json()
    assert "questions" in data
    assert "brief" in data
    assert len(data["questions"]) > 0
