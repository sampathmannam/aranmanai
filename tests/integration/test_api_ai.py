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


def _last_audit_metadata(tmp_env, action_value: str) -> dict:
    """Read the most recent audit-log entry for a given action. Used to
    verify elapsed_seconds was actually persisted, not just returned in
    the API response.
    """
    from aranmanai.security import AuditLog
    log = AuditLog(tmp_env / "audit.log")
    for entry in log.tail(50):
        if entry["action"] == action_value:
            return entry["metadata"]
    raise AssertionError(f"no audit entry found for action={action_value}")


def test_fir_draft_reports_real_elapsed_seconds(client, tmp_env):
    """Month-3 milestone instrumentation: fir-draft must report genuine
    wall-clock time spent in the AI-generation call, in both the API
    response and the audit-log metadata (mock LLM — no real inference
    time, but the timer itself is real perf_counter() wall-clock).
    """
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
    assert "elapsed_seconds" in data
    assert isinstance(data["elapsed_seconds"], float)
    assert data["elapsed_seconds"] > 0.0
    assert data["elapsed_seconds"] < 5.0  # mock LLM — should be near-instant, never fabricated

    metadata = _last_audit_metadata(tmp_env, "ai.fir_draft")
    assert metadata["elapsed_seconds"] == data["elapsed_seconds"]


def test_chargesheet_draft_reports_real_elapsed_seconds(client, tmp_env):
    r = client.post("/api/v1/ai/chargesheet-draft", json={
        "case_id": "case-1",
        "fir_no": "123/2026",
        "court": "District Court, Chengalpattu",
        "accused_name": "Accused A",
        "accused_address": "Some address",
        "arrest_date": "2026-08-01",
        "sections_bns": ["BNS 308"],
        "facts": "Facts of the case.",
        "evidence_summary": "Knife recovered.",
        "witness_summary": "2 eyewitnesses.",
        "io_name": "IO S. Krishnan",
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "elapsed_seconds" in data
    assert data["elapsed_seconds"] > 0.0

    metadata = _last_audit_metadata(tmp_env, "ai.chargesheet_draft")
    assert metadata["elapsed_seconds"] == data["elapsed_seconds"]


def test_case_diary_draft_reports_real_elapsed_seconds(client, tmp_env):
    r = client.post("/api/v1/ai/case-diary-draft", json={
        "case_id": "case-1",
        "fir_no": "123/2026",
        "io_name": "IO S. Krishnan",
        "date": "2026-08-15",
        "progress_notes": "Visited scene, recorded statements.",
        "investigation_steps": "Scene visit, witness statements.",
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "elapsed_seconds" in data
    assert data["elapsed_seconds"] > 0.0

    metadata = _last_audit_metadata(tmp_env, "ai.fir_draft")  # case-diary reuses this enum
    assert metadata["elapsed_seconds"] == data["elapsed_seconds"]


def test_investigation_recommendations_reports_real_elapsed_seconds(client, tmp_env):
    r = client.post("/api/v1/ai/investigation-recommendations", json={
        "case_id": "case-1",
        "lapses": [
            {"key": "fir_delay_unexplained", "tier": "FATAL", "description": "FIR filed 5 days after incident"},
        ],
        "case_facts": "Test facts",
        "evidence_list": ["knife recovered"],
        "witness_list": ["W1 (hostile)"],
        "language": "en",
    })
    assert r.status_code == 200
    data = r.json()
    assert "elapsed_seconds" in data
    assert data["elapsed_seconds"] > 0.0

    metadata = _last_audit_metadata(tmp_env, "ai.investigation_recommendations")
    assert metadata["elapsed_seconds"] == data["elapsed_seconds"]


def test_cross_exam_prep_reports_real_elapsed_seconds(client, tmp_env):
    r = client.post("/api/v1/cases", json={"fir_no": "TIMING/2026", "district": "test-district"})
    case_id = r.json()["id"]
    w = client.post("/api/v1/witnesses", json={
        "case_id": case_id, "name": "W", "type": "eyewitness", "category": "hostile",
    }).json()
    wid = w["id"]
    r2 = client.post(f"/api/v1/witnesses/{wid}/cross-exam-prep?case_facts=Theft+at+bus+stand&language=en")
    assert r2.status_code == 200
    data = r2.json()
    assert "elapsed_seconds" in data
    assert data["elapsed_seconds"] > 0.0

    metadata = _last_audit_metadata(tmp_env, "ai.cross_exam_prep")
    assert metadata["elapsed_seconds"] == data["elapsed_seconds"]


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
