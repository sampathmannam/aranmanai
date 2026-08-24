"""Hearing routes."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.api.deps import CurrentUser, DbSession, IoUser, PpUser
from aranmanai.db.models.case import Case
from aranmanai.db.models.hearing import Hearing
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter()


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


class HearingCreateRequest(BaseModel):
    case_id: str
    date: datetime
    docket_label: str | None = None
    stage: str = "hearing"
    judge_name: str | None = None


class HearingUpdateRequest(BaseModel):
    date: datetime | None = None
    docket_label: str | None = None
    stage: str | None = None
    accused_present: bool | None = None
    pp_present: bool | None = None
    defense_present: bool | None = None
    witness_ids_present: list[str] | None = None
    judge_name: str | None = None
    outcome: str | None = None
    next_action: str | None = None
    next_hearing_date: datetime | None = None
    notes: str | None = None
    adjournment_reason: str | None = None
    caused_by: str | None = None


class HearingResponse(BaseModel):
    id: str
    case_id: str
    date: datetime
    docket_label: str | None
    stage: str
    judge_name: str | None
    accused_present: bool | None
    pp_present: bool | None
    defense_present: bool | None
    witness_ids_present: list[str]
    outcome: str | None
    next_action: str | None
    next_hearing_date: datetime | None
    notes: str | None
    adjournment_reason: str | None
    caused_by: str

    class Config:
        from_attributes = True


def _to_response(h: Hearing) -> dict[str, Any]:
    return {
        "id": h.id,
        "case_id": h.case_id,
        "date": h.date,
        "docket_label": h.docket_label,
        "stage": h.stage,
        "judge_name": h.judge_name,
        "accused_present": h.accused_present,
        "pp_present": h.pp_present,
        "defense_present": h.defense_present,
        "witness_ids_present": h.witness_ids_present or [],
        "outcome": h.outcome,
        "next_action": h.next_action,
        "next_hearing_date": h.next_hearing_date,
        "notes": h.notes,
        "adjournment_reason": h.adjournment_reason,
        "caused_by": h.caused_by,
    }


@router.post("", response_model=HearingResponse, status_code=status.HTTP_201_CREATED)
def create_hearing(req: HearingCreateRequest, db: DbSession, user: IoUser) -> HearingResponse:
    case = db.get(Case, req.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    h = Hearing(
        id=str(uuid.uuid4()),
        case_id=req.case_id,
        date=req.date,
        docket_label=req.docket_label,
        stage=req.stage,
        judge_name=req.judge_name,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    _audit().append(
        AuditAction.CREATE_HEARING,
        actor_id=user.id,
        subject_id=h.id,
        metadata={"case_id": req.case_id, "date": req.date.isoformat()},
    )
    log.info("hearing.create", hearing_id=h.id[:8], case_id=req.case_id[:8])
    return _to_response(h)


@router.get("/{hearing_id}", response_model=HearingResponse)
def get_hearing(hearing_id: str, db: DbSession, user: CurrentUser) -> HearingResponse:
    h = db.get(Hearing, hearing_id)
    if not h:
        raise HTTPException(status_code=404, detail="Hearing not found")
    _audit().append(AuditAction.READ_HEARING, actor_id=user.id, subject_id=hearing_id)
    return _to_response(h)


@router.get("", response_model=list[HearingResponse])
def list_hearings(
    db: DbSession,
    user: CurrentUser,
    case_id: str | None = None,
    upcoming_only: bool = False,
    limit: int = 100,
) -> list[HearingResponse]:
    stmt = select(Hearing).order_by(Hearing.date.desc()).limit(limit)
    if case_id:
        stmt = stmt.where(Hearing.case_id == case_id)
    if upcoming_only:
        stmt = stmt.where(Hearing.date >= datetime.utcnow())
    rows = db.execute(stmt).scalars().all()
    return [_to_response(h) for h in rows]


@router.patch("/{hearing_id}", response_model=HearingResponse)
def update_hearing(
    hearing_id: str,
    req: HearingUpdateRequest,
    db: DbSession,
    user: PpUser,
) -> HearingResponse:
    h = db.get(Hearing, hearing_id)
    if not h:
        raise HTTPException(status_code=404, detail="Hearing not found")
    fields_used: list[str] = []
    for fname, val in req.model_dump(exclude_unset=True).items():
        if hasattr(h, fname):
            setattr(h, fname, val)
            fields_used.append(fname)
    # If next_hearing_date is set, update case.next_hearing
    if h.next_hearing_date:
        case = db.get(Case, h.case_id)
        if case:
            case.next_hearing = h.next_hearing_date
    db.commit()
    db.refresh(h)
    _audit().append(
        AuditAction.UPDATE_HEARING,
        actor_id=user.id,
        subject_id=hearing_id,
        fields_used=fields_used,
    )
    return _to_response(h)
