"""Audit log entries stored in the database. Separate from the file-based
hash-chained log so we can query them (the file log is append-only)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aranmanai.db.session import Base


class AuditLogEntry(Base):
    """Queryable copy of the file-based audit log. Hash chain is in the file.

    The file (data/audit.log) is the source of truth (hash-chained, append-only).
    This table is a secondary index for fast queries by user/case/action.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    log_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    fields_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    __table_args__ = (
        Index("ix_audit_actor_action", "actor_id", "action"),
        Index("ix_audit_subject_action", "subject_id", "action"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} actor={self.actor_id[:8]} subject={self.subject_id[:8] if self.subject_id else None}>"
