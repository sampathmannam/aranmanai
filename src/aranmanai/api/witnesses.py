"""Witness CRUD. Categorization + prep status are the levers that move
case outcomes (per Kishore + Dheeraj playbooks)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, Witness
from src.aranmanai.schemas import WitnessCreate, WitnessRead, WitnessUpdate
from src.aranmanai.security import get_current_user, record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/cases/{case_internal_id}/witnesses", tags=["witnesses"])


@router.post("", response_model=WitnessRead, status_code=status.HTTP_201_CREATED)
def create_witness(
    case_internal_id: int,
    body: WitnessCreate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Witness:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    w = Witness(
        case_id=case.id,
        name=body.name,
        type=body.type,
        contact=body.contact,
        language=body.language,
        statement_161=body.statement_161,
        prep_notes=body.prep_notes,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    record_audit(
        db, actor_id=actor.id, action="witness.create",
        subject_type="witness", subject_id=str(w.id),
        fields_used=list(body.model_dump().keys()),
        detail={"case_id": case.case_id},
    )
    log.info("witness.created id=%s case=%s by=%s", w.id, case.case_id, actor.id)
    return w


@router.get("", response_model=list[WitnessRead])
def list_witnesses(
    case_internal_id: int,
    category: str | None = None,
    type: str | None = None,
    prep_status: str | None = None,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> list[Witness]:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    q = db.query(Witness).filter(Witness.case_id == case.id)
    if category is not None:
        q = q.filter(Witness.category == category)
    if type is not None:
        q = q.filter(Witness.type == type)
    if prep_status is not None:
        q = q.filter(Witness.prep_status == prep_status)
    return q.order_by(Witness.category, Witness.name).all()


@router.get("/{witness_id}", response_model=WitnessRead)
def get_witness(
    case_internal_id: int,
    witness_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Witness:
    w = db.get(Witness, witness_id)
    if w is None or w.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Witness not found")
    case = db.get(Case, w.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return w


@router.patch("/{witness_id}", response_model=WitnessRead)
def update_witness(
    case_internal_id: int,
    witness_id: int,
    body: WitnessUpdate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Witness:
    w = db.get(Witness, witness_id)
    if w is None or w.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Witness not found")
    case = db.get(Case, w.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    fields_used: list[str] = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
        fields_used.append(k)
    w.updated_at = int(__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc).timestamp())
    db.commit()
    db.refresh(w)
    record_audit(
        db, actor_id=actor.id, action="witness.update",
        subject_type="witness", subject_id=str(w.id),
        fields_used=fields_used,
        detail={"case_id": case.case_id},
    )
    return w


@router.delete("/{witness_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_witness(
    case_internal_id: int,
    witness_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
):
    """Delete a witness. DPDP §12 right to erasure."""
    w = db.get(Witness, witness_id)
    if w is None or w.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Witness not found")
    case = db.get(Case, w.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district delete not allowed")
    db.delete(w)
    db.commit()
    record_audit(
        db, actor_id=actor.id, action="witness.delete",
        subject_type="witness", subject_id=str(w.id),
        fields_used=["*"],
        detail={"case_id": case.case_id, "dpdp_§12": True},
    )
    log.warning("witness.deleted id=%s case=%s by=%s", witness_id, case.case_id, actor.id)
    return None
