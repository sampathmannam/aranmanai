"""CMC loop API endpoints — the operational coordination that moves conviction rate.

These are the endpoints Kishore Kommi's CMC ran on. Without them,
Aranmanai is a dashboard. With them, it's an accountability machine.

Endpoints:
- POST /cmc/meeting                        - SP opens morning meeting
- POST /cmc/meeting/{id}/action            - SP assigns an action to IO/PP
- PATCH /cmc/action/{id}/answer            - IO/PP reports back
- PATCH /cmc/action/{id}/sp-reviewed       - SP signs off on the answer
- POST /cmc/sweep                          - cron: mark overdue + raise escalations
- PATCH /cmc/escalation/{id}/acknowledge
- PATCH /cmc/escalation/{id}/resolve
- POST /cmc/sp-review                      - SP per-case sign-off (every morning)
- GET  /cmc/daily-view                     - the morning CMC view
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aranmanai.ai.services.cmc_loop import CmcLoopService
from aranmanai.api.deps import CurrentUser, DbSession, IoUser, PpUser, SpUser
from aranmanai.db.models.coordination import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    Escalation,
    SpDailyReview,
)
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter(prefix="/cmc", tags=["cmc-loop"])


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


# ──────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────

class CmcMeetingRequest(BaseModel):
    meeting_date: Optional[str] = None  # ISO; default = now
    attendees: list[str] = []
    minutes: Optional[str] = None


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
    assigned_role: str  # io | pp | court_constable | sp
    due_date: str       # ISO datetime
    priority: ActionPriority = ActionPriority.HIGH


class CmcActionAnswerRequest(BaseModel):
    answer: str  # done | not_done | blocked
    answer_detail: Optional[str] = None


class CmcEscalationAcknowledgeRequest(BaseModel):
    note: Optional[str] = None


class CmcEscalationResolveRequest(BaseModel):
    note: str


class CmcSpReviewRequest(BaseModel):
    case_id: str
    review_date: Optional[str] = None  # ISO date; default = today
    status: str = "reviewed"  # reviewed | escalated | cleared
    notes: Optional[str] = None


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


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────

@router.post("/meeting", response_model=CmcMeetingResponse, status_code=201)
def open_meeting(req: CmcMeetingRequest, user: SpUser, db: DbSession) -> CmcMeetingResponse:
    """SP opens the morning CMC meeting. Idempotent per district per day."""
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
        AuditAction.CREATE_WITNESS,  # reuse
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
    """SP assigns an action to an IO/PP during the CMC meeting."""
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
    """IO/PP reports back: done / not_done / blocked. Closes the loop for this action."""
    svc = CmcLoopService(db)
    try:
        a = svc.answer_action(
            action_id=action_id,
            answer=req.answer,
            answer_detail=req.answer_detail,
            answered_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
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


@router.patch("/action/{action_id}/sp-reviewed")
def sp_review_action(action_id: str, user: SpUser, db: DbSession) -> dict:
    """SP signs off on the IO/PP's answer."""
    svc = CmcLoopService(db)
    try:
        a = svc.mark_sp_reviewed(action_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"action_id": a.id, "sp_reviewed": a.sp_reviewed, "sp_reviewed_at": a.sp_reviewed_at.isoformat()}


@router.post("/sweep", response_model=CmcSweepResponse)
def sweep_overdue(user: SpUser, db: DbSession) -> CmcSweepResponse:
    """Mark overdue actions + raise escalations. Run by cron every morning at 9am."""
    svc = CmcLoopService(db)
    n_overdue_before = db.query(ActionItem).filter(ActionItem.status == ActionStatus.OVERDUE).count()
    n_esc = svc.check_overdue()
    n_overdue_after = db.query(ActionItem).filter(ActionItem.status == ActionStatus.OVERDUE).count()
    n_marked = n_overdue_after - n_overdue_before
    return CmcSweepResponse(n_marked_overdue=n_marked, n_escalations_raised=n_esc)


@router.patch("/escalation/{escalation_id}/acknowledge")
def acknowledge_escalation(escalation_id: str, req: CmcEscalationAcknowledgeRequest, user: IoUser, db: DbSession) -> dict:
    """IO/PP acknowledges the escalation. Required before they can resolve it."""
    svc = CmcLoopService(db)
    try:
        e = svc.acknowledge_escalation(escalation_id, note=req.note)
    except ValueError as ex:
        raise HTTPException(404, str(ex))
    return {"escalation_id": e.id, "status": e.status.value}


@router.patch("/escalation/{escalation_id}/resolve")
def resolve_escalation(escalation_id: str, req: CmcEscalationResolveRequest, user: SpUser, db: DbSession) -> dict:
    """SP resolves the escalation with a note."""
    svc = CmcLoopService(db)
    try:
        e = svc.resolve_escalation(escalation_id, note=req.note)
    except ValueError as ex:
        raise HTTPException(404, str(ex))
    return {"escalation_id": e.id, "status": e.status.value, "resolved_at": e.resolved_at.isoformat()}


@router.post("/sp-review", status_code=201)
def sp_review_case(req: CmcSpReviewRequest, user: SpUser, db: DbSession) -> dict:
    """SP signs off on a case for a given day. The core accountability loop."""
    from datetime import date as _date
    svc = CmcLoopService(db)
    review_date = _date.fromisoformat(req.review_date) if req.review_date else _date.today()
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
def daily_view(user: SpUser, db: DbSession, target_date: Optional[str] = None) -> CmcDailyViewResponse:
    """The full CMC morning view: today's hearings + actions + escalations + SP signoff status."""
    from datetime import date as _date
    svc = CmcLoopService(db)
    target = _date.fromisoformat(target_date) if target_date else _date.today()
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
