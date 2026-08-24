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
    CourtConstablePerformance,
    Escalation,
    EscalationStatus,
    PpAnswer,
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

    # ──────────────────────────────────────────────────────────
    # Court constable personnel loop — rewards & penalties
    # Kishore's CMC: constables who excel get cash + commendation;
    # negligence triggers action. This is the part Aranmanai
    # previously missed.
    # ──────────────────────────────────────────────────────────

    def record_constable_performance(
        self,
        constable_id: str,
        district: str,
        period_month: str,  # YYYY-MM
    ) -> CourtConstablePerformance:
        """Auto-compute constable's monthly performance from hearing data.

        Counts hearings attended, witnesses produced, on-time arrival %.
        Idempotent: re-running overwrites counts.
        """
        from calendar import monthrange

        year, month = int(period_month[:4]), int(period_month[5:7])
        days_in_month = monthrange(year, month)[1]
        month_start = datetime(year, month, 1)
        month_end = datetime(year, month, days_in_month, 23, 59, 59)

        # All hearings in the month in the constable's district
        hearings = (
            self.db.query(Hearing)
            .join(Case, Hearing.case_id == Case.id)
            .filter(
                Case.district == district,
                Hearing.date >= month_start,
                Hearing.date <= month_end,
            )
            .all()
        )

        hearings_attended = len(hearings)

        # Witness production: count witnesses who were present at hearings
        witnesses_produced = 0
        on_time_count = 0
        for h in hearings:
            present_ids = h.witness_ids_present or []
            witnesses_produced += len(present_ids)
            # On-time = hearing happened in the morning (before 12pm) for non-urgent cases
            if h.date and h.date.hour < 12:
                on_time_count += 1

        on_time_pct = (on_time_count / hearings_attended) if hearings_attended > 0 else 0.0
        # Production rate: average witnesses produced per hearing
        production_rate = (witnesses_produced / hearings_attended) if hearings_attended > 0 else 0.0

        # Find or create the performance row
        perf = (
            self.db.query(CourtConstablePerformance)
            .filter(
                CourtConstablePerformance.constable_id == constable_id,
                CourtConstablePerformance.period_month == period_month,
            )
            .first()
        )
        if perf is None:
            perf = CourtConstablePerformance(
                id=str(uuid.uuid4()),
                constable_id=constable_id,
                district=district,
                period_month=period_month,
            )
            self.db.add(perf)

        perf.hearings_attended = hearings_attended
        perf.witnesses_produced = witnesses_produced
        perf.witness_production_rate = production_rate
        perf.cases_supported = hearings_attended
        perf.on_time_pct = on_time_pct

        # Auto-flag excellence: >90% production rate AND >80% on-time
        if production_rate >= 0.9 and on_time_pct >= 0.8 and hearings_attended >= 5:
            if not perf.excellence_flag:
                perf.excellence_flag = True
                perf.excellence_reason = (
                    f"Auto-flagged: {production_rate:.0%} witness production, "
                    f"{on_time_pct:.0%} on-time over {hearings_attended} hearings"
                )

        # Auto-flag negligence: <50% production rate OR multiple missed hearings
        if hearings_attended >= 5 and production_rate < 0.5:
            if not perf.negligence_flag:
                perf.negligence_flag = True
                perf.negligence_reason = (
                    f"Auto-flagged: {production_rate:.0%} production rate"
                )

        self.db.commit()
        self.db.refresh(perf)
        log.info(
            "cmc.constable_perf constable=%s month=%s attended=%d produced=%d",
            constable_id, period_month, hearings_attended, witnesses_produced,
        )
        return perf

    def commend_constable(
        self,
        performance_id: str,
        commended_by: str,
        cash_reward_amount: int = 0,
        issue_certificate: bool = True,
        reason: str | None = None,
    ) -> CourtConstablePerformance:
        """Award a constable: cash + commendation certificate.

        Per Kishore's CMC: 'court constables who show excellence in their
        duties will be rewarded with cash and commendation certificates'.
        """
        perf = self.db.get(CourtConstablePerformance, performance_id)
        if not perf:
            raise ValueError(f"Performance record {performance_id} not found")
        perf.excellence_flag = True
        perf.cash_reward_amount = cash_reward_amount
        perf.commendation_certificate = issue_certificate
        perf.commended_by = commended_by
        perf.commended_at = datetime.utcnow()
        if reason:
            perf.excellence_reason = reason
        self.db.commit()
        self.db.refresh(perf)
        log.info(
            "cmc.commend constable=%s cash=%d cert=%s",
            perf.constable_id, cash_reward_amount, issue_certificate,
        )
        return perf

    def penalize_constable(
        self,
        performance_id: str,
        actioned_by: str,
        action_type: str,  # warning | memo | transfer
        reason: str,
    ) -> CourtConstablePerformance:
        """Penalize a constable: warning / memo / transfer.

        Per Kishore: 'any negligence in duty would result in action'.
        """
        valid_actions = ("warning", "memo", "transfer")
        if action_type not in valid_actions:
            raise ValueError(f"action_type must be one of {valid_actions}")
        perf = self.db.get(CourtConstablePerformance, performance_id)
        if not perf:
            raise ValueError(f"Performance record {performance_id} not found")
        perf.negligence_flag = True
        perf.action_taken = action_type
        perf.action_taken_by = actioned_by
        perf.action_taken_at = datetime.utcnow()
        perf.negligence_reason = reason
        self.db.commit()
        self.db.refresh(perf)
        log.info(
            "cmc.penalize constable=%s action=%s reason=%s",
            perf.constable_id, action_type, reason,
        )
        return perf

    # ──────────────────────────────────────────────────────────
    # Public prosecutor accountability — PP must answer on ActionItem
    # ──────────────────────────────────────────────────────────

    def pp_answer(
        self,
        action_id: str,
        pp_id: str,
        answer: str,  # ready | not_ready | needs_evidence | blocked
        answer_detail: str | None = None,
        evidence_needed: list[str] | None = None,
    ) -> PpAnswer:
        """Public prosecutor answers a CMC action.

        Separate from ActionItem.answer (which is the IO's answer) so the
        prosecution and investigation sides each have their own timeline.
        """
        action = self.db.get(ActionItem, action_id)
        if not action:
            raise ValueError(f"Action {action_id} not found")

        existing = (
            self.db.query(PpAnswer)
            .filter(PpAnswer.action_id == action_id, PpAnswer.pp_id == pp_id)
            .order_by(PpAnswer.answered_at.desc())
            .first()
        )
        if existing is None:
            existing = PpAnswer(
                id=str(uuid.uuid4()),
                action_id=action_id,
                case_id=action.case_id,
                pp_id=pp_id,
            )
            self.db.add(existing)
        existing.answer = answer
        existing.answer_detail = answer_detail
        existing.evidence_needed = evidence_needed or []
        existing.answered_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(existing)
        log.info(
            "cmc.pp_answer action=%s pp=%s answer=%s",
            action_id, pp_id, answer,
        )
        return existing

    # ──────────────────────────────────────────────────────────
    # DSP weekly rollup — station-by-station review
    # Per The Hindu [11]: IGP directed DSPs to review cases
    # station-wise every week.
    # ──────────────────────────────────────────────────────────

    def dsp_weekly_rollup(
        self,
        district: str,
        week_start: date,
    ) -> dict[str, Any]:
        """DSP-level weekly review: one row per police station in district.

        Shows: case count, pending actions, overdue actions, witnesses
        flagged, FSL status. This is the rollup above the SP's daily view.
        """
        from aranmanai.db.models.evidence import Evidence, FslStatus
        from aranmanai.db.models.witness import Witness, WitnessCategory

        week_end_excl = week_start + timedelta(days=7)
        cases_in_district = (
            self.db.query(Case).filter(Case.district == district).all()
        )
        # Group cases by police station if we have a station field; for
        # v1 we use the cases as the rollup unit
        by_station: dict[str, list[Case]] = {}
        for c in cases_in_district:
            station = c.district  # v1 simplification
            by_station.setdefault(station, []).append(c)

        rollup: list[dict[str, Any]] = []
        for station, cases in by_station.items():
            case_ids = [c.id for c in cases]
            pending_actions = (
                self.db.query(ActionItem)
                .filter(
                    ActionItem.case_id.in_(case_ids),
                    ActionItem.status == ActionStatus.PENDING,
                )
                .count()
            )
            overdue_actions = (
                self.db.query(ActionItem)
                .filter(
                    ActionItem.case_id.in_(case_ids),
                    ActionItem.status == ActionStatus.OVERDUE,
                )
                .count()
            )
            answered_in_week = (
                self.db.query(ActionItem)
                .filter(
                    ActionItem.case_id.in_(case_ids),
                    ActionItem.answered_at >= datetime.combine(week_start, datetime.min.time()),
                    ActionItem.answered_at < datetime.combine(week_end_excl, datetime.min.time()),
                )
                .count()
            )
            hostile_witnesses = (
                self.db.query(Witness)
                .filter(
                    Witness.case_id.in_(case_ids),
                    Witness.category == WitnessCategory.HOSTILE,
                )
                .count()
            )
            fsl_overdue = (
                self.db.query(Evidence)
                .filter(
                    Evidence.case_id.in_(case_ids),
                    Evidence.fsl_status.in_([FslStatus.OVERDUE, FslStatus.NOT_SENT]),
                )
                .count()
            )
            rollup.append({
                "station": station,
                "n_cases": len(cases),
                "n_actions_pending": pending_actions,
                "n_actions_overdue": overdue_actions,
                "n_actions_answered_this_week": answered_in_week,
                "n_hostile_witnesses": hostile_witnesses,
                "n_fsl_overdue": fsl_overdue,
                "flagged": overdue_actions > 0 or fsl_overdue > 0,
            })

        return {
            "district": district,
            "week_start": week_start.isoformat(),
            "week_end_excl": week_end_excl.isoformat(),
            "n_stations": len(rollup),
            "stations": rollup,
            "n_flagged_stations": sum(1 for s in rollup if s["flagged"]),
        }

    # ──────────────────────────────────────────────────────────
    # Pilot measurement — conviction rate delta
    # ──────────────────────────────────────────────────────────

    def pilot_conviction_metrics(
        self,
        district: str | None = None,
    ) -> dict[str, Any]:
        """Compute conviction rate for the pilot.

        Conviction rate = (convicted cases) / (closed cases).
        Closed = cases with an outcome recorded.
        """
        from aranmanai.db.models.coordination import PilotCase
        from datetime import datetime as _dt

        q = self.db.query(PilotCase)
        if district:
            q = q.filter(PilotCase.district == district)

        cases = q.all()
        total = len(cases)
        closed = [c for c in cases if c.outcome in ("convicted", "acquitted", "compromised", "dismissed")]
        pending = [c for c in cases if c.outcome in (None, "pending")]
        convicted = [c for c in cases if c.outcome == "convicted"]
        acquitted = [c for c in cases if c.outcome == "acquitted"]
        compromised = [c for c in cases if c.outcome == "compromised"]

        # Conviction rate over closed cases
        conviction_rate = (len(convicted) / len(closed)) if len(closed) > 0 else None
        acquittal_rate = (len(acquitted) / len(closed)) if len(closed) > 0 else None

        # Average baseline_p_conviction as the pre-pilot rate
        baselines = [c.baseline_p_conviction for c in cases if c.baseline_p_conviction is not None]
        baseline_avg = sum(baselines) / len(baselines) if baselines else None

        # Delta: how much did the system improve over baseline
        delta = None
        if baseline_avg is not None and conviction_rate is not None:
            delta = conviction_rate - baseline_avg
            delta_pct = (delta / baseline_avg) * 100 if baseline_avg > 0 else None
        else:
            delta_pct = None

        # Cures applied average
        n_cures_total = sum(len(c.cures_applied or []) for c in cases)

        return {
            "district": district or "all",
            "n_enrolled": total,
            "n_closed": len(closed),
            "n_pending": len(pending),
            "n_convicted": len(convicted),
            "n_acquitted": len(acquitted),
            "n_compromised": len(compromised),
            "conviction_rate": round(conviction_rate, 4) if conviction_rate is not None else None,
            "acquittal_rate": round(acquittal_rate, 4) if acquittal_rate is not None else None,
            "baseline_p_conviction_avg": round(baseline_avg, 4) if baseline_avg is not None else None,
            "delta_conviction_rate": round(delta, 4) if delta is not None else None,
            "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
            "n_cures_applied_total": n_cures_total,
            "sentences": {
                "life": sum(1 for c in cases if c.sentence and "life" in (c.sentence or "").lower()),
                "20y": sum(1 for c in cases if c.sentence and "20" in (c.sentence or "")),
                "10y": sum(1 for c in cases if c.sentence and "10" in (c.sentence or "")),
            },
        }
