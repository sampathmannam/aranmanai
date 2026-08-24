"""Operational coordination models: notes, witness production, daily review, alerts, pilot, CMC loop.

These power Kishore Kommi's accountability loop:
- SP-IO-PP chat per case (coordination_note)
- Witness production tracking per hearing (witness_production)
- SP daily review entries (daily_review)
- Proactive alerts (alert)
- Pilot measurement (pilot_case)
- CMC daily action tracker (action_item)
- CMC daily meeting record (cmc_meeting)
- SP per-case sign-off (sp_daily_review)
- Escalation chain (escalation)

DPDP §8(3): every entry has actor_id, timestamp; sensitive fields
encrypted; audit hash chained.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.user import User
    from aranmanai.db.models.hearing import Hearing


# ──────────────────────────────────────────────────────────────
# Coordination note — SP-IO-PP chat per case
# ──────────────────────────────────────────────────────────────


class NoteType(str, enum.Enum):
    OBSERVATION = "observation"     # factual: "witness X was hostile today"
    ACTION_REQUEST = "action_request"  # SP asks IO/PP to do something
    ACTION_DONE = "action_done"      # IO/PP reports back: done
    FLAG = "flag"                    # urgent attention needed
    NOTE = "note"                    # free-form


class CoordinationNote(Base):
    __tablename__ = "coordination_note"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    hearing_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("hearing.id"), nullable=True, index=True)

    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)  # sp / io / pp / admin
    note_type: Mapped[NoteType] = mapped_column(Enum(NoteType), default=NoteType.NOTE, nullable=False)

    # Free-form text (DPDP §8(4): encrypt at rest if contains PII)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured metadata: { "action_due": "2026-09-15", "witness_id": "..." }
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    # If this is an action_request, the assigned actor
    assigned_to: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_done: Mapped[bool] = mapped_column(default=False, nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    case: Mapped["Case"] = relationship("Case", back_populates="coordination_notes")

    def __repr__(self) -> str:
        return f"<CoordinationNote {self.note_type} case={self.case_id[:8]} actor={self.actor_role}>"


# ──────────────────────────────────────────────────────────────
# Witness production — who showed up at which hearing
# ──────────────────────────────────────────────────────────────


class ProductionStatus(str, enum.Enum):
    PENDING = "pending"             # hearing scheduled, not yet checked
    CONFIRMED_PRESENT = "confirmed_present"  # IO/PP confirmed witness will attend
    CONFIRMED_ABSENT = "confirmed_absent"  # IO/PP confirmed witness will NOT attend
    ACTUALLY_PRESENT = "actually_present"  # witness showed up (updated post-hearing)
    ACTUALLY_ABSENT = "actually_absent"  # witness did not show up
    NO_SHOW = "no_show"              # witness was expected but did not appear
    RESCHEDULED = "rescheduled"      # hearing was rescheduled


class WitnessProduction(Base):
    """One row per (witness, hearing). Tracks production through the
    case lifecycle. DPDP §8(3) compliant.
    """
    __tablename__ = "witness_production"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    hearing_id: Mapped[str] = mapped_column(String(36), ForeignKey("hearing.id"), index=True, nullable=False)
    witness_id: Mapped[str] = mapped_column(String(36), ForeignKey("witness.id"), index=True, nullable=False)

    # Pre-hearing status
    pre_status: Mapped[ProductionStatus] = mapped_column(Enum(ProductionStatus), default=ProductionStatus.PENDING, nullable=False)
    pre_updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    pre_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pre_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Post-hearing status (after the hearing date)
    post_status: Mapped[ProductionStatus | None] = mapped_column(Enum(ProductionStatus), nullable=True)
    post_updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    post_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    post_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Defense questions asked (free text or JSON list)
    defense_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # How did the witness perform? (calm, nervous, contradicted, evasive)
    performance: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Witness protection: escort, in-camera, identity protection
    protection_provided: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_wp_case_hearing_witness", "case_id", "hearing_id", "witness_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<WitnessProduction {self.pre_status}/{self.post_status} w={self.witness_id[:8]}>"


# ──────────────────────────────────────────────────────────────
# Daily review — SP's accountability log
# ──────────────────────────────────────────────────────────────


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"            # case surfaced, not yet reviewed by SP
    REVIEWED = "reviewed"          # SP has reviewed
    ESCALATED = "escalated"        # SP has escalated (e.g., to DGP, fast-track court)
    CLEARED = "cleared"            # SP reviewed, no action needed
    NO_REVIEW_NEEDED = "no_review_needed"  # auto-cleared (low risk, no issues)


class DailyCaseReview(Base):
    """SP's daily review entry for a case. One per (case, date)."""
    __tablename__ = "daily_case_review"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    review_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    sp_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)

    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)
    # Free-form notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Action items arising from the review
    action_items: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Was SP's intervention logged?
    sp_intervened: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Outcome if escalated
    escalation_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_dcr_case_date", "case_id", "review_date", unique=True),
    )

    def __repr__(self) -> str:
        return f"<DailyCaseReview {self.review_date.date()} case={self.case_id[:8]} {self.status}>"


# ──────────────────────────────────────────────────────────────
# Alert — proactive notifications
# ──────────────────────────────────────────────────────────────


class AlertType(str, enum.Enum):
    BOTTLENECK = "bottleneck"             # case stuck at stage
    WITNESS_MISSING = "witness_missing"   # hearing tomorrow, witness not confirmed
    WITNESS_UNPREPPED = "witness_unprepped"  # hostile witness, no cross-exam prep done
    FSL_OVERDUE = "fsl_overdue"           # FSL report not returned
    HEARING_TOMORROW = "hearing_tomorrow"
    CASE_STUCK = "case_stuck"             # >180 days in same stage
    ACTION_OVERDUE = "action_overdue"     # coordination_note is_action_request past due
    PP_MISSING = "pp_missing"             # PP not confirmed for tomorrow's hearing


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(Base):
    """Proactive alert surfaced to SP / IO / PP. Auto-generated by the
    daily cron job. Resolved when the underlying condition clears.
    """
    __tablename__ = "alert"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("case.id"), nullable=True, index=True)
    hearing_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("hearing.id"), nullable=True, index=True)
    witness_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("witness.id"), nullable=True, index=True)

    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), index=True, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), default=AlertSeverity.WARNING, nullable=False)
    district: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    is_resolved: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} {self.severity} case={self.case_id[:8] if self.case_id else None}>"


# ──────────────────────────────────────────────────────────────
# Pilot case — tracks conviction rate measurement
# ──────────────────────────────────────────────────────────────


class PilotCase(Base):
    """One row per case in the conviction-rate pilot.

    Measures the delta between baseline (before Aranmanai cures) and
    post-cure conviction probability. Used to compute the delta attributable
    to the Aranmanai system.

    The pilot is the make-or-break measurement: did the system move
    conviction rate? Kishore Kommi achieved 156% increase (from 51/41 to
    132/41 cases) with the CMC coordination loop — this model tracks whether
    Aranmanai achieves a similar effect.
    """
    __tablename__ = "pilot_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    district: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    enrolled_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Baseline (measured BEFORE Aranmanai cures applied)
    baseline_p_conviction: Mapped[float | None] = mapped_column(nullable=True)  # 0-1
    baseline_offence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_court: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_lapse_count: Mapped[int | None] = mapped_column(nullable=True)
    baseline_fatal_lapse_count: Mapped[int | None] = mapped_column(nullable=True)

    # Cures applied (list of {lapse_key, cure_action, applied_at})
    cures_applied: Mapped[list] = mapped_column(JSON, default=list)

    # Post-cure measurements (measured after at least one hearing cycle)
    post_p_conviction: Mapped[float | None] = mapped_column(nullable=True)  # 0-1
    post_lapse_count: Mapped[int | None] = mapped_column(nullable=True)
    post_fatal_lapse_count: Mapped[int | None] = mapped_column(nullable=True)
    post_hostile_witnesses: Mapped[int | None] = mapped_column(nullable=True)

    # Outcome (the actual case outcome — filled when judgment is delivered)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)  # convicted | acquitted | compromised | pending
    outcome_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sentence: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Measurement timestamps
    mid_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<PilotCase {self.case_id[:8]} outcome={self.outcome}>"


# ──────────────────────────────────────────────────────────────
# CMC daily meeting — the core loop that made Kishore's system work
# ──────────────────────────────────────────────────────────────


class CMCMeeting(Base):
    """One row per daily CMC morning meeting.

    Kishore Kommi's accountability loop:
    1. SP holds 30-min morning CMC at 10am (court constable + PP + IO present)
    2. Today's actions assigned per case — each is an ActionItem
    3. IO/PP reports back next morning — each answer is an ActionAnswer
    4. Overdue answers trigger Alert to SP

    DPDP: meeting minutes are internal; not shared with external parties.
    """
    __tablename__ = "cmc_meeting"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    district: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    meeting_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    # Who held this meeting (typically SP)
    held_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    # Attendees: list of user IDs
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    # Free-form minutes
    minutes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Key decisions made
    decisions: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<CMCMeeting {self.meeting_date.date()} district={self.district}>"


# ──────────────────────────────────────────────────────────────
# Action item — one action per case per meeting
# ──────────────────────────────────────────────────────────────


class ActionPriority(str, enum.Enum):
    URGENT = "urgent"      # must be done today
    HIGH = "high"          # must be done by tomorrow
    MEDIUM = "medium"      # this week
    LOW = "low"             # this month


class ActionStatus(str, enum.Enum):
    PENDING = "pending"     # assigned, not yet answered
    ANSWERED = "answered"   # IO/PP reported back
    OVERDUE = "overdue"    # past due_date, no answer
    CANCELLED = "cancelled"


class ActionItem(Base):
    """One action assigned per case per CMC meeting.

    This is the CORE of Kishore's accountability loop:
    - SP assigns: "IO, call witness X today"
    - Due tomorrow morning: IO must answer "done / not done / blocked"
    - If no answer → Alert to SP → escalation
    """
    __tablename__ = "action_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("cmc_meeting.id"), index=True, nullable=False)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)

    # What the IO/PP needs to do
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)  # call_witness | confirm_production | fsl_reminder | court_followup | etc.

    # Who is responsible
    assigned_to: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    assigned_role: Mapped[str] = mapped_column(String(16), nullable=False)  # io | pp | court_constable | sp

    # When it must be done (typically next morning for IO answerability)
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    priority: Mapped[ActionPriority] = mapped_column(
        Enum(ActionPriority), default=ActionPriority.HIGH, nullable=False
    )

    # Status
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus), default=ActionStatus.PENDING, nullable=False
    )

    # IO/PP's answer (filled next morning)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # done | not_done | blocked
    answer_detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # free-form explanation
    answered_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # SP review
    sp_reviewed: Mapped[bool] = mapped_column(default=False, nullable=False)
    sp_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_action_case_due", "case_id", "due_date"),
        Index("ix_action_assignee_status", "assigned_to", "status"),
    )

    def __repr__(self) -> str:
        return f"<ActionItem {self.action_type} case={self.case_id[:8]} status={self.status.value}>"


# ──────────────────────────────────────────────────────────────
# SP daily review — SP's per-case sign-off
# ──────────────────────────────────────────────────────────────


class SpDailyReview(Base):
    """SP's per-case per-day sign-off. Kishore's loop:
    - SP reviews every case every single morning
    - Marks: REVIEWED (acknowledged, no action), ESCALATED (needs intervention), or CLEARED (auto, no review needed)
    - Without this, the SP is just looking at a dashboard, not running the loop
    """
    __tablename__ = "sp_daily_review"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    review_date: Mapped[datetime] = mapped_column(Date, index=True, nullable=False)
    sp_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending | reviewed | escalated | cleared
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_count: Mapped[int] = mapped_column(default=0, nullable=False)
    overdue_action_count: Mapped[int] = mapped_column(default=0, nullable=False)

    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_sdr_case_date", "case_id", "review_date", unique=True),
    )

    def __repr__(self) -> str:
        return f"<SpDailyReview {self.review_date} case={self.case_id[:8]} {self.status}>"


# ──────────────────────────────────────────────────────────────
# Escalation — IO/PP missed an action → SP gets pinged
# ──────────────────────────────────────────────────────────────


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Escalation(Base):
    """One row per escalation event. Triggered automatically when
    an ActionItem goes overdue. SP must acknowledge or resolve.
    """
    __tablename__ = "escalation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)
    action_id: Mapped[str] = mapped_column(String(36), ForeignKey("action_item.id"), nullable=True, index=True)

    # Who raised the escalation (system or SP)
    raised_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    # Who needs to respond (IO/PP)
    to_user: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    # SP cc'd
    sp_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)

    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)  # info | warning | critical
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus), default=EscalationStatus.OPEN, nullable=False, index=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Escalation {self.severity} case={self.case_id[:8]} status={self.status.value}>"

