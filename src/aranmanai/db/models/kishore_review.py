"""Models for the 12 Kishore-review findings (excluding CCTNS #3).

Each table addresses one of the gaps SP K. Pratap Shiva Kishore flagged
in his review of Aranmanai v1.1.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base


# ──────────────────────────────────────────────────────────────
# F1: HelplineCall GPS + auto-station dispatch
# ──────────────────────────────────────────────────────────────

class HelplineCallGPS(Base):
    """GPS coordinates and auto-derived police station for a helpline call.

    F1 fix: free-form `location_text` was insufficient. Patrol needs lat/lng
    plus the auto-derived station boundary so the right PSO gets pinged.
    """
    __tablename__ = "safety_helpline_call_gps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    helpline_log_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_helpline_call.id"), nullable=False, index=True
    )
    caller_lat: Mapped[float] = mapped_column(Float, nullable=False)
    caller_lng: Mapped[float] = mapped_column(Float, nullable=False)
    auto_station: Mapped[str | None] = mapped_column(String(128), nullable=True)
    distance_to_station_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_resolution_method: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ──────────────────────────────────────────────────────────────
# F2: BNS 173 charge-sheet deadline tracking
# ──────────────────────────────────────────────────────────────

class ChargeSheetDeadline(Base):
    """BNS 173(2) / BNSS 173 charge-sheet deadline tracking.

    F2 fix: charge-sheet must be filed within 60 days for offences
    punishable up to 10 years, and 90 days otherwise. Missed deadlines
    are the #1 reason for acquittal per BPRD studies.
    """
    __tablename__ = "case_charge_sheet_deadline"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case.id"), nullable=False, index=True, unique=True
    )
    fir_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_sentence_years: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    is_overdue: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    alert_7d_sent: Mapped[bool] = mapped_column(default=False, nullable=False)
    alert_1d_sent: Mapped[bool] = mapped_column(default=False, nullable=False)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ──────────────────────────────────────────────────────────────
# F5: Charge-sheet version control
# ──────────────────────────────────────────────────────────────

class ChargeSheetVersion(Base):
    """Charge-sheet version history. F5 fix: every save is a version.

    IOs edit drafts multiple times before submitting. PP reviews. We need
    to track each version for audit and rollback.
    """
    __tablename__ = "case_charge_sheet_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case.id"), nullable=False, index=True
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    drafted_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    drafted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    pp_reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    pp_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pp_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    # 'draft' | 'pp_reviewed' | 'filed' | 'rejected'


# ──────────────────────────────────────────────────────────────
# F6: Case.pilot_flag (consolidation of PilotCase)
# ──────────────────────────────────────────────────────────────

class CaseTransfer(Base):
    """F10 fix: case transfers between IOs / PPs.

    Required for BPRD audit and court challenges (IO at the time of the
    act is responsible, not the IO at the time of trial).
    """
    __tablename__ = "case_transfer"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case.id"), nullable=False, index=True
    )
    from_io_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    to_io_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    from_pp_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    to_pp_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    transferred_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    transferred_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ──────────────────────────────────────────────────────────────
# F11: CaseFamilyLiaison (POCSO / 304B victim updates)
# ──────────────────────────────────────────────────────────────

class CaseFamilyLiaison(Base):
    """F11 fix: family liaison tracking. Mandatory for POCSO + 304B.

    District Child Protection Officer asks quarterly for this data.
    Tracks who is the family contact, when last briefed, what communicated,
    and whether the family retained counsel.
    """
    __tablename__ = "case_family_liaison"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case.id"), nullable=False, index=True
    )
    family_contact: Mapped[str] = mapped_column(String(256), nullable=False)
    family_contact_relationship: Mapped[str | None] = mapped_column(String(64), nullable=True)
    family_counsel: Mapped[str | None] = mapped_column(String(128), nullable=True)
    briefed_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    briefed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    what_communicated: Mapped[str] = mapped_column(Text, nullable=False)
    followup_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    followup_due: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ──────────────────────────────────────────────────────────────
# F12: National helpline reference (1091 / 181 integration)
# ──────────────────────────────────────────────────────────────

class HelplineUpstreamRef(Base):
    """F12 fix: link to national/state helpline calls (1091 / 181).

    When a call comes in from the national helpline, link it to the
    upstream reference for end-to-end traceability.
    """
    __tablename__ = "safety_helpline_upstream_ref"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    helpline_log_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_helpline_call.id"), nullable=False, index=True
    )
    upstream_system: Mapped[str] = mapped_column(String(32), nullable=False)  # '1091' | '181' | '112' | 'other'
    upstream_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)


# ──────────────────────────────────────────────────────────────
# F13: PPBriefing (PP reads)
# ──────────────────────────────────────────────────────────────

class PPBriefing(Base):
    """F13 fix: PP briefing tracking.

    A PP handles ~80 cases/year. They can't keep up with 'have I read the
    latest investigation update?'. Track which briefings each PP has read.
    """
    __tablename__ = "pp_briefing"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case.id"), nullable=False, index=True
    )
    pp_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    case_action_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("action_item.id"), nullable=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_response: Mapped[bool] = mapped_column(default=False, nullable=False)


# ──────────────────────────────────────────────────────────────
# F14: Deputation model (IO on deputation in another district)
# ──────────────────────────────────────────────────────────────

class Deputation(Base):
    """F14 fix: IO on deputation. Allows cross-district access.

    When an IO is on deputation, they can see both home + deputation
    districts. This complements the H-2 IDOR fix which otherwise
    blocks cross-district access.
    """
    __tablename__ = "deputation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    home_district: Mapped[str] = mapped_column(String(64), nullable=False)
    deputation_district: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    approved_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
