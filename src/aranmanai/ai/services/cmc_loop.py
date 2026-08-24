"""CMC daily action tracker service — Kishore's accountability loop.

Kishore Kommi (Eluru, 2023-24) achieved 156% conviction rate increase via
one mechanism: the daily CMC (Court Monitoring Cell) loop. SP held 30-min
morning meeting at 10am with IO + PP + court constable. Each case got a
specific action item assigned to an IO/PP, due by next morning. If not
answered, SP got pinged.

This service implements that loop:
- create_meeting: SP opens the morning CMC
- assign_action: per-case action with assignee + due_date
- answer_action: IO/PP reports back next morning
- check_overdue: cron-style sweep that marks overdue actions + raises escalations
- daily_view: the full CMC morning view (today's hearings + actions + escalations)
- sp_review: SP's per-case sign-off (every case, every morning)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case
from aranmanai.db.models.coordination import (
    ActionItem,
    ActionPriority,
    ActionStatus,
    CMCMeeting,
    Escalation,
    EscalationStatus,
    SpDailyReview,
)
from aranmanai.db.models.hearing import Hearing
from aranmanai.db.models.user import User
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class DailyCmcView:
    """The full CMC morning view: hearings + actions + escalations."""
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
    sp_signoff_status: dict  # {case_id: status} for SP dashboard


class CmcLoopService:
    """The Kishore accountability loop, as a service."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────
    # Meeting
    # ──────────────────────────────────────────────────────────

    def open_meeting(
        self,
        district: str,
        meeting_date: datetime,
        held_by: str,
        attendees: list[str] | None = None,
        minutes: str | None = None,
    ) -> CMCMeeting:
        """SP opens a CMC morning meeting. One per district per day."""
        existing = (
            self.db.query(CMCMeeting)
            .filter(
                CMCMeeting.district == district,
                CMCMeeting.meeting_date >= meeting_date.replace(hour=0, minute=0, second=0),
                CMCMeeting.meeting_date < meeting_date.replace(hour=23, minute=59, second=59),
            )
            .first()
        )
        if existing:
            return existing  # idempotent

        m = CMCMeeting(
            id=str(uuid.uuid4()),
            district=district,
            meeting_date=meeting_date,
            held_by=held_by,
            attendees=attendees or [],
            minutes=minutes,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        log.info("cmc.meeting_opened district=%s held_by=%s", district, held_by)
        return m

    # ──────────────────────────────────────────────────────────
    # Action items
    # ──────────────────────────────────────────────────────────

    def assign_action(
        self,
        meeting_id: str,
        case_id: str,
        description: str,
        action_type: str,
        assigned_to: str,
        assigned_role: str,
        due_date: datetime,
        priority: ActionPriority = ActionPriority.HIGH,
    ) -> ActionItem:
        """SP assigns an action to an IO/PP. The heart of the loop."""
        a = ActionItem(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            case_id=case_id,
            description=description,
            action_type=action_type,
            assigned_to=assigned_to,
            assigned_role=assigned_role,
            due_date=due_date,
            priority=priority,
            status=ActionStatus.PENDING,
        )
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        log.info("cmc.action_assigned case=%s assigned_to=%s due=%s", case_id, assigned_to, due_date)
        return a

    def answer_action(
        self,
        action_id: str,
        answer: str,  # done | not_done | blocked
        answer_detail: str | None = None,
        answered_by: str | None = None,
    ) -> ActionItem:
        """IO/PP reports back. Closes the loop for this action."""
        a = self.db.get(ActionItem, action_id)
        if not a:
            raise ValueError(f"Action {action_id} not found")
        a.answer = answer
        a.answer_detail = answer_detail
        a.answered_by = answered_by
        a.answered_at = datetime.utcnow()
        a.status = ActionStatus.ANSWERED
        self.db.commit()
        self.db.refresh(a)
        log.info("cmc.action_answered action=%s answer=%s", action_id, answer)
        return a

    def mark_sp_reviewed(self, action_id: str) -> ActionItem:
        """SP reviews the IO/PP's answer."""
        a = self.db.get(ActionItem, action_id)
        if not a:
            raise ValueError(f"Action {action_id} not found")
        a.sp_reviewed = True
        a.sp_reviewed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(a)
        return a

    # ──────────────────────────────────────────────────────────
    # Overdue sweep + escalation
    # ──────────────────────────────────────────────────────────

    def check_overdue(self) -> int:
        """Sweep actions past due_date without answer; mark overdue + raise escalations.

        Returns the number of new escalations raised. Should be called by
        a cron job (e.g., every morning at 9am, before the CMC).
        """
        now = datetime.utcnow()
        overdue_actions = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.due_date < now,
                ActionItem.status == ActionStatus.PENDING,
            )
            .all()
        )

        new_escalations = 0
        for a in overdue_actions:
            a.status = ActionStatus.OVERDUE

            # Find SP for the case's district
            case = self.db.get(Case, a.case_id)
            if not case:
                continue

            # Skip if escalation already open for this action
            existing = (
                self.db.query(Escalation)
                .filter(
                    Escalation.action_id == a.id,
                    Escalation.status == EscalationStatus.OPEN,
                )
                .first()
            )
            if existing:
                continue

            severity = "critical" if a.priority in (ActionPriority.URGENT, ActionPriority.HIGH) else "warning"
            reason = f"Action overdue: {a.action_type}"
            esc = Escalation(
                id=str(uuid.uuid4()),
                case_id=a.case_id,
                action_id=a.id,
                to_user=a.assigned_to,
                sp_id=case.sp_id or a.assigned_to,  # fallback
                severity=severity,
                reason=reason,
                detail=f"'{a.description}' was due {a.due_date.isoformat()} and not answered",
            )
            self.db.add(esc)
            new_escalations += 1
            log.info("cmc.escalation_raised action=%s case=%s to=%s", a.id, a.case_id, a.assigned_to)

        if new_escalations > 0:
            self.db.commit()
        return new_escalations

    def acknowledge_escalation(self, escalation_id: str, note: str | None = None) -> Escalation:
        e = self.db.get(Escalation, escalation_id)
        if not e:
            raise ValueError(f"Escalation {escalation_id} not found")
        e.status = EscalationStatus.ACKNOWLEDGED
        e.acknowledged_at = datetime.utcnow()
        e.resolution_note = note
        self.db.commit()
        self.db.refresh(e)
        return e

    def resolve_escalation(self, escalation_id: str, note: str) -> Escalation:
        e = self.db.get(Escalation, escalation_id)
        if not e:
            raise ValueError(f"Escalation {escalation_id} not found")
        e.status = EscalationStatus.RESOLVED
        e.resolved_at = datetime.utcnow()
        e.resolution_note = note
        self.db.commit()
        self.db.refresh(e)
        return e

    # ──────────────────────────────────────────────────────────
    # SP daily review — the SP's per-case sign-off
    # ──────────────────────────────────────────────────────────

    def sp_review_case(
        self,
        case_id: str,
        sp_id: str,
        review_date: date,
        status: str = "reviewed",  # reviewed | escalated | cleared
        notes: str | None = None,
    ) -> SpDailyReview:
        """SP signs off on a case for a given day. Without this, no accountability."""
        existing = (
            self.db.query(SpDailyReview)
            .filter(
                SpDailyReview.case_id == case_id,
                SpDailyReview.review_date == review_date,
            )
            .first()
        )
        if existing:
            existing.status = status
            existing.notes = notes
            existing.reviewed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)
            return existing

        # Count today's actions + overdue
        action_count = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.case_id == case_id,
                ActionItem.due_date >= datetime.combine(review_date, datetime.min.time()),
                ActionItem.due_date < datetime.combine(review_date + timedelta(days=1), datetime.min.time()),
            )
            .count()
        )
        overdue_count = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.case_id == case_id,
                ActionItem.status == ActionStatus.OVERDUE,
            )
            .count()
        )

        r = SpDailyReview(
            id=str(uuid.uuid4()),
            case_id=case_id,
            review_date=review_date,
            sp_id=sp_id,
            status=status,
            notes=notes,
            action_count=action_count,
            overdue_action_count=overdue_count,
            reviewed_at=datetime.utcnow(),
        )
        self.db.add(r)
        self.db.commit()
        self.db.refresh(r)
        log.info("cmc.sp_review case=%s sp=%s status=%s", case_id, sp_id, status)
        return r

    # ──────────────────────────────────────────────────────────
    # Daily CMC view — the morning view
    # ──────────────────────────────────────────────────────────

    def daily_view(self, district: str, target_date: date | None = None) -> DailyCmcView:
        """The full CMC morning view for the SP."""
        target = target_date or date.today()
        next_day = target + timedelta(days=1)
        day_start = datetime.combine(target, datetime.min.time())
        day_end = datetime.combine(next_day, datetime.min.time())

        # Today's hearings (in this district)
        hearings = (
            self.db.query(Hearing)
            .join(Case, Hearing.case_id == Case.id)
            .filter(
                Case.district == district,
                Hearing.date >= day_start,
                Hearing.date < day_end,
            )
            .all()
        )

        # Pending actions due today or earlier (across the district)
        cases_in_district_ids = select(Case.id).where(Case.district == district)
        pending_actions = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.case_id.in_(cases_in_district_ids),
                ActionItem.status == ActionStatus.PENDING,
                ActionItem.due_date <= day_end,
            )
            .all()
        )
        overdue_actions = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.case_id.in_(cases_in_district_ids),
                ActionItem.status == ActionStatus.OVERDUE,
            )
            .all()
        )
        answered_yesterday = (
            self.db.query(ActionItem)
            .filter(
                ActionItem.case_id.in_(cases_in_district_ids),
                ActionItem.status == ActionStatus.ANSWERED,
                ActionItem.answered_at >= day_start - timedelta(days=1),
                ActionItem.answered_at < day_start,
            )
            .all()
        )
        open_escalations = (
            self.db.query(Escalation)
            .filter(
                Escalation.status == EscalationStatus.OPEN,
                Escalation.case_id.in_(cases_in_district_ids),
            )
            .all()
        )

        # SP signoff status for today
        sp_reviews_today = (
            self.db.query(SpDailyReview)
            .filter(
                SpDailyReview.review_date == target,
                SpDailyReview.case_id.in_(cases_in_district_ids),
            )
            .all()
        )
        sp_signoff: dict[str, str] = {r.case_id: r.status for r in sp_reviews_today}
        case_ids_with_hearings_today = {h.case_id for h in hearings}
        n_unreviewed = len(case_ids_with_hearings_today - set(sp_signoff.keys()))

        def _action_to_dict(a: ActionItem) -> dict[str, Any]:
            case = self.db.get(Case, a.case_id)
            return {
                "id": a.id,
                "case_id": a.case_id,
                "fir_no": case.fir_no if case else "unknown",
                "description": a.description,
                "action_type": a.action_type,
                "assigned_to": a.assigned_to,
                "assigned_role": a.assigned_role,
                "due_date": a.due_date.isoformat(),
                "priority": a.priority.value,
                "status": a.status.value,
                "answer": a.answer,
                "answer_detail": a.answer_detail,
                "answered_at": a.answered_at.isoformat() if a.answered_at else None,
            }

        def _escalation_to_dict(e: Escalation) -> dict[str, Any]:
            case = self.db.get(Case, e.case_id)
            return {
                "id": e.id,
                "case_id": e.case_id,
                "fir_no": case.fir_no if case else "unknown",
                "severity": e.severity,
                "reason": e.reason,
                "detail": e.detail,
                "to_user": e.to_user,
                "sp_id": e.sp_id,
                "status": e.status.value,
                "created_at": e.created_at.isoformat(),
            }

        def _hearing_to_dict(h: Hearing) -> dict[str, Any]:
            case = self.db.get(Case, h.case_id)
            return {
                "hearing_id": h.id,
                "case_id": h.case_id,
                "fir_no": case.fir_no if case else "unknown",
                "date": h.date.isoformat(),
                "stage": h.stage,
                "pp_present": h.pp_present,
                "accused_present": h.accused_present,
                "sp_reviewed": sp_signoff.get(h.case_id, "pending"),
            }

        # Top priority: overdue + critical pending
        top_priority = sorted(
            [_action_to_dict(a) for a in overdue_actions]
            + [_action_to_dict(a) for a in pending_actions if a.priority == ActionPriority.URGENT],
            key=lambda x: ({"urgent": 0, "high": 1, "medium": 2, "low": 3}[x["priority"]], x["due_date"]),
        )[:10]

        return DailyCmcView(
            date=target.isoformat(),
            district=district,
            n_hearings=len(hearings),
            n_actions_pending=len(pending_actions),
            n_actions_overdue=len(overdue_actions),
            n_actions_answered_yesterday=len(answered_yesterday),
            n_escalations_open=len(open_escalations),
            n_cases_unreviewed=n_unreviewed,
            hearings=[_hearing_to_dict(h) for h in hearings],
            overdue_actions=[_action_to_dict(a) for a in overdue_actions],
            open_escalations=[_escalation_to_dict(e) for e in open_escalations],
            top_priority=top_priority,
            sp_signoff_status=sp_signoff,
        )
