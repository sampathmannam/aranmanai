"""CMC loop API endpoints — the operational coordination that moves conviction rate.

These are the endpoints Kishore Kommi's CMC ran on. Without them,
Aranmanai is a dashboard. With them, it's an accountability machine.

Endpoints:
- POST /cmc/meeting                        - SP opens morning meeting
- POST /cmc/meeting/{id}/action            - SP assigns an action to IO/PP
- PATCH /cmc/action/{id}/answer            - IO/PP reports back
- PATCH /cmc/action/{id}/pp-answer         - PP answers (separate from IO)
- PATCH /cmc/action/{id}/sp-reviewed       - SP signs off on the answer
- POST /cmc/sweep                          - cron: mark overdue + raise escalations
- PATCH /cmc/escalation/{id}/acknowledge
- PATCH /cmc/escalation/{id}/resolve
- POST /cmc/sp-review                      - SP per-case sign-off (every morning)
- GET  /cmc/daily-view                     - the morning CMC view
- POST /cmc/constable/record-performance   - auto-compute constable KPIs
- POST /cmc/constable/commend              - cash reward + commendation
- POST /cmc/constable/penalize             - warning/memo/transfer
- GET  /cmc/dsp-weekly-rollup               - DSP station-by-station review
- GET  /cmc/pilot-metrics                  - conviction rate + delta
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aranmanai.ai.services.cmc_loop import CmcLoopService
from aranmanai.api.deps import DbSession, DspUser, IoUser, PpUser, SpUser
from aranmanai.config import get_settings
from aranmanai.core.time_utils import local_today
from aranmanai.db.models.coordination import (
    ActionItem,
    ActionPriority,
    ActionStatus,
)
from aranmanai.db.models.user import UserRole
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog

log = get_logger(__name__)
router = APIRouter(prefix="/cmc", tags=["cmc-loop"])


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


# ──────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────

class CmcMeetingRequest(BaseModel):
    meeting_date: str | None = None
    attendees: list[str] = []
    minutes: str | None = None


class CmcMeetingResponse(BaseModel):
    meeting_id: str
    district: str
    meeting_date: str
    held_by: str
    attendees: list[str]
    n_actions: int


class CmcActionAssignRequest(BaseModel):
    case_id: str
    description: str
    action_type: str
    assigned_to: str
    assigned_role: str
    due_date: str
    priority: ActionPriority = ActionPriority.HIGH


class CmcActionAnswerRequest(BaseModel):
    answer: str
    answer_detail: str | None = None


class CmcPpAnswerRequest(BaseModel):
    answer: str  # ready | not_ready | needs_evidence | blocked
    answer_detail: str | None = None
    evidence_needed: list[str] = []


class CmcEscalationAcknowledgeRequest(BaseModel):
    note: str | None = None


class CmcEscalationResolveRequest(BaseModel):
    note: str


class CmcSpReviewRequest(BaseModel):
    case_id: str
    review_date: str | None = None
    status: str = "reviewed"
    notes: str | None = None


class CmcSweepResponse(BaseModel):
    n_marked_overdue: int
    n_escalations_raised: int


class CmcDailyViewResponse(BaseModel):
    date: str
    district: str
    n_hearings: int
    n_actions_pending: int
    n_actions_overdue: int
    n_actions_answered_yesterday: int
    n_escalations_open: int
    n_cases_unreviewed: int
    hearings: list[dict]
    overdue_actions: list[dict]
    open_escalations: list[dict]
    top_priority: list[dict]
    sp_signoff_status: dict


class ConstableRecordPerformanceRequest(BaseModel):
    constable_id: str
    period_month: str  # YYYY-MM


class ConstableCommendRequest(BaseModel):
    performance_id: str
    cash_reward_amount: int = 0
    issue_certificate: bool = True
    reason: str | None = None


class ConstablePenalizeRequest(BaseModel):
    performance_id: str
    action_type: str  # warning | memo | transfer
    reason: str


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────

@router.post("/meeting", response_model=CmcMeetingResponse, status_code=201)
def open_meeting(req: CmcMeetingRequest, user: SpUser, db: DbSession) -> CmcMeetingResponse:
    svc = CmcLoopService(db)
    meeting_date = datetime.fromisoformat(req.meeting_date) if req.meeting_date else datetime.utcnow()
    m = svc.open_meeting(
        district=user.district,
        meeting_date=meeting_date,
        held_by=user.id,
        attendees=req.attendees,
        minutes=req.minutes,
    )
    n_actions = db.query(ActionItem).filter(ActionItem.meeting_id == m.id).count()
    _audit().append(
        AuditAction.CREATE_WITNESS,
        actor_id=user.id,
        subject_id=m.id,
        metadata={"action": "cmc_open_meeting", "n_attendees": len(req.attendees)},
    )
    return CmcMeetingResponse(
        meeting_id=m.id,
        district=m.district,
        meeting_date=m.meeting_date.isoformat(),
        held_by=m.held_by,
        attendees=m.attendees or [],
        n_actions=n_actions,
    )


@router.post("/meeting/{meeting_id}/action", status_code=201)
def assign_action(meeting_id: str, req: CmcActionAssignRequest, user: SpUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    a = svc.assign_action(
        meeting_id=meeting_id,
        case_id=req.case_id,
        description=req.description,
        action_type=req.action_type,
        assigned_to=req.assigned_to,
        assigned_role=req.assigned_role,
        due_date=datetime.fromisoformat(req.due_date),
        priority=req.priority,
    )
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=a.id,
        metadata={"action": "cmc_assign", "case_id": req.case_id, "assigned_to": req.assigned_to},
    )
    log.info("cmc.action_assigned case=%s action=%s by=%s", req.case_id, a.id, user.id)
    return {
        "action_id": a.id,
        "status": a.status.value,
        "due_date": a.due_date.isoformat(),
        "priority": a.priority.value,
    }


@router.patch("/action/{action_id}/answer")
def answer_action(action_id: str, req: CmcActionAnswerRequest, user: IoUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    try:
        a = svc.answer_action(
            action_id=action_id,
            answer=req.answer,
            answer_detail=req.answer_detail,
            answered_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=action_id,
        metadata={"action": "cmc_answer", "answer": req.answer},
    )
    return {
        "action_id": a.id,
        "status": a.status.value,
        "answer": a.answer,
        "answered_at": a.answered_at.isoformat() if a.answered_at else None,
    }


@router.patch("/action/{action_id}/pp-answer")
def pp_answer_action(action_id: str, req: CmcPpAnswerRequest, user: PpUser, db: DbSession) -> dict:
    """Public prosecutor answers the CMC action — separate from the IO's answer.

    Per Kishore: PPs and IOs are both answerable. Their timelines are
    tracked separately so neither can hide behind the other.
    """
    svc = CmcLoopService(db)
    try:
        ans = svc.pp_answer(
            action_id=action_id,
            pp_id=user.id,
            answer=req.answer,
            answer_detail=req.answer_detail,
            evidence_needed=req.evidence_needed,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=action_id,
        metadata={"action": "cmc_pp_answer", "answer": req.answer},
    )
    return {
        "action_id": ans.action_id,
        "pp_id": ans.pp_id,
        "answer": ans.answer,
        "evidence_needed": ans.evidence_needed,
        "answered_at": ans.answered_at.isoformat(),
    }


@router.patch("/action/{action_id}/sp-reviewed")
def sp_review_action(action_id: str, user: SpUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    try:
        a = svc.mark_sp_reviewed(action_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "action_id": a.id,
        "sp_reviewed": a.sp_reviewed,
        "sp_reviewed_at": a.sp_reviewed_at.isoformat() if a.sp_reviewed_at else None,
    }


@router.post("/sweep", response_model=CmcSweepResponse)
def sweep_overdue(user: SpUser, db: DbSession) -> CmcSweepResponse:
    svc = CmcLoopService(db)
    n_overdue_before = db.query(ActionItem).filter(ActionItem.status == ActionStatus.OVERDUE).count()
    n_esc = svc.check_overdue()
    n_overdue_after = db.query(ActionItem).filter(ActionItem.status == ActionStatus.OVERDUE).count()
    n_marked = n_overdue_after - n_overdue_before
    return CmcSweepResponse(n_marked_overdue=n_marked, n_escalations_raised=n_esc)


@router.patch("/escalation/{escalation_id}/acknowledge")
def acknowledge_escalation(escalation_id: str, req: CmcEscalationAcknowledgeRequest, user: IoUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    try:
        e = svc.acknowledge_escalation(escalation_id, note=req.note)
    except ValueError as ex:
        raise HTTPException(404, str(ex)) from ex
    return {"escalation_id": e.id, "status": e.status.value}


@router.patch("/escalation/{escalation_id}/resolve")
def resolve_escalation(escalation_id: str, req: CmcEscalationResolveRequest, user: SpUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    try:
        e = svc.resolve_escalation(escalation_id, note=req.note)
    except ValueError as ex:
        raise HTTPException(404, str(ex)) from ex
    return {
        "escalation_id": e.id,
        "status": e.status.value,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
    }


@router.post("/sp-review", status_code=201)
def sp_review_case(req: CmcSpReviewRequest, user: SpUser, db: DbSession) -> dict:
    svc = CmcLoopService(db)
    review_date = _date.fromisoformat(req.review_date) if req.review_date else local_today()
    r = svc.sp_review_case(
        case_id=req.case_id,
        sp_id=user.id,
        review_date=review_date,
        status=req.status,
        notes=req.notes,
    )
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=r.id,
        metadata={"action": "cmc_sp_review", "status": req.status},
    )
    return {
        "review_id": r.id,
        "case_id": r.case_id,
        "review_date": r.review_date.isoformat(),
        "status": r.status,
        "action_count": r.action_count,
        "overdue_action_count": r.overdue_action_count,
    }


@router.get("/daily-view", response_model=CmcDailyViewResponse)
def daily_view(user: SpUser, db: DbSession, target_date: str | None = None) -> CmcDailyViewResponse:
    svc = CmcLoopService(db)
    target = _date.fromisoformat(target_date) if target_date else local_today()
    v = svc.daily_view(district=user.district, target_date=target)
    return CmcDailyViewResponse(
        date=v.date,
        district=v.district,
        n_hearings=v.n_hearings,
        n_actions_pending=v.n_actions_pending,
        n_actions_overdue=v.n_actions_overdue,
        n_actions_answered_yesterday=v.n_actions_answered_yesterday,
        n_escalations_open=v.n_escalations_open,
        n_cases_unreviewed=v.n_cases_unreviewed,
        hearings=v.hearings,
        overdue_actions=v.overdue_actions,
        open_escalations=v.open_escalations,
        top_priority=v.top_priority,
        sp_signoff_status=v.sp_signoff_status,
    )


# ──────────────────────────────────────────────────────────
# Court constable personnel loop
# ──────────────────────────────────────────────────────────

@router.post("/constable/record-performance", status_code=201)
def constable_record_performance(req: ConstableRecordPerformanceRequest, user: SpUser, db: DbSession) -> dict:
    """Auto-compute constable's monthly performance from hearing data."""
    svc = CmcLoopService(db)
    perf = svc.record_constable_performance(
        constable_id=req.constable_id,
        district=user.district,
        period_month=req.period_month,
    )
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=perf.id,
        metadata={"action": "constable_record_performance", "constable_id": req.constable_id, "month": req.period_month},
    )
    return {
        "performance_id": perf.id,
        "constable_id": perf.constable_id,
        "period_month": perf.period_month,
        "hearings_attended": perf.hearings_attended,
        "witnesses_produced": perf.witnesses_produced,
        "witness_production_rate": round(perf.witness_production_rate, 4),
        "on_time_pct": round(perf.on_time_pct, 4),
        "excellence_flag": perf.excellence_flag,
        "negligence_flag": perf.negligence_flag,
    }


@router.post("/constable/commend")
def constable_commend(req: ConstableCommendRequest, user: SpUser, db: DbSession) -> dict:
    """Award a constable: cash reward + commendation certificate.

    Per Kishore: 'court constables who show excellence in their duties
    will be rewarded with cash and commendation certificates'.
    """
    svc = CmcLoopService(db)
    try:
        perf = svc.commend_constable(
            performance_id=req.performance_id,
            commended_by=user.id,
            cash_reward_amount=req.cash_reward_amount,
            issue_certificate=req.issue_certificate,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=perf.id,
        metadata={"action": "constable_commend", "cash": req.cash_reward_amount, "cert": req.issue_certificate},
    )
    return {
        "performance_id": perf.id,
        "constable_id": perf.constable_id,
        "excellence_flag": perf.excellence_flag,
        "cash_reward_amount": perf.cash_reward_amount,
        "commendation_certificate": perf.commendation_certificate,
        "commended_by": perf.commended_by,
        "commended_at": perf.commended_at.isoformat() if perf.commended_at else None,
    }


@router.post("/constable/penalize")
def constable_penalize(req: ConstablePenalizeRequest, user: SpUser, db: DbSession) -> dict:
    """Penalize a constable: warning / memo / transfer.

    Per Kishore: 'any negligence in duty would result in action'.
    """
    svc = CmcLoopService(db)
    try:
        perf = svc.penalize_constable(
            performance_id=req.performance_id,
            actioned_by=user.id,
            action_type=req.action_type,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=perf.id,
        metadata={"action": "constable_penalize", "action_type": req.action_type, "reason": req.reason},
    )
    return {
        "performance_id": perf.id,
        "constable_id": perf.constable_id,
        "negligence_flag": perf.negligence_flag,
        "action_taken": perf.action_taken,
        "action_taken_by": perf.action_taken_by,
        "action_taken_at": perf.action_taken_at.isoformat() if perf.action_taken_at else None,
    }


# ──────────────────────────────────────────────────────────
# DSP weekly rollup
# ──────────────────────────────────────────────────────────

@router.get("/dsp-weekly-rollup")
def dsp_weekly_rollup(user: DspUser, db: DbSession, week_start: str | None = None) -> dict:
    """DSP-level weekly review: one row per police station in district.

    Per The Hindu [11]: IGP directed DSPs to review cases station-wise
    every week. This endpoint is the rollup above the SP's daily view.
    """
    svc = CmcLoopService(db)
    week_start_date = _date.fromisoformat(week_start) if week_start else local_today()
    # Roll back to Monday
    week_start_date = week_start_date - timedelta(days=week_start_date.weekday())
    return svc.dsp_weekly_rollup(district=user.district, week_start=week_start_date)


# ──────────────────────────────────────────────────────────
# Pilot conviction rate measurement
# ──────────────────────────────────────────────────────────

@router.get("/pilot-metrics")
def pilot_metrics(user: SpUser, db: DbSession, district: str | None = None) -> dict:
    """Conviction rate + delta vs baseline for the pilot.

    Returns the actual conviction rate from closed pilot cases plus
    the delta against the baseline p_conviction captured at enrollment.
    This is the endpoint that proves whether the system moved the rate.

    H-2 fix (IDOR): a non-admin SP can only read their own district's
    metrics. Passing district=<other-district> was a cross-district
    read of conviction-rate data. Same pattern as list_patrol_dispatches
    in safety.py.
    """
    target = district or user.district
    if user.role != UserRole.ADMIN.value and target != user.district:
        raise HTTPException(
            status_code=403,
            detail="SPs can only view their own district's pilot metrics",
        )
    svc = CmcLoopService(db)
    return svc.pilot_conviction_metrics(district=target)
