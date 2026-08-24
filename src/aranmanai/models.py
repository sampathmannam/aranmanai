"""ORM models for the 6 core tables.

All models use INTEGER PKs (SQLite-friendly, no UUID overhead).
Arrays are stored as JSON text (SQLite has no native array).
Timestamps are Unix epoch integers (UTC) for index efficiency.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.aranmanai.db import Base


def _now() -> int:
    """Unix epoch seconds (UTC) — used as default for created_at / updated_at."""
    return int(datetime.now(tz=timezone.utc).timestamp())


# --- Enums (string constants, kept in Python to avoid SQLAlchemy Enum overhead on SQLite) ---

ROLE_SP = "SP"
ROLE_IO = "IO"
ROLE_PP = "PP"  # Public Prosecutor
ROLE_ADMIN = "Admin"
ROLES = (ROLE_SP, ROLE_IO, ROLE_PP, ROLE_ADMIN)

CASE_STATUS_OPEN = "open"
CASE_STATUS_HEARING = "hearing"
CASE_STATUS_JUDGMENT = "judgment"
CASE_STATUS_APPEAL = "appeal"
CASE_STATUSES = (CASE_STATUS_OPEN, CASE_STATUS_HEARING, CASE_STATUS_JUDGMENT, CASE_STATUS_APPEAL)

CASE_STAGE_INVESTIGATION = "investigation"
CASE_STAGE_CHARGE_SHEET = "charge_sheet"
CASE_STAGE_TRIAL = "trial"
CASE_STAGE_ARGUMENT = "argument"
CASE_STAGE_JUDGMENT = "judgment"
CASE_STAGES = (
    CASE_STAGE_INVESTIGATION,
    CASE_STAGE_CHARGE_SHEET,
    CASE_STAGE_TRIAL,
    CASE_STAGE_ARGUMENT,
    CASE_STAGE_JUDGMENT,
)

WITNESS_TYPE_EYEWITNESS = "eyewitness"
WITNESS_TYPE_VICTIM = "victim"
WITNESS_TYPE_EXPERT = "expert"
WITNESS_TYPE_OFFICIAL = "official"
WITNESS_TYPES = (
    WITNESS_TYPE_EYEWITNESS,
    WITNESS_TYPE_VICTIM,
    WITNESS_TYPE_EXPERT,
    WITNESS_TYPE_OFFICIAL,
)

WITNESS_CATEGORY_SUPPORTIVE = "Supportive"
WITNESS_CATEGORY_NEUTRAL = "Neutral"
WITNESS_CATEGORY_HOSTILE = "Hostile"
WITNESS_CATEGORIES = (WITNESS_CATEGORY_SUPPORTIVE, WITNESS_CATEGORY_NEUTRAL, WITNESS_CATEGORY_HOSTILE)

WITNESS_PREP_UNTOUCHED = "untouched"
WITNESS_PREP_PREPPED = "prepped"
WITNESS_PREP_READY = "ready"
WITNESS_PREP_TESTIFIED = "testified"
WITNESS_PREP_STATUSES = (WITNESS_PREP_UNTOUCHED, WITNESS_PREP_PREPPED, WITNESS_PREP_READY, WITNESS_PREP_TESTIFIED)

EVIDENCE_TYPE_DOCUMENT = "document"
EVIDENCE_TYPE_WITNESS = "witness"
EVIDENCE_TYPE_FSL = "fsl"
EVIDENCE_TYPE_ELECTRONIC = "electronic"
EVIDENCE_TYPES = (
    EVIDENCE_TYPE_DOCUMENT, EVIDENCE_TYPE_WITNESS, EVIDENCE_TYPE_FSL, EVIDENCE_TYPE_ELECTRONIC,
)

CHAIN_SEALED = "sealed"
CHAIN_BROKEN = "broken"
CHAIN_PENDING = "pending"
CHAIN_STATUSES = (CHAIN_SEALED, CHAIN_BROKEN, CHAIN_PENDING)

FSL_SENT = "sent"
FSL_RETURNED = "returned"
FSL_OVERDUE = "overdue"
FSL_NA = "not_applicable"
FSL_STATUSES = (FSL_SENT, FSL_RETURNED, FSL_OVERDUE, FSL_NA)


# --- User ---

class User(Base):
    """SP / IO / PP / Admin. Auth via bcrypt password + JWT."""
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    district: Mapped[str] = mapped_column(String(80), nullable=False, default="Vellore")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)

    cases_as_io: Mapped[list["Case"]] = relationship(back_populates="io", foreign_keys="Case.io_id")
    cases_as_pp: Mapped[list["Case"]] = relationship(back_populates="pp", foreign_keys="Case.pp_id")

    __table_args__ = (
        Index("ix_user_district_role", "district", "role"),
    )


# --- Case ---

class Case(Base):
    """One criminal case from FIR to judgment."""
    __tablename__ = "case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fir_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sections: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    offence: Mapped[str] = mapped_column(String(80), default="all", nullable=False)
    district: Mapped[str] = mapped_column(String(80), nullable=False)
    court: Mapped[str | None] = mapped_column(String(120), nullable=True)
    judge: Mapped[str | None] = mapped_column(String(120), nullable=True)
    io_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    pp_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CASE_STATUS_OPEN, nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default=CASE_STAGE_INVESTIGATION, nullable=False)
    next_hearing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_update: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)
    facts_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquittal_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_conviction: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)

    io: Mapped[User | None] = relationship(back_populates="cases_as_io", foreign_keys=[io_id])
    pp: Mapped[User | None] = relationship(back_populates="cases_as_pp", foreign_keys=[pp_id])
    witnesses: Mapped[list["Witness"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    hearings: Mapped[list["Hearing"]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="Hearing.date")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_case_district_status", "district", "status"),
        Index("ix_case_status_stage", "status", "stage"),
        Index("ix_case_next_hearing", "next_hearing"),
    )


# --- Witness ---

class Witness(Base):
    """Per-case witness. Categorization (Supportive/Neutral/Hostile) drives cure actions."""
    __tablename__ = "witness"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default=WITNESS_TYPE_EYEWITNESS, nullable=False)
    category: Mapped[str] = mapped_column(String(20), default=WITNESS_CATEGORY_NEUTRAL, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="Tamil", nullable=False)
    statement_161: Mapped[str | None] = mapped_column(Text, nullable=True)
    hostile_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_status: Mapped[str] = mapped_column(String(20), default=WITNESS_PREP_UNTOUCHED, nullable=False)
    prep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    protection_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    last_contact: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)

    case: Mapped[Case] = relationship(back_populates="witnesses")

    __table_args__ = (
        Index("ix_witness_case_category", "case_id", "category"),
    )


# --- Hearing ---

class Hearing(Base):
    """One court hearing date for a case. Tracks attendance + outcome."""
    __tablename__ = "hearing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default=CASE_STAGE_TRIAL, nullable=False)
    accused_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    witness_present_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    pp_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    defense_present: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)

    case: Mapped[Case] = relationship(back_populates="hearings")

    __table_args__ = (
        Index("ix_hearing_case_date", "case_id", "date"),
        Index("ix_hearing_date", "date"),
    )


# --- Evidence ---

class Evidence(Base):
    """One piece of evidence in a case. Tracks chain + FSL status."""
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default=EVIDENCE_TYPE_DOCUMENT, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    chain_status: Mapped[str] = mapped_column(String(20), default=CHAIN_PENDING, nullable=False)
    fsl_status: Mapped[str] = mapped_column(String(20), default=FSL_NA, nullable=False)
    cctv_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    esakshya_sid: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)

    case: Mapped[Case] = relationship(back_populates="evidence")

    __table_args__ = (
        Index("ix_evidence_case_type", "case_id", "type"),
    )


# --- Audit Log (hash-chained, DPDP §8(3) compliant) ---

class AuditLog(Base):
    """Every read/write logged with hash-chained integrity. DPDP §8(3)."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fields_used: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timestamp: Mapped[int] = mapped_column(Integer, default=_now, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_audit_actor_time", "actor_id", "timestamp"),
        Index("ix_audit_subject", "subject_type", "subject_id"),
    )
