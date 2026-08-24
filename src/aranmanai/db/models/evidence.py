"""Evidence model. One per piece of evidence in a case."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.case import Case


class EvidenceType(str, enum.Enum):
    DOCUMENT = "document"
    WITNESS_TESTIMONY = "witness_testimony"
    FSL = "fsl"                        # forensic science lab report
    ELECTRONIC = "electronic"          # phone records, CCTV, eSakshya
    PHYSICAL = "physical"              # weapon, recovered item
    MEDICAL = "medical"                # MLC, post-mortem
    OTHER = "other"


class EvidenceChainStatus(str, enum.Enum):
    SEALED = "sealed"            # chain intact, sealed at recovery
    INTACT = "intact"            # chain intact, not yet sealed
    PENDING = "pending"          # chain under construction
    BROKEN = "broken"            # chain has gaps — this is a FATAL lapse
    UNKNOWN = "unknown"


class FslStatus(str, enum.Enum):
    NOT_SENT = "not_sent"
    SENT = "sent"
    IN_QUEUE = "in_queue"
    RETURNED = "returned"
    OVERDUE = "overdue"          # > 60 days without return — a procedural risk


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("case.id"), index=True, nullable=False)

    type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, native_enum=False, length=20), default=EvidenceType.OTHER, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    chain_status: Mapped[EvidenceChainStatus] = mapped_column(
        Enum(EvidenceChainStatus, native_enum=False, length=20),
        default=EvidenceChainStatus.UNKNOWN,
        nullable=False,
    )
    fsl_status: Mapped[FslStatus] = mapped_column(
        Enum(FslStatus, native_enum=False, length=20), default=FslStatus.NOT_SENT, nullable=False
    )

    # Mock eSakshya SID — 16-digit ID per eSakshya spec
    sid: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # Hash for tamper detection (per eSakshya)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    recovered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fsl_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fsl_returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    case: Mapped["Case"] = relationship("Case", back_populates="evidence", lazy="joined")

    def __repr__(self) -> str:
        return f"<Evidence {self.id[:8]} type={self.type.value} chain={self.chain_status.value}>"
