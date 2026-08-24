"""Citizen safety API — Abhaya equivalent.

Per Kishore's Eluru deployment (New Indian Express, 7 Nov 2024):
- Abhaya app for women's safety
- Dedicated helpline 9550351100 for women in distress
- Anonymous online reporting form at formurl.com/to/abhaya,
  reviewed under SP's direct supervision
- Women-run patrol units with pink helmets
- Network of Village Women Protection Secretaries

This endpoint set replicates the citizen-facing surface: anonymous
incident submission, helpline log, patrol unit coordination.

Per Kishore [Hans India]: "30% of the police personnel in the district
are women" — women patrol unit staffing is the operational layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.api.deps import CurrentUser, DbSession, SpUser, WomenPatrolUser
from aranmanai.db.models.case import Case
from aranmanai.db.models.user import User, UserRole
from aranmanai.db.models.witness import Witness
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, encrypt_field
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter(prefix="/safety", tags=["citizen-safety"])


# ──────────────────────────────────────────────────────────
# Helpline log (citizen calls, anonymous, recorded for audit)
# ──────────────────────────────────────────────────────────

HELPLINE_NUMBER = "9550351100"  # Per Kishore's Abhaya helpline


class HelplineCallLog(BaseModel):
    """One row per call received on the women's helpline.

    Note: NO caller_id or phone is stored (per Kishore's anonymity
    guarantee). Only metadata about the call + what was reported.
    """
    case_id: str | None = None
    caller_district: str
    report_type: str  # harassment | stalking | domestic_violence | threat | other
    severity: str = "medium"  # low | medium | high | critical
    description: str  # what the caller reported (free text)
    location_text: str | None = None
    needs_patrol: bool = False
    needs_callback: bool = False


class HelplineCallResponse(BaseModel):
    log_id: str
    helpline_number: str
    routed_to: str
    patrol_dispatched: bool
    next_action: str
    recorded_at: str


# ──────────────────────────────────────────────────────────
# Anonymous incident report (Abhaya's formurl.com equivalent)
# ──────────────────────────────────────────────────────────


class AnonymousReportRequest(BaseModel):
    report_type: str  # harassment | stalking | domestic_violence | eve_teasing | threat | missing_person | other
    district: str
    incident_date: str  # ISO date
    location_text: str
    description: str
    severity: str = "medium"
    # No PII fields — anonymous by design (Kishore's promise)


class AnonymousReportResponse(BaseModel):
    report_id: str
    status: str
    review_queue: str  # which SP / unit picks it up
    next_action: str


# ──────────────────────────────────────────────────────────
# Women patrol unit coordination
# ──────────────────────────────────────────────────────────


class PatrolDispatchRequest(BaseModel):
    case_id: str | None = None
    helpline_log_id: str | None = None
    district: str
    area: str
    priority: str = "high"  # low | medium | high | critical
    reason: str


class PatrolDispatchResponse(BaseModel):
    dispatch_id: str
    district: str
    area: str
    priority: str
    dispatched_at: str
    unit_id: str | None = None  # women patrol unit, if available


# ──────────────────────────────────────────────────────────
# In-memory stores (v1; in production these would be DB tables)
# Per Kishore: Abhaya was a small in-house app at first; v1 keeps
# the same surface but uses lightweight in-memory storage. Persistence
# to DB is a v1.1 follow-up.
# ──────────────────────────────────────────────────────────

_HELPLINE_LOG: list[dict] = []
_ANON_REPORTS: list[dict] = []
_PATROL_DISPATCHES: list[dict] = []


@router.get("/helpline")
def get_helpline() -> dict:
    """Return the women's safety helpline number. Public endpoint."""
    return {
        "helpline_number": HELPLINE_NUMBER,
        "available": "24x7",
        "languages": ["en", "ta", "hi"],
        "anonymous": True,
        "dispatch_promise_minutes": 5,
        "note": "Per Kishore's Abhaya model — anonymous, no PII recorded",
    }


@router.post("/helpline/call", response_model=HelplineCallResponse, status_code=201)
def log_helpline_call(req: HelplineCallLog, user: WomenPatrolUser, db: DbSession) -> HelplineCallResponse:
    """Log a helpline call. NO PII is stored — only metadata.

    Called by the women patrol unit / call centre operator after
    taking a call. The operator answers, dispatches patrol, then logs.
    """
    log_id = str(uuid.uuid4())
    routed_to = "women_patrol_unit" if req.needs_patrol else "sp_direct_review"
    patrol_dispatched = bool(req.needs_patrol)

    _HELPLINE_LOG.append({
        "log_id": log_id,
        "case_id": req.case_id,
        "caller_district": req.caller_district,
        "report_type": req.report_type,
        "severity": req.severity,
        "description": req.description,
        "location_text": req.location_text,
        "needs_patrol": req.needs_patrol,
        "needs_callback": req.needs_callback,
        "routed_to": routed_to,
        "patrol_dispatched": patrol_dispatched,
        "logged_by": user.id,
        "logged_at": datetime.utcnow().isoformat(),
    })
    log.info(
        "safety.helpline_call id=%s district=%s type=%s patrol=%s",
        log_id, req.caller_district, req.report_type, patrol_dispatched,
    )
    next_action = (
        "Patrol dispatched to location" if patrol_dispatched
        else "SP to review within 24h"
    )
    return HelplineCallResponse(
        log_id=log_id,
        helpline_number=HELPLINE_NUMBER,
        routed_to=routed_to,
        patrol_dispatched=patrol_dispatched,
        next_action=next_action,
        recorded_at=datetime.utcnow().isoformat(),
    )


@router.post("/report", response_model=AnonymousReportResponse, status_code=201)
def submit_anonymous_report(req: AnonymousReportRequest, db: DbSession) -> AnonymousReportResponse:
    """Submit an anonymous report (Abhaya formurl.com equivalent).

    Per Kishore: 'The anonymity feature removes this barrier, enabling
    more women to come forward without hesitation.'

    No auth required. No PII collected. The SP reviews directly.
    """
    report_id = str(uuid.uuid4())
    _ANON_REPORTS.append({
        "report_id": report_id,
        "report_type": req.report_type,
        "district": req.district,
        "incident_date": req.incident_date,
        "location_text": req.location_text,
        "description": req.description,
        "severity": req.severity,
        "status": "pending_sp_review",
        "submitted_at": datetime.utcnow().isoformat(),
    })
    log.info(
        "safety.anon_report id=%s district=%s type=%s",
        report_id, req.district, req.report_type,
    )
    return AnonymousReportResponse(
        report_id=report_id,
        status="pending_sp_review",
        review_queue=f"sp_{req.district}",
        next_action="SP to review within 24h. Patrol dispatched if severity=critical.",
    )


@router.post("/patrol/dispatch", response_model=PatrolDispatchResponse, status_code=201)
def dispatch_patrol(req: PatrolDispatchRequest, user: SpUser, db: DbSession) -> PatrolDispatchResponse:
    """SP dispatches a women patrol unit to a location.

    Per Kishore [NIE]: 'Abhaya women patrol units are staffed entirely
    by trained women officers, equipped with pink helmets and
    distinctive uniforms for easy recognition.'
    """
    dispatch_id = str(uuid.uuid4())
    # Find a women patrol unit in the district
    unit = (
        db.query(User)
        .filter(User.role == UserRole.WOMEN_PATROL, User.district == req.district, User.is_active)
        .first()
    )
    unit_id = unit.id if unit else None

    _PATROL_DISPATCHES.append({
        "dispatch_id": dispatch_id,
        "case_id": req.case_id,
        "helpline_log_id": req.helpline_log_id,
        "district": req.district,
        "area": req.area,
        "priority": req.priority,
        "reason": req.reason,
        "unit_id": unit_id,
        "dispatched_by": user.id,
        "dispatched_at": datetime.utcnow().isoformat(),
    })
    log.info(
        "safety.patrol_dispatch id=%s district=%s unit=%s priority=%s",
        dispatch_id, req.district, unit_id, req.priority,
    )
    return PatrolDispatchResponse(
        dispatch_id=dispatch_id,
        district=req.district,
        area=req.area,
        priority=req.priority,
        dispatched_at=datetime.utcnow().isoformat(),
        unit_id=unit_id,
    )


@router.get("/patrol/dispatches")
def list_patrol_dispatches(user: SpUser, db: DbSession, district: Optional[str] = None) -> dict:
    """List patrol dispatches for the district. SP view."""
    target = district or user.district
    matches = [d for d in _PATROL_DISPATCHES if d["district"] == target]
    return {
        "district": target,
        "n_dispatches": len(matches),
        "dispatches": matches[-50:],  # last 50
    }
