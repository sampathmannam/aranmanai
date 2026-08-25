"""Pilot tracker API: conviction-rate measurement endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aranmanai.ai.services.pilot_tracker import PilotTrackerService
from aranmanai.api.deps import DbSession, SpUser
from aranmanai.config import get_settings
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog

log = get_logger(__name__)
router = APIRouter(prefix="/pilot", tags=["pilot"])


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


# ─── Request/Response models ──────────────────────────────────────

class PilotEnrollRequest(BaseModel):
    case_id: str
    baseline_p_conviction: float | None = None
    baseline_offence: str | None = None
    baseline_court: str | None = None
    baseline_lapse_count: int | None = None
    baseline_fatal_lapse_count: int | None = None
    notes: str | None = None


class PilotCureRequest(BaseModel):
    lapse_key: str
    cure_action: str


class PilotMidReviewRequest(BaseModel):
    post_p_conviction: float | None = None
    post_lapse_count: int | None = None
    post_fatal_lapse_count: int | None = None
    post_hostile_witnesses: int | None = None
    notes: str | None = None


class PilotCloseRequest(BaseModel):
    outcome: str  # convicted | acquitted | compromised | pending
    outcome_date: str | None = None
    sentence: str | None = None
    notes: str | None = None


class PilotMetricsResponse(BaseModel):
    n_enrolled: int
    n_closed: int
    n_pending: int
    n_convicted: int
    n_acquitted: int
    n_compromised: int
    conviction_rate: float | None
    conviction_rate_baseline: float | None
    delta_conviction_rate: float | None
    delta_p_conviction_avg: float | None
    hostile_reduction_avg: float | None
    cases: list[dict]


# ─── Endpoints ───────────────────────────────────────────────────

@router.post("/enroll", status_code=201)
def enroll_case(req: PilotEnrollRequest, user: SpUser, db: DbSession) -> dict:
    """Enroll a case in the conviction-rate pilot."""
    svc = PilotTrackerService(db)
    try:
        pc = svc.enroll(
            case_id=req.case_id,
            district=user.district,
            enrolled_by=user.id,
            baseline_p_conviction=req.baseline_p_conviction,
            baseline_offence=req.baseline_offence,
            baseline_court=req.baseline_court,
            baseline_lapse_count=req.baseline_lapse_count,
            baseline_fatal_lapse_count=req.baseline_fatal_lapse_count,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    _audit().append(
        AuditAction.CREATE_WITNESS,  # reuse — no specific enum
        actor_id=user.id,
        subject_id=pc.id,
        metadata={"case_id": req.case_id, "pilot": True},
    )
    log.info("pilot.enroll case_id=%s", req.case_id)
    return {"status": "enrolled", "pilot_case_id": pc.id, "case_id": pc.case_id}


@router.post("/{pilot_case_id}/cure")
def apply_cure(pilot_case_id: str, req: PilotCureRequest, user: SpUser, db: DbSession) -> dict:
    """Record an Aranmanai cure applied to a pilot case."""
    svc = PilotTrackerService(db)
    try:
        pc = svc.apply_cure(pilot_case_id, req.lapse_key, req.cure_action)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"status": "ok", "pilot_case_id": pc.id, "n_cures": len(pc.cures_applied)}


@router.post("/{pilot_case_id}/mid-review")
def mid_review(pilot_case_id: str, req: PilotMidReviewRequest, user: SpUser, db: DbSession) -> dict:
    """Record mid-pilot review after first hearing cycle."""
    svc = PilotTrackerService(db)
    try:
        pc = svc.mid_review(
            pilot_case_id,
            post_p_conviction=req.post_p_conviction,
            post_lapse_count=req.post_lapse_count,
            post_fatal_lapse_count=req.post_fatal_lapse_count,
            post_hostile_witnesses=req.post_hostile_witnesses,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "status": "ok",
        "pilot_case_id": pc.id,
        "mid_review_at": pc.mid_review_at.isoformat() if pc.mid_review_at else None,
    }


@router.post("/{pilot_case_id}/close")
def close_case(pilot_case_id: str, req: PilotCloseRequest, user: SpUser, db: DbSession) -> dict:
    """Close a pilot case with final outcome."""
    svc = PilotTrackerService(db)
    try:
        outcome_date = datetime.fromisoformat(req.outcome_date) if req.outcome_date else None
        pc = svc.close_case(
            pilot_case_id,
            outcome=req.outcome,
            outcome_date=outcome_date,
            sentence=req.sentence,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"status": "closed", "pilot_case_id": pc.id, "outcome": pc.outcome}


@router.get("/metrics", response_model=PilotMetricsResponse)
def get_metrics(user: SpUser, db: DbSession, district: str | None = None) -> PilotMetricsResponse:
    """Get aggregate pilot metrics for the district (or all if admin)."""
    svc = PilotTrackerService(db)
    m = svc.get_metrics(district=district or user.district)
    return PilotMetricsResponse(
        n_enrolled=m.n_enrolled,
        n_closed=m.n_closed,
        n_pending=m.n_pending,
        n_convicted=m.n_convicted,
        n_acquitted=m.n_acquitted,
        n_compromised=m.n_compromised,
        conviction_rate=m.conviction_rate,
        conviction_rate_baseline=m.conviction_rate_baseline,
        delta_conviction_rate=m.delta_conviction_rate,
        delta_p_conviction_avg=m.delta_p_conviction_avg,
        hostile_reduction_avg=m.hostile_reduction_avg,
        cases=m.cases,
    )
