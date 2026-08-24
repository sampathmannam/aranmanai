"""Hearing model. One per scheduled court date for a case."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.case import Case


class Hearing(Base):
    __tablename__ = "hearing"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)

    # Date is the only required scheduling field
    date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    # Free-form label of what was on the docket
    docket_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Stage at this hearing
    stage: Mapped[str] = mapped_column(String(32), default="hearing", nullable=False)

    # Attendance
    accused_present: Mapped[bool] = mapped_column(Boolean, default=None, nullable=True)
    pp_present: Mapped[bool] = mapped_column(Boolean, default=None, nullable=True)
    defense_present: Mapped[bool] = mapped_column(Boolean, default=None, nullable=True)
    witness_ids_present: Mapped[list[str]] = mapped_column(JSON, default=list)  # witnesses who showed
    judge_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Outcome
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)  # adjourned, argued, judgment, etc.
    next_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_hearing_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Adjourning reasons — populated for bottleneck analysis
    adjournment_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Whose absence caused the adjournment
    caused_by: Mapped[str] = mapped_column(String(32), default="none", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    case: Mapped["Case"] = relationship("Case", back_populates="hearings", lazy="joined")

    def __repr__(self) -> str:
        return f"<Hearing {self.date} case={self.case_id[:8]} outcome={self.outcome}>"
