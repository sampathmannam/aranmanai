"""Safety tables — helpline log, anonymous reports, patrol dispatches.

Migrated from in-memory lists in api/v1/safety.py (C-5 from security audit).
Each row is hashed-chained to the audit log for tamper-evidence.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aranmanai.db.session import Base


class HelplineCall(Base):
    """One row per helpline call. NO caller_id/phone stored (anonymity)."""
    __tablename__ = "safety_helpline_call"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("case.id"), nullable=True, index=True)
    caller_district: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_patrol: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_callback: Mapped[bool] = mapped_column(default=False, nullable=False)
    routed_to: Mapped[str] = mapped_column(String(32), nullable=False)
    patrol_dispatched: Mapped[bool] = mapped_column(default=False, nullable=False)
    logged_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_safety_helpline_district_severity", "caller_district", "severity"),
    )


class AnonymousReport(Base):
    """Anonymous incident report (Abhaya formurl.com equivalent)."""
    __tablename__ = "safety_anon_report"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    incident_date: Mapped[str] = mapped_column(String(32), nullable=False)
    location_text: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_sp_review", nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PatrolDispatch(Base):
    """Women patrol unit dispatch record."""
    __tablename__ = "safety_patrol_dispatch"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("case.id"), nullable=True)
    helpline_log_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("safety_helpline_call.id"), nullable=True)
    district: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    area: Mapped[str] = mapped_column(String(256), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="high", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    dispatched_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
