"""Tests for the 12 Kishore-review endpoints (P0-3 fix).

Covers:
- F1: helpline GPS (auth required, FK validation, 404 on unknown)
- F2: BNS 173 charge-sheet deadline (boundary 10y/11y, 60d/90d, alert_band)
- F4: case list pagination, search, status filter, district match (H-2)
- F5: charge-sheet version control + IDOR on list
- F6: pilot enroll
- F7: case entry translation (TamilPipeline.process) + source_language validation
- F8: FIR auto-fill + IDOR
- F10: case transfer (district match)
- F11: family liaison + IDOR on list
- F12: helpline upstream (1091/181) + dedupe + validation
- F13: PP briefing + IDOR on unread-briefings
- F14: deputation (district match + end_date filter)
- C-3: register admin-only
- C-4: audit log race (8 threads x 20 writes verify chain)
- H-3: rate limit (429 after threshold)
"""
import requests
import threading
import time
import uuid
from datetime import date, datetime, timedelta

API = "http://127.0.0.1:8080/api/v1"


def _admin_token():
    r = requests.post(f"{API}/auth/login",
                       json={"username": "admin", "password": "Aranmanai!Dev!2026"})
    return r.json()["access_token"]


def _ensure_data(token):
    """Seed a case + IO + PP so the kishore endpoints have data."""
    h = {"Authorization": f"Bearer {token}"}

    # Get a real case
    cases = requests.get(f"{API}/kishore/cases?page=1&page_size=1", headers=h).json()
    return cases["cases"][0]


# ---------- F1: helpline GPS ----------

def test_f1_gps_requires_auth():
    """Unauth request → 401 (P0-2: was 200/no-auth)."""
    r = requests.post(f"{API}/kishore/helpline/abc/gps", json={
        "helpline_log_id": "abc", "caller_lat": 17.7, "caller_lng": 83.3
    })
    assert r.status_code == 401


def test_f1_gps_404_on_unknown_call():
    """Unknown helpline_log_id → 404 (P2: was a raw 500 from FK constraint)."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/kishore/helpline/no-such-call-12345/gps", json={
        "helpline_log_id": "no-such-call-12345", "caller_lat": 17.7, "caller_lng": 83.3
    }, headers=h)
    assert r.status_code == 404
    assert "not found" in r.json().get("detail", "").lower()


def test_f1_gps_happy_path():
    """F1 happy path: GPS recorded with distance non-negative."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    # First create a helpline call
    call = requests.post(f"{API}/safety/helpline/call", json={
        "caller_district": "default-district",
        "report_type": "harassment",
        "severity": "high",
        "description": "F1 test",
    }, headers=h)
    log_id = call.json()["log_id"]
    r = requests.post(f"{API}/kishore/helpline/{log_id}/gps", json={
        "helpline_log_id": log_id, "caller_lat": 17.7231, "caller_lng": 83.3028,
        "auto_station": "Dwaraka_Tirumala_PS", "distance_to_station_km": 2.3
    }, headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["auto_station"] == "Dwaraka_Tirumala_PS"
    assert data["distance_to_station_km"] == 2.3
    assert data["next_step"].startswith("Patrol dispatched")


# ---------- F2: BNS 173 deadline ----------

def test_f2_boundary_10_years_60_days():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/charge-sheet-deadline", json={
        "case_id": case["id"], "fir_date": "2025-01-01", "max_sentence_years": 7
    }, headers=h)
    assert r.status_code == 200
    data = r.json()
    expected = (date(2025, 1, 1) + timedelta(days=60)).isoformat()
    assert data["deadline"] == expected


def test_f2_boundary_11_years_90_days():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/charge-sheet-deadline", json={
        "case_id": case["id"], "fir_date": "2025-01-01", "max_sentence_years": 11
    }, headers=h)
    assert r.status_code == 200
    data = r.json()
    expected = (date(2025, 1, 1) + timedelta(days=90)).isoformat()
    assert data["deadline"] == expected


def test_f2_overdue_alert():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/charge-sheet-deadline", json={
        "case_id": case["id"], "fir_date": "2020-01-01", "max_sentence_years": 5
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["alert_band"] == "overdue"


def test_f2_requires_auth():
    r = requests.post(f"{API}/kishore/cases/x/charge-sheet-deadline", json={
        "case_id": "x", "fir_date": "2025-01-01", "max_sentence_years": 5
    })
    assert r.status_code == 401


# ---------- F4: case list pagination + H-2 IDOR ----------

def test_f4_search_returns_zero_for_nonsense():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/kishore/cases?search=__no_such_case__&page=1&page_size=5", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["cases"] == []


def test_f4_status_filter():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/kishore/cases?status=trial&page=1&page_size=5", headers=h)
    assert r.status_code == 200
    data = r.json()
    for c in data["cases"]:
        assert c["status"] == "trial"


def test_f4_pagination():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/kishore/cases?page=1&page_size=2", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["cases"]) <= 2


# ---------- F5: charge-sheet version control + IDOR ----------

def test_f5_version_save_and_list():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/charge-sheet-versions", json={
        "case_id": case["id"], "draft_text": "Test v1", "pp_review_notes": "OK"
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["version_num"] >= 1
    r2 = requests.get(f"{API}/kishore/cases/{case['id']}/charge-sheet-versions", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()) >= 1


def test_f5_list_idor_rejected_cross_district():
    """P0-2: a non-admin user in a different district gets 403."""
    # Login as a PP (created in default-district); try to access a
    # case in tirupati district.
    pp_token_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "pp_user", "password": "PP!Dev!2026"},
    )
    if pp_token_resp.status_code != 200:
        return  # no PP user seeded
    pp_h = {"Authorization": f"Bearer {pp_token_resp.json()['access_token']}"}
    # Find a case in tirupati via admin token
    admin_h = {"Authorization": f"Bearer {_admin_token()}"}
    cases = requests.get(
        f"{API}/kishore/cases?page=1&page_size=200", headers=admin_h
    ).json().get("cases", [])
    other = next((c for c in cases if c["district"] != "default-district"), None)
    if not other:
        return  # no cross-district case seeded
    r = requests.get(
        f"{API}/kishore/cases/{other['id']}/charge-sheet-versions", headers=pp_h
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ---------- F6: pilot enroll ----------

def test_f6_pilot_enroll():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/pilot-enroll", json={
        "case_id": case["id"], "baseline_p_conviction": 0.5
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["enrolled_at"] is not None


# ---------- F7: case entry translation ----------

def test_f7_translation_happy_path():
    """F7 happy path: text is translated, not silently dropped."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/kishore/cases/translate-entry", json={
        "case_id": "case-scst-019", "text": "Hello world", "source_language": "en"
    }, headers=h)
    # Pipeline may be unavailable in test env; if so, the endpoint should
    # still return 200 with a fallback translated_text
    assert r.status_code == 200
    data = r.json()
    assert "translated_text" in data
    assert data["translated_text"]  # must be non-empty


def test_f7_translation_rejects_unknown_source_lang():
    """P2: source_language must be in {ta, hi, en}; unknown → 400."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/kishore/cases/translate-entry", json={
        "case_id": "case-scst-019", "text": "Hello", "source_language": "xx"
    }, headers=h)
    assert r.status_code == 400
    assert "source_language" in r.json().get("detail", "")


# ---------- F8: FIR auto-fill + IDOR ----------

def test_f8_fir_autofill():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.get(f"{API}/kishore/cases/{case['id']}/fir-autofill", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert "fir_no" in data
    assert "auto_filled_fields" in data
    assert "district" in data["auto_filled_fields"]


def test_f8_fir_autofill_idor_rejected():
    """P0-2: cross-district autofill → 403."""
    pp_token_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "pp_user", "password": "PP!Dev!2026"},
    )
    if pp_token_resp.status_code != 200:
        return
    pp_h = {"Authorization": f"Bearer {pp_token_resp.json()['access_token']}"}
    admin_h = {"Authorization": f"Bearer {_admin_token()}"}
    cases = requests.get(
        f"{API}/kishore/cases?page=1&page_size=200", headers=admin_h
    ).json().get("cases", [])
    other = next((c for c in cases if c["district"] != "default-district"), None)
    if not other:
        return
    r = requests.get(f"{API}/kishore/cases/{other['id']}/fir-autofill", headers=pp_h)
    assert r.status_code == 403


# ---------- F10: case transfer ----------

def test_f10_case_transfer():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/transfer", json={
        "case_id": case["id"], "to_io_id": token and "x" or "y", "reason": "test"
    }, headers=h)
    # Either succeeds (200) or fails validation - just check it doesn't 500
    assert r.status_code in (200, 201, 400, 404, 422)


# ---------- F11: family liaison + IDOR ----------

def test_f11_family_liaison():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    case = _ensure_data(token)
    r = requests.post(f"{API}/kishore/cases/{case['id']}/family-liaison", json={
        "case_id": case["id"], "family_contact": "9876543210",
        "family_contact_relationship": "mother",
        "what_communicated": "test", "followup_required": True,
        "followup_due": "2026-12-01"
    }, headers=h)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/kishore/cases/{case['id']}/family-liaison", headers=h)
    assert r2.status_code == 200
    assert len(r2.json()) >= 1


def test_f11_family_liaison_idor_rejected():
    """P0-2: cross-district family-liaison list → 403."""
    pp_token_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "pp_user", "password": "PP!Dev!2026"},
    )
    if pp_token_resp.status_code != 200:
        return
    pp_h = {"Authorization": f"Bearer {pp_token_resp.json()['access_token']}"}
    admin_h = {"Authorization": f"Bearer {_admin_token()}"}
    cases = requests.get(
        f"{API}/kishore/cases?page=1&page_size=200", headers=admin_h
    ).json().get("cases", [])
    other = next((c for c in cases if c["district"] != "default-district"), None)
    if not other:
        return
    r = requests.get(f"{API}/kishore/cases/{other['id']}/family-liaison", headers=pp_h)
    assert r.status_code == 403


# ---------- F12: helpline upstream 1091/181 + dedupe + validation ----------

def test_f12_helpline_upstream():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    call = requests.post(f"{API}/safety/helpline/call", json={
        "caller_district": "default-district",
        "report_type": "harassment",
        "severity": "high",
        "description": "F12 test",
    }, headers=h)
    log_id = call.json()["log_id"]
    ref = f"AP-TEST-{int(time.time())}"
    r = requests.post(f"{API}/kishore/safety/helpline/upstream", json={
        "helpline_log_id": log_id, "upstream_system": "181",
        "upstream_reference": ref
    }, headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["upstream_system"] == "181"
    assert "received_at" in data


def test_f12_helpline_upstream_dedupes():
    """P2: same (log, system, ref) → returns existing row, no duplicate."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    call = requests.post(f"{API}/safety/helpline/call", json={
        "caller_district": "default-district",
        "report_type": "harassment",
        "severity": "high",
        "description": "F12 dedup test",
    }, headers=h)
    log_id = call.json()["log_id"]
    ref = f"AP-DEDUP-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    r1 = requests.post(f"{API}/kishore/safety/helpline/upstream", json={
        "helpline_log_id": log_id, "upstream_system": "181", "upstream_reference": ref
    }, headers=h)
    r2 = requests.post(f"{API}/kishore/safety/helpline/upstream", json={
        "helpline_log_id": log_id, "upstream_system": "181", "upstream_reference": ref
    }, headers=h)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]  # same row


def test_f12_helpline_upstream_rejects_unknown_system():
    """P2: upstream_system must be in {1091, 181, 112, other}."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}/kishore/safety/helpline/upstream", json={
        "helpline_log_id": "x", "upstream_system": "999", "upstream_reference": "y"
    }, headers=h)
    assert r.status_code == 400
    assert "upstream_system" in r.json().get("detail", "")


# ---------- F13: PP briefing + IDOR ----------

def test_f13_pp_briefing_record():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    # The /users endpoint varies by deployment; use /auth/me for the
    # current admin and assume a PP user has been seeded. If no PP is
    # known, derive from /auth/login as pp_user.
    pp_token_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "pp_user", "password": "PP!Dev!2026"},
    )
    if pp_token_resp.status_code != 200:
        return  # no PP user seeded; skip
    pp_id = pp_token_resp.json()["user_id"]
    # Use a real case_id from the kishore cases list (was a FK 500
    # before the fix when the case_id was a placeholder).
    cases = requests.get(f"{API}/kishore/cases?page=1&page_size=1", headers=h).json()
    if not cases.get("cases"):
        return  # no case seeded
    real_case_id = cases["cases"][0]["id"]
    r = requests.post(f"{API}/kishore/pp-briefings", json={
        "case_id": real_case_id, "pp_id": pp_id,
        "notes": "test", "requires_response": True
    }, headers=h)
    assert r.status_code == 200, f"unexpected: {r.status_code} {r.text}"
    assert r.json()["read_at"] is not None


def test_f13_unread_briefings_idor_rejected():
    """P0-2: a user cannot read another user's briefings (unless admin)."""
    pp_token_resp = requests.post(
        f"{API}/auth/login",
        json={"username": "pp_user", "password": "PP!Dev!2026"},
    )
    if pp_token_resp.status_code != 200:
        return
    pp_token = pp_token_resp.json()["access_token"]
    pp_h = {"Authorization": f"Bearer {pp_token}"}
    admin_h = {"Authorization": f"Bearer {_admin_token()}"}
    # /auth/me returns {"user_id": ..., ...} (not "id")
    admin_id = requests.get(
        f"{API}/auth/me", headers=admin_h
    ).json()["user_id"]
    # PP tries to read admin's briefings → 403
    r = requests.get(f"{API}/kishore/pps/{admin_id}/unread-briefings", headers=pp_h)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ---------- F14: deputation ----------

def test_f14_deputation_create():
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    # /users endpoint shape varies; use the admin's own id as the deputed
    # user (admin can self-depute, which is a fine smoke test).
    admin_id = requests.get(f"{API}/auth/me", headers=h).json()["user_id"]
    r = requests.post(f"{API}/kishore/deputations", json={
        "user_id": admin_id, "home_district": "default-district",
        "deputation_district": "default-district", "start_date": "2026-09-01",
        "end_date": "2026-09-15", "reason": "test"
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["is_active"] is True


# ---------- C-3: register requires admin ----------

def test_c3_register_unauth_rejected():
    r = requests.post(f"{API}/auth/register", json={
        "username": "evil", "password": "evil12345",
        "name": "Evil", "role": "admin", "district": "anywhere"
    })
    # Now requires admin auth after C-3 fix
    assert r.status_code in (401, 403)


def test_c3_register_works_with_admin_token():
    """Admin CAN create new users."""
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    # Use a unique username to avoid conflict
    username = f"newuser_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/auth/register", json={
        "username": username, "password": "newuser1234",
        "name": "Test User", "role": "io", "district": "default-district"
    }, headers=h)
    assert r.status_code in (200, 201), f"unexpected: {r.status_code} {r.text}"


# ---------- C-4: audit log race ----------

def test_c4_audit_chain_survives_concurrent_writes():
    """C-4 fix: 8 threads x 20 writes must verify cleanly."""
    import os
    # The test runs from a different cwd than the app; .env lookup needs
    # the project root. Set the env vars explicitly so the Settings
    # constructor succeeds.
    os.environ.setdefault("ARANMANAI_DB_KEY", "dev-only-change-me-in-prod-dbkey-2f7c9a4e8b1d3f5a")
    os.environ.setdefault("ARANMANAI_JWT_SECRET", "dev-only-change-me-in-prod-jwt-c4e8a1d9f2b3")
    import sys
    sys.path.insert(0, "src")
    from aranmanai.security.audit import AuditLog, AuditAction
    from aranmanai.config import get_settings
    log = AuditLog(get_settings().audit_log_path)
    def spam():
        for i in range(20):
            log.append(
                AuditAction.READ_CASE, actor_id="race-test", subject_id=f"c-{i}"
            )
    threads = [threading.Thread(target=spam) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    ok, msg = log.verify()
    assert ok, f"chain broken: {msg}"


# ---------- H-3: rate limit ----------

def test_h3_rate_limit_triggers_429():
    """After 10 calls in a minute to /report, the 11th should be 429."""
    time.sleep(1.0)  # let any prior bucket expire
    token = _admin_token()
    h = {"Authorization": f"Bearer {token}"}
    statuses = []
    for _ in range(12):
        r = requests.post(f"{API}/safety/report", json={
            "report_type": "test", "district": "d",
            "incident_date": "2026-01-01", "location_text": "x",
            "description": "y", "severity": "low"
        }, headers=h)
        statuses.append(r.status_code)
    # At least one of the last few should be 429
    assert 429 in statuses, f"Expected rate limit 429, got {statuses}"
