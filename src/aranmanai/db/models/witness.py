"""Witness model. One per witness per case."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.case import Case


class WitnessType(str, enum.Enum):
    EYEWITNESS = "eyewitness"
    VICTIM = "victim"
    EXPERT = "expert"          # FSL, doctor, handwriting expert
    OFFICIAL = "official"      # IO, panch, etc.
    CHARACTER = "character"    # character witness for accused
    OTHER = "other"


class WitnessCategory(str, enum.Enum):
    """How reliable is this witness? Updated by IO/PP."""
    SUPPORTIVE = "supportive"  # cooperative, telling truth
    NEUTRAL = "neutral"        # not actively hostile
    HOSTILE = "hostile"        # turned hostile, threat/inducement


class WitnessPrepStatus(str, enum.Enum):
    UNTOUCHED = "untouched"     # not yet contacted by IO/PP for prep
    PREPPED = "prepped"         # prepped, understands cross-exam
    READY = "ready"             # ready to testify
    TESTIFIED = "testified"     # already testified in court
    UNAVAILABLE = "unavailable" # can't be located or refuses


class Witness(Base):
    __tablename__ = "witness"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)

    # Encrypted identity (name + contact)
    name_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    contact_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    type: Mapped[WitnessType] = mapped_column(
        Enum(WitnessType, native_enum=False, length=20), default=WitnessType.EYEWITNESS, nullable=False
    )
    category: Mapped[WitnessCategory] = mapped_column(
        Enum(WitnessCategory, native_enum=False, length=20),
        default=WitnessCategory.NEUTRAL,
        nullable=False,
        index=True,
    )
    prep_status: Mapped[WitnessPrepStatus] = mapped_column(
        Enum(WitnessPrepStatus, native_enum=False, length=20),
        default=WitnessPrepStatus.UNTOUCHED,
        nullable=False,
    )

    # Statement text (encrypted) — 161 BNSS / 157 CrPC
    statement_text_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    statement_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Hostile tracking
    hostile_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    hostile_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Protection (BNSS §327 in-camera, identity protection under §17 SC/ST PoA, etc.)
    protection_level: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    protection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cross-exam prep — AI-generated questions + suggested answers
    cross_exam_questions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    cross_exam_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Court attendance history (denormalized for fast dashboard)
    hearings_attended: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attended: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # AI cross-exam prep generation history
    prep_history: Mapped[list[dict]] = mapped_column(JSON, default=list)

    last_contact: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="witnesses", lazy="joined")

    def __repr__(self) -> str:
        return f"<Witness {self.id[:8]} type={self.type.value} category={self.category.value}>"
