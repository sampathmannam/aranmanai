"""Case model: the central unit of Aranmanai. One row per FIR/case."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.user import User
    from aranmanai.db.models.witness import Witness
    from aranmanai.db.models.hearing import Hearing
    from aranmanai.db.models.evidence import Evidence
    from aranmanai.db.models.coordination import CoordinationNote


class CaseStatus(str, enum.Enum):
    """Lifecycle status of a case."""
    OPEN = "open"                    # FIR registered, investigation ongoing
    CHARGE_SHEETED = "charge_sheeted"  # charge sheet filed
    TRIAL = "trial"                  # in trial
    JUDGMENT = "judgment"            # judgment delivered
    APPEAL = "appeal"                # under appeal
    CLOSED_ACQUITTED = "closed_acquitted"
    CLOSED_CONVICTED = "closed_convicted"
    CLOSED_COMPROMISED = "closed_compromised"
    CLOSED_WITHDRAWN = "closed_withdrawn"


class CaseStage(str, enum.Enum):
    """Current procedural stage. Used for bottleneck detection."""
    INVESTIGATION = "investigation"   # FIR → charge sheet
    CHARGE_SHEET = "charge_sheet"     # charge sheet filed
    ARGUMENT = "argument"             # arguments heard
    EVIDENCE = "evidence"             # evidence stage
    JUDGMENT = "judgment"             # awaiting judgment
    APPEAL = "appeal"                 # on appeal
    CLOSED = "closed"


class Case(Base):
    """A case (one FIR or set of linked FIRs)."""

    __tablename__ = "case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fir_no: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    district: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    court: Mapped[str | None] = mapped_column(String(128), nullable=True)
    judge: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # BNS / BNSS / BSA / PoA sections, stored as JSON list
    bns_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    bnss_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    bsa_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    poa_sections: Mapped[list[str]] = mapped_column(JSON, default=list)  # SC/ST PoA Act sections
    is_poa_act_case: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Facts (plaintext summary — not encrypted in pilot seed)
    facts: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Encrypted text fields (witness names, contact, etc. — see security/crypto.py)
    facts_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_text_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False, length=32),
        default=CaseStatus.OPEN,
        nullable=False,
        index=True,
    )
    stage: Mapped[CaseStage] = mapped_column(
        Enum(CaseStage, native_enum=False, length=32),
        default=CaseStage.INVESTIGATION,
        nullable=False,
        index=True,
    )

    # FK to users
    io_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True, index=True)
    pp_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True, index=True)
    sp_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True, index=True)

    # Calendar
    fir_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_hearing: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_hearing: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    judgment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # AI outputs (advisory)
    risk_score: Mapped[float | None] = mapped_column(nullable=True)  # 0-1, advisory
    risk_score_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Free-form notes (encrypted at the application layer)
    sp_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    io: Mapped["User | None"] = relationship("User", foreign_keys=[io_id], lazy="joined")
    pp: Mapped["User | None"] = relationship("User", foreign_keys=[pp_id], lazy="joined")
    sp: Mapped["User | None"] = relationship("User", foreign_keys=[sp_id], lazy="joined")
    witnesses: Mapped[list["Witness"]] = relationship(
        "Witness", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    hearings: Mapped[list["Hearing"]] = relationship(
        "Hearing", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    coordination_notes: Mapped[list["CoordinationNote"]] = relationship(
        "CoordinationNote", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Case {self.fir_no} status={self.status.value} stage={self.stage.value}>"
