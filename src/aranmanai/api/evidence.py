"""Evidence CRUD. Tracks chain-of-custody + FSL status per case."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, Evidence
from src.aranmanai.schemas import EvidenceCreate, EvidenceRead, EvidenceUpdate
from src.aranmanai.security import get_current_user, record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/cases/{case_internal_id}/evidence", tags=["evidence"])


@router.post("", response_model=EvidenceRead, status_code=status.HTTP_201_CREATED)
def create_evidence(
    case_internal_id: int,
    body: EvidenceCreate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Evidence:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    e = Evidence(case_id=case.id, **body.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    record_audit(
        db, actor_id=actor.id, action="evidence.create",
        subject_type="evidence", subject_id=str(e.id),
        fields_used=list(body.model_dump().keys()),
        detail={"case_id": case.case_id, "type": body.type},
    )
    log.info("evidence.created id=%s case=%s type=%s by=%s", e.id, case.case_id, body.type, actor.id)
    return e


@router.get("", response_model=list[EvidenceRead])
def list_evidence(
    case_internal_id: int,
    type: str | None = None,
    chain_status: str | None = None,
    fsl_status: str | None = None,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> list[Evidence]:
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    q = db.query(Evidence).filter(Evidence.case_id == case.id)
    if type is not None:
        q = q.filter(Evidence.type == type)
    if chain_status is not None:
        q = q.filter(Evidence.chain_status == chain_status)
    if fsl_status is not None:
        q = q.filter(Evidence.fsl_status == fsl_status)
    return q.order_by(Evidence.type, Evidence.id).all()


@router.get("/{evidence_id}", response_model=EvidenceRead)
def get_evidence(
    case_internal_id: int,
    evidence_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Evidence:
    e = db.get(Evidence, evidence_id)
    if e is None or e.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    case = db.get(Case, e.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return e


@router.patch("/{evidence_id}", response_model=EvidenceRead)
def update_evidence(
    case_internal_id: int,
    evidence_id: int,
    body: EvidenceUpdate,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
) -> Evidence:
    e = db.get(Evidence, evidence_id)
    if e is None or e.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    case = db.get(Case, e.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    fields_used: list[str] = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
        fields_used.append(k)
    e.updated_at = int(__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc).timestamp())
    db.commit()
    db.refresh(e)
    record_audit(
        db, actor_id=actor.id, action="evidence.update",
        subject_type="evidence", subject_id=str(e.id),
        fields_used=fields_used,
        detail={"case_id": case.case_id},
    )
    return e


@router.delete("/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_evidence(
    case_internal_id: int,
    evidence_id: int,
    db: Session = Depends(get_db),
    actor: "User" = Depends(get_current_user),
):
    e = db.get(Evidence, evidence_id)
    if e is None or e.case_id != case_internal_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    case = db.get(Case, e.case_id)
    if case is None or (actor.role == "SP" and case.district != actor.district):
        raise HTTPException(status_code=403, detail="Cross-district delete not allowed")
    db.delete(e)
    db.commit()
    record_audit(
        db, actor_id=actor.id, action="evidence.delete",
        subject_type="evidence", subject_id=str(evidence_id),
        fields_used=["*"],
    )
    return None
