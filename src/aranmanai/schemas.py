"""Pydantic v2 schemas for request/response validation.

One schema per model + a few composite schemas for the CMS endpoints
(daily calendar, witness prep, etc). Every schema is the API contract;
changing a schema changes the API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.aranmanai.models import (
    CASE_STATUSES, CASE_STAGES, CHAIN_STATUSES, EVIDENCE_TYPES,
    FSL_STATUSES, ROLES, WITNESS_CATEGORIES, WITNESS_PREP_STATUSES, WITNESS_TYPES,
)


class ORMModel(BaseModel):
    """Base for response models. Reads from SQLAlchemy ORM objects."""
    model_config = ConfigDict(from_attributes=True)


# --- Auth ---

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


# --- User ---

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal["SP", "IO", "PP", "Admin"]
    district: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class UserRead(ORMModel):
    id: int
    name: str
    role: str
    district: str
    is_active: bool
    last_login: int | None
    created_at: int


# --- Case ---

class CaseCreate(BaseModel):
    case_id: str = Field(min_length=1, max_length=64, description="Stable external ID (auto-* or district-prefixed)")
    fir_no: str | None = Field(default=None, max_length=64)
    sections: list[str] = Field(default_factory=list, description="BNS/BNSS/BSA section codes")
    offence: str = Field(default="all", max_length=80)
    district: str = Field(min_length=1, max_length=80)
    court: str | None = Field(default=None, max_length=120)
    judge: str | None = Field(default=None, max_length=120)
    io_id: int | None = None
    pp_id: int | None = None
    facts_text: str | None = None
    next_hearing: int | None = Field(default=None, description="Unix epoch seconds (UTC)")

    @field_validator("sections")
    @classmethod
    def _validate_sections(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


class CaseUpdate(BaseModel):
    fir_no: str | None = None
    sections: list[str] | None = None
    offence: str | None = None
    court: str | None = None
    judge: str | None = None
    io_id: int | None = None
    pp_id: int | None = None
    status: str | None = None
    stage: str | None = None
    next_hearing: int | None = None
    facts_text: str | None = None
    p_conviction: float | None = Field(default=None, ge=0, le=1)
    acquittal_risk: float | None = Field(default=None, ge=0, le=1)


class CaseRead(ORMModel):
    id: int
    case_id: str
    fir_no: str | None
    sections: list[str]
    offence: str
    district: str
    court: str | None
    judge: str | None
    io_id: int | None
    pp_id: int | None
    status: str
    stage: str
    next_hearing: int | None
    last_update: int
    facts_text: str | None
    acquittal_risk: float | None
    p_conviction: float | None
    created_at: int


# --- Witness ---

class WitnessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: str = Field(default="eyewitness", max_length=20)
    contact: str | None = Field(default=None, max_length=160)
    language: str = Field(default="Tamil", max_length=20)
    statement_161: str | None = None
    prep_notes: str | None = None


class WitnessUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    category: str | None = None
    contact: str | None = None
    language: str | None = None
    statement_161: str | None = None
    hostile_reason: str | None = None
    prep_status: str | None = None
    prep_notes: str | None = None
    protection_level: str | None = None
    last_contact: int | None = None


class WitnessRead(ORMModel):
    id: int
    case_id: int
    name: str
    type: str
    category: str
    contact: str | None
    language: str
    statement_161: str | None
    hostile_reason: str | None
    prep_status: str
    prep_notes: str | None
    protection_level: str
    last_contact: int | None
    created_at: int
    updated_at: int


# --- Hearing ---

class HearingCreate(BaseModel):
    date: int = Field(description="Unix epoch seconds (UTC)")
    stage: str = Field(default="trial", max_length=20)
    accused_present: bool = False
    witness_present_ids: list[int] = Field(default_factory=list)
    pp_present: bool = False
    defense_present: bool = True
    outcome: str | None = None
    next_action: str | None = None
    notes: str | None = None


class HearingUpdate(BaseModel):
    date: int | None = None
    stage: str | None = None
    accused_present: bool | None = None
    witness_present_ids: list[int] | None = None
    pp_present: bool | None = None
    defense_present: bool | None = None
    outcome: str | None = None
    next_action: str | None = None
    notes: str | None = None


class HearingRead(ORMModel):
    id: int
    case_id: int
    date: int
    stage: str
    accused_present: bool
    witness_present_ids: list[int]
    pp_present: bool
    defense_present: bool
    outcome: str | None
    next_action: str | None
    notes: str | None
    created_at: int


# --- Evidence ---

class EvidenceCreate(BaseModel):
    type: str = Field(default="document", max_length=20)
    description: str
    chain_status: str = Field(default="pending", max_length=20)
    fsl_status: str = Field(default="not_applicable", max_length=20)
    cctv_available: bool = False
    esakshya_sid: str | None = Field(default=None, max_length=20)
    location: str | None = Field(default=None, max_length=200)


class EvidenceUpdate(BaseModel):
    type: str | None = None
    description: str | None = None
    chain_status: str | None = None
    fsl_status: str | None = None
    cctv_available: bool | None = None
    esakshya_sid: str | None = None
    location: str | None = None


class EvidenceRead(ORMModel):
    id: int
    case_id: int
    type: str
    description: str
    chain_status: str
    fsl_status: str
    cctv_available: bool
    esakshya_sid: str | None
    location: str | None
    created_at: int
    updated_at: int


# --- CMS composite endpoints ---

class CaseWithWitnesses(CaseRead):
    witnesses: list[WitnessRead] = Field(default_factory=list)


class DailyCalendarItem(BaseModel):
    case_id: str
    case_internal_id: int
    fir_no: str | None
    section_summary: str
    hearing_id: int
    hearing_date: int
    hearing_stage: str
    court: str | None
    judge: str | None
    pp_name: str | None
    witnesses_to_prep: list[WitnessRead] = Field(default_factory=list)
    hostile_witness_count: int
    total_witness_count: int


class DailyCalendarResponse(BaseModel):
    date: int
    district: str
    items: list[DailyCalendarItem] = Field(default_factory=list)
    total_hearings: int
    total_cases_at_risk: int


class BottleneckReport(BaseModel):
    threshold_days: int
    items: list[CaseRead] = Field(default_factory=list)
    bottleneck_count: int


class WitnessPrepRequest(BaseModel):
    witness_id: int
    case_id: int
    focus: str | None = Field(default=None, description="Optional focus area: 'cross-exam', 'statement', 'specific-fact'")


class WitnessPrepResponse(BaseModel):
    witness_id: int
    witness_name: str
    case_id: int
    case_summary: str
    likely_questions: list[dict[str, str]]  # [{"question": "...", "rationale": "..."}]
    suggested_talking_points: list[str]
    prep_completed_at: int


# --- AI assist endpoints ---

class ComplaintIntakeRequest(BaseModel):
    text: str | None = None
    language: str = "Tamil"
    audio_b64: str | None = Field(default=None, description="Base64-encoded audio for voice intake")


class ComplaintIntakeResponse(BaseModel):
    structured_complaint: dict[str, Any]
    model: str
    generated_at: int
    review_required: bool = True


class FirDraftRequest(BaseModel):
    case_id: int


class FirDraftResponse(BaseModel):
    case_id: int
    fir_text: str
    bns_sections: list[str]
    bnss_sections: list[str]
    bsa_sections: list[str]
    model: str
    review_required: bool = True


class ChargesheetDraftRequest(BaseModel):
    case_id: int


class ChargesheetDraftResponse(BaseModel):
    case_id: int
    chargesheet_text: str
    model: str
    review_required: bool = True


# --- Health ---

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    db_path: str
    llm_backend: str
    llm_model_loaded: bool
    integrations: dict[str, str]  # mode per integration
    uptime_s: float


# --- Generic ---

class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    request_id: str | None = None
