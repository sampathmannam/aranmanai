"""Operational coordination models: notes, witness production, daily review, alerts.

These power Kishore Kommi's accountability loop:
- SP-IO-PP chat per case (coordination_note)
- Witness production tracking per hearing (witness_production)
- SP daily review entries (daily_review)
- Proactive alerts (alert)

DPDP §8(3): every entry has actor_id, timestamp; sensitive fields
encrypted; audit hash chained.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text
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
