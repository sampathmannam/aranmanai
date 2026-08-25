"""Witness routes: CRUD + categorization + prep."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from aranmanai.api.deps import CurrentUser, DbSession, IoUser, PpUser
from aranmanai.config import get_settings
from aranmanai.core.witness.categorization import WitnessCategorizationService
from aranmanai.core.witness.preparation import WitnessPreparationService
from aranmanai.db.models.case import Case
from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessPrepStatus, WitnessType
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, decrypt_field, encrypt_field

log = get_logger(__name__)
router = APIRouter()


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


class WitnessCreateRequest(BaseModel):
    case_id: str
    name: str = Field(..., min_length=1, max_length=128)
    contact: str | None = None
    language: str = "en"
    type: WitnessType = WitnessType.EYEWITNESS
    category: WitnessCategory = WitnessCategory.NEUTRAL
    statement_text: str | None = None
    statement_recorded_at: datetime | None = None
    hostile_reason: str | None = None
    protection_level: str = "none"
    protection_notes: str | None = None


class WitnessUpdateRequest(BaseModel):
    name: str | None = None
    contact: str | None = None
    language: str | None = None
    type: WitnessType | None = None
    category: WitnessCategory | None = None
    statement_text: str | None = None
    statement_recorded_at: datetime | None = None
    hostile_reason: str | None = None
    protection_level: str | None = None
    protection_notes: str | None = None
    prep_status: WitnessPrepStatus | None = None


class WitnessResponse(BaseModel):
    id: str
    case_id: str
    name: str  # decrypted
    contact: str | None
    language: str
    type: str
    category: str
    prep_status: str
    hostile_reason: str | None
    protection_level: str
    cross_exam_questions: list[dict]
    cross_exam_at: datetime | None
    hearings_attended: int
    last_contact: datetime | None
    created_at: datetime
    updated_at: datetime


def _to_response(w: Witness) -> WitnessResponse:
    return WitnessResponse(
        id=w.id,
        case_id=w.case_id,
        name=decrypt_field(w.name_encrypted),
        contact=decrypt_field(w.contact_encrypted) if w.contact_encrypted else None,
        language=w.language,
        type=w.type.value,
        category=w.category.value,
        prep_status=w.prep_status.value,
        hostile_reason=w.hostile_reason,
        protection_level=w.protection_level,
        cross_exam_questions=w.cross_exam_questions or [],
        cross_exam_at=w.cross_exam_at,
        hearings_attended=w.hearings_attended,
        last_contact=w.last_contact,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


@router.post("", response_model=WitnessResponse, status_code=status.HTTP_201_CREATED)
def create_witness(req: WitnessCreateRequest, db: DbSession, user: IoUser) -> WitnessResponse:
    case = db.get(Case, req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    witness = Witness(
        id=str(uuid.uuid4()),
        case_id=req.case_id,
        name_encrypted=encrypt_field(req.name),
        contact_encrypted=encrypt_field(req.contact) if req.contact else None,
        language=req.language,
        type=req.type,
        category=req.category,
        statement_text_encrypted=encrypt_field(req.statement_text) if req.statement_text else None,
        statement_recorded_at=req.statement_recorded_at,
        hostile_reason=req.hostile_reason,
        protection_level=req.protection_level,
        protection_notes=req.protection_notes,
    )
    db.add(witness)
    db.commit()
    db.refresh(witness)
    _audit().append(
        AuditAction.CREATE_WITNESS,
        actor_id=user.id,
        subject_id=witness.id,
        fields_used=["name", "type", "category"],
    )
    log.info("witness.create", witness_id=witness.id[:8], case_id=req.case_id[:8])
    return _to_response(witness)


@router.get("/{witness_id}", response_model=WitnessResponse)
def get_witness(witness_id: str, db: DbSession, user: CurrentUser) -> WitnessResponse:
    w = db.get(Witness, witness_id)
    if not w:
        raise HTTPException(status_code=404, detail="Witness not found")
    _audit().append(AuditAction.READ_WITNESS, actor_id=user.id, subject_id=witness_id)
    return _to_response(w)


@router.get("", response_model=list[WitnessResponse])
def list_witnesses(
    db: DbSession,
    user: CurrentUser,
    case_id: str | None = None,
    category: WitnessCategory | None = None,
    prep_status: WitnessPrepStatus | None = None,
) -> list[WitnessResponse]:
    stmt = select(Witness)
    if case_id:
        stmt = stmt.where(Witness.case_id == case_id)
    if category:
        stmt = stmt.where(Witness.category == category)
    if prep_status:
        stmt = stmt.where(Witness.prep_status == prep_status)
    rows = db.execute(stmt).scalars().all()
    return [_to_response(w) for w in rows]


@router.patch("/{witness_id}/category", response_model=WitnessResponse)
def categorize_witness(
    witness_id: str,
    category: WitnessCategory,
    db: DbSession,
    user: IoUser,
    reason: str | None = None,
) -> WitnessResponse:
    svc = WitnessCategorizationService(db)
    w = svc.categorize(witness_id, category, reason=reason)
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=witness_id,
        fields_used=["category"],
        metadata={"new_category": category.value, "reason": reason},
    )
    return _to_response(w)


@router.post("/{witness_id}/cross-exam-prep")
def cross_exam_prep(
    witness_id: str,
    case_facts: str,
    db: DbSession,
    user: PpUser,
    language: str = "en",
) -> dict:
    svc = WitnessPreparationService(db)
    result = svc.generate_brief(witness_id, case_facts=case_facts, language=language)
    _audit().append(
        AuditAction.AI_CROSS_EXAM_PREP,
        actor_id=user.id,
        subject_id=witness_id,
        success=True,
        metadata={"prep_id": result["prep_id"], "elapsed_seconds": result["elapsed_seconds"]},
    )
    return result


@router.post("/{witness_id}/ready", response_model=WitnessResponse)
def mark_witness_ready(witness_id: str, db: DbSession, user: PpUser) -> WitnessResponse:
    svc = WitnessPreparationService(db)
    w = svc.mark_ready(witness_id, io_approved=True)
    _audit().append(AuditAction.UPDATE_WITNESS, actor_id=user.id, subject_id=witness_id, fields_used=["prep_status"])
    return _to_response(w)


@router.post("/{witness_id}/testified", response_model=WitnessResponse)
def mark_witness_testified(
    witness_id: str,
    db: DbSession,
    user: PpUser,
    performance_notes: str | None = None,
) -> WitnessResponse:
    svc = WitnessPreparationService(db)
    w = svc.mark_testified(witness_id, performance_notes=performance_notes)
    _audit().append(AuditAction.UPDATE_WITNESS, actor_id=user.id, subject_id=witness_id, fields_used=["prep_status", "hearings_attended"])
    return _to_response(w)
