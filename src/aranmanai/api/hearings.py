"""Hearing CRUD. Per-hearing attendance + outcome tracking.
Used by /cms/daily-calendar to show what's coming up today."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, Hearing
from src.aranmanai.schemas import HearingCreate, HearingRead, HearingUpdate
from src.aranmanai.security import get_current_user, record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/cases/{case_internal_id}/hearings", tags=["hearings"])


@router.post("", response_model=HearingRead, status_code=status.HTTP_201_CREATED)
def create_hearing(
    case_internal_id: int,
    body: HearingCreate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Hearing:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    h = Hearing(case_id=case.id, **body.model_dump())
    db.add(h)
    db.commit()
    db.refresh(h)
    record_audit(
        db, actor_id=actor.id, action="hearing.create",
        subject_type="hearing", subject_id=str(h.id),
        fields_used=list(body.model_dump().keys()),
        detail={"case_id": case.case_id, "date": body.date},
    )
    log.info("hearing.created id=%s case=%s date=%s by=%s", h.id, case.case_id, body.date, actor.id)
    return h


@router.get("", response_model=list[HearingRead])
def list_hearings(
    case_internal_id: int,
    from_date: int | None = Query(default=None, description="Unix epoch, inclusive"),
    to_date: int | None = Query(default=None, description="Unix epoch, inclusive"),
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> list[Hearing]:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    q = db.query(Hearing).filter(Hearing.case_id == case.id)
    if from_date is not None:
        q = q.filter(Hearing.date >= from_date)
    if to_date is not None:
        q = q.filter(Hearing.date <= to_date)
    return q.order_by(Hearing.date.asc()).all()


@router.get("/{hearing_id}", response_model=HearingRead)
def get_hearing(
    case_internal_id: int,
    hearing_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Hearing:
    h = db.get(Hearing, hearing_id)
    if h is None or h.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Hearing not found")
    case = db.get(Case, h.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return h


@router.patch("/{hearing_id}", response_model=HearingRead)
def update_hearing(
    case_internal_id: int,
    hearing_id: int,
    body: HearingUpdate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Hearing:
    h = db.get(Hearing, hearing_id)
    if h is None or h.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Hearing not found")
    case = db.get(Case, h.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    fields_used: list[str] = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
        fields_used.append(k)
    db.commit()
    db.refresh(h)
    record_audit(
        db, actor_id=actor.id, action="hearing.update",
        subject_type="hearing", subject_id=str(h.id),
        fields_used=fields_used,
        detail={"case_id": case.case_id},
    )
    return h


@router.delete("/{hearing_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_hearing(
    case_internal_id: int,
    hearing_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
):
    h = db.get(Hearing, hearing_id)
    if h is None or h.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Hearing not found")
    case = db.get(Case, h.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district delete not allowed")
    db.delete(h)
    db.commit()
    record_audit(
        db, actor_id=actor.id, action="hearing.delete",
        subject_type="hearing", subject_id=str(hearing_id),
        fields_used=["*"],
    )
    return None
