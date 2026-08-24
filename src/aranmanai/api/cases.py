"""Case CRUD. The single largest table; every endpoint writes to audit log."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, User
from src.aranmanai.schemas import CaseCreate, CaseRead, CaseUpdate, CaseWithWitnesses
from src.aranmanai.security import get_current_user, record_audit, require_roles

log = get_logger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])


def _now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(
    body: CaseCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Case:
    """Create a new case. SP / IO / PP can create. PP is rare but allowed for handoffs."""
    existing = db.query(Case).filter(Case.case_id == body.case_id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Case with case_id '{body.case_id}' already exists",
        )
    case = Case(
        case_id=body.case_id,
        fir_no=body.fir_no,
        sections=body.sections,
        offence=body.offence,
        district=body.district,
        court=body.court,
        judge=body.judge,
        io_id=body.io_id,
        pp_id=body.pp_id,
        facts_text=body.facts_text,
        next_hearing=body.next_hearing,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    record_audit(
        db, actor_id=actor.id, action="case.create",
        subject_type="case", subject_id=case.case_id,
        fields_used=list(body.model_dump().keys()),
    )
    log.info("case.created case_id=%s by=%s", case.case_id, actor.id)
    return case


@router.get("", response_model=list[CaseRead])
def list_cases(
    district: str | None = None,
    status_filter: str = Query(None, alias="status"),
    stage: str | None = None,
    io_id: int | None = None,
    pp_id: int | None = None,
    min_risk: float = Query(None, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[Case]:
    """List cases with filters. SP is scoped to own district."""
    q = db.query(Case)
    if actor.role == "SP":
        q = q.filter(Case.district == actor.district)
    elif district is not None:
        q = q.filter(Case.district == district)
    if status_filter is not None:
        q = q.filter(Case.status == status_filter)
    if stage is not None:
        q = q.filter(Case.stage == stage)
    if io_id is not None:
        q = q.filter(Case.io_id == io_id)
    if pp_id is not None:
        q = q.filter(Case.pp_id == pp_id)
    if min_risk is not None:
        q = q.filter(Case.acquittal_risk >= min_risk)
    return (
        q.order_by(
            Case.next_hearing.asc().nullslast(),
            Case.acquittal_risk.desc().nullslast(),
        )
        .limit(limit)
        .all()
    )


@router.get("/by-case-id/{case_id}", response_model=CaseRead)
def get_case_by_external_id(
    case_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Case:
    """Get one case by external case_id (the string ID used in URLs + audit)."""
    case = db.query(Case).filter(Case.case_id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case with case_id '{case_id}' not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return case


@router.get("/{case_internal_id}", response_model=CaseRead)
def get_case(
    case_internal_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Case:
    """Get one case by internal ID. (Use /cases/by-case-id/{case_id} for external ID.)"""
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return case


@router.get("/{case_internal_id}/with-witnesses", response_model=CaseWithWitnesses)
def get_case_with_witnesses(
    case_internal_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Case:
    """Get one case + all its witnesses. Used by /sp/cases-at-risk dashboard."""
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return case


@router.patch("/{case_internal_id}", response_model=CaseRead)
def update_case(
    case_internal_id: int,
    body: CaseUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Case:
    """Update a case. Partial update — only fields present in body are touched."""
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    fields_used: list[str] = []
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(case, k, v)
        fields_used.append(k)
    case.last_update = _now()
    db.commit()
    db.refresh(case)
    record_audit(
        db, actor_id=actor.id, action="case.update",
        subject_type="case", subject_id=case.case_id,
        fields_used=fields_used,
    )
    log.info("case.updated case_id=%s by=%s fields=%s", case.case_id, actor.id, fields_used)
    return case


@router.delete("/{case_internal_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_case(
    case_internal_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin", "SP")),
):
    """Hard-delete a case + cascade its witnesses/hearings/evidence. Admin or SP only."""
    case = db.get(Case, case_internal_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if admin.role == "SP" and case.district != admin.district:
        raise HTTPException(status_code=403, detail="Cross-district delete not allowed")
    case_id_str = case.case_id
    db.delete(case)
    db.commit()
    record_audit(
        db, actor_id=admin.id, action="case.delete",
        subject_type="case", subject_id=case_id_str,
        fields_used=["*"], success=True,
    )
    log.warning("case.deleted case_id=%s by=%s", case_id_str, admin.id)
    return None
