"""Case routes: CRUD + listing + status transitions."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.api.deps import CurrentUser, DbSession, IoUser, SpUser
from aranmanai.db.models.case import Case, CaseStage, CaseStatus
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, encrypt_field
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter()


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


class CaseCreateRequest(BaseModel):
    fir_no: str = Field(..., min_length=1, max_length=64)
    district: str = Field(..., min_length=1, max_length=64)
    court: str | None = None
    judge: str | None = None
    bns_sections: list[str] = Field(default_factory=list)
    bnss_sections: list[str] = Field(default_factory=list)
    bsa_sections: list[str] = Field(default_factory=list)
    facts_text: str | None = None
    fir_date: datetime | None = None
    io_id: str | None = None
    pp_id: str | None = None
    sp_id: str | None = None


class CaseUpdateRequest(BaseModel):
    court: str | None = None
    judge: str | None = None
    bns_sections: list[str] | None = None
    bnss_sections: list[str] | None = None
    bsa_sections: list[str] | None = None
    facts_text: str | None = None
    status: CaseStatus | None = None
    stage: CaseStage | None = None
    io_id: str | None = None
    pp_id: str | None = None
    sp_id: str | None = None
    next_hearing: datetime | None = None
    sp_notes: str | None = None


class CaseResponse(BaseModel):
    id: str
    fir_no: str
    district: str
    court: str | None
    judge: str | None
    bns_sections: list[str]
    bnss_sections: list[str]
    bsa_sections: list[str]
    facts_text: str | None
    fir_date: datetime | None
    next_hearing: datetime | None
    last_hearing: datetime | None
    judgment_date: datetime | None
    status: str
    stage: str
    risk_score: float | None
    io_id: str | None
    pp_id: str | None
    sp_id: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _to_response(c: Case) -> dict[str, Any]:
    return {
        "id": c.id,
        "fir_no": c.fir_no,
        "district": c.district,
        "court": c.court,
        "judge": c.judge,
        "bns_sections": c.bns_sections or [],
        "bnss_sections": c.bnss_sections or [],
        "bsa_sections": c.bsa_sections or [],
        "facts_text": c.facts_text,
        "fir_date": c.fir_date,
        "next_hearing": c.next_hearing,
        "last_hearing": c.last_hearing,
        "judgment_date": c.judgment_date,
        "status": c.status.value,
        "stage": c.stage.value,
        "risk_score": c.risk_score,
        "io_id": c.io_id,
        "pp_id": c.pp_id,
        "sp_id": c.sp_id,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(req: CaseCreateRequest, db: DbSession, user: IoUser) -> CaseResponse:
    case = Case(
        id=str(uuid.uuid4()),
        fir_no=req.fir_no,
        district=req.district,
        court=req.court,
        judge=req.judge,
        bns_sections=req.bns_sections,
        bnss_sections=req.bnss_sections,
        bsa_sections=req.bsa_sections,
        facts_text=req.facts_text,
        fir_date=req.fir_date,
        io_id=req.io_id or user.id,
        pp_id=req.pp_id,
        sp_id=req.sp_id or (user.id if user.role.value == "sp" else None),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    _audit().append(
        AuditAction.CREATE_CASE,
        actor_id=user.id,
        subject_id=case.id,
        fields_used=["fir_no", "district", "bns_sections", "facts_text"],
        success=True,
        metadata={"fir_no": case.fir_no},
    )
    log.info("case.create", case_id=case.id[:8], fir_no=case.fir_no)
    return _to_response(case)


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: str, db: DbSession, user: CurrentUser) -> CaseResponse:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    _audit().append(
        AuditAction.READ_CASE,
        actor_id=user.id,
        subject_id=case.id,
    )
    return _to_response(case)


@router.get("", response_model=list[CaseResponse])
def list_cases(
    db: DbSession,
    user: CurrentUser,
    district: str | None = None,
    status: CaseStatus | None = None,
    stage: CaseStage | None = None,
    io_id: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> list[CaseResponse]:
    stmt = select(Case)
    if district:
        stmt = stmt.where(Case.district == district)
    if status:
        stmt = stmt.where(Case.status == status)
    if stage:
        stmt = stmt.where(Case.stage == stage)
    if io_id:
        stmt = stmt.where(Case.io_id == io_id)
    stmt = stmt.order_by(Case.fir_date.desc().nulls_last(), Case.created_at.desc()).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return [_to_response(c) for c in rows]


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: str,
    req: CaseUpdateRequest,
    db: DbSession,
    user: IoUser,
) -> CaseResponse:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    fields_used: list[str] = []
    for field_name, value in req.model_dump(exclude_unset=True).items():
        if hasattr(case, field_name):
            setattr(case, field_name, value)
            fields_used.append(field_name)
    db.commit()
    db.refresh(case)
    _audit().append(
        AuditAction.UPDATE_CASE,
        actor_id=user.id,
        subject_id=case.id,
        fields_used=fields_used,
        success=True,
    )
    log.info("case.update", case_id=case_id[:8], fields=fields_used)
    return _to_response(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_case(case_id: str, db: DbSession, user: SpUser) -> None:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    db.delete(case)
    db.commit()
    _audit().append(
        AuditAction.DELETE_CASE,
        actor_id=user.id,
        subject_id=case_id,
        success=True,
    )
    log.warning("case.delete", case_id=case_id[:8], actor=user.id[:8])
