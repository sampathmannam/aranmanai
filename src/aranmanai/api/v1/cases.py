"""Case routes: CRUD + listing + status transitions."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from aranmanai.api.deps import CurrentUser, DbSession, IoUser, SpUser
from aranmanai.config import get_settings
from aranmanai.db.models.case import Case, CaseStage, CaseStatus
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog

# v1.1 Kishore review item 5: FIR-number normalizer.
# Defends the UNIQUE(fir_no, district) constraint from typo-collision:
#   "123/2025" vs "123-2025" vs " 123 2025 " all canonicalize to "123/2025".
# Canonical form: trim, collapse internal whitespace, replace dashes /
# dots with "/", strip leading zeros on the numeric part.
# The result is what is stored and what is searched.
_FIR_STRIP_RE = re.compile(r"[\s\-.]+")
_FIR_KEEP = "/"


def _normalize_fir_no(fir_no: str) -> str:
    """Canonicalize a FIR number for storage and search.

    Examples (all collapse to the same canonical form):
      "123/2025"   -> "123/2025"
      "123-2025"   -> "123/2025"
      " 123 2025 " -> "123/2025"
      "123 . 2025" -> "123/2025"
      "0123/2025"  -> "123/2025"   (leading zero stripped on the number)

    The result is at most 64 chars (FIR-no column max). The endpoint
    still validates the input shape (min 1, max 64) before this is
    called.
    """
    s = (fir_no or "").strip()
    if not s:
        return s
    s = _FIR_STRIP_RE.sub(_FIR_KEEP, s)
    # Strip leading zeros on any numeric segment, but keep a single
    # "0" if the segment was all zeros ("000/2025" -> "0/2025", not "/2025").
    parts = s.split(_FIR_KEEP)
    out = []
    for part in parts:
        if part.isdigit():
            stripped = part.lstrip("0")
            out.append(stripped or "0")
        else:
            out.append(part)
    return _FIR_KEEP.join(out)

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
    # v1.1 Kishore review item 2/3: the IO sets the POCSO/304B
    # flag at FIR-filing time (it's the IO's judgment, not derived
    # from BNS section codes). Default False. Required for F11
    # family-liaison briefings to be recorded.
    is_pocso_or_304b_case: bool = False


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
    # v1.1 Kishore review item 3: the IO can flip this on later
    # (e.g., the case is reclassified after the initial FIR).
    is_pocso_or_304b_case: bool | None = None


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

    model_config = ConfigDict(from_attributes=True)


def _to_response(c: Case) -> CaseResponse:
    return CaseResponse(
        id=c.id,
        fir_no=c.fir_no,
        district=c.district,
        court=c.court,
        judge=c.judge,
        bns_sections=c.bns_sections or [],
        bnss_sections=c.bnss_sections or [],
        bsa_sections=c.bsa_sections or [],
        facts_text=c.facts_text,
        fir_date=c.fir_date,
        next_hearing=c.next_hearing,
        last_hearing=c.last_hearing,
        judgment_date=c.judgment_date,
        status=c.status.value,
        stage=c.stage.value,
        risk_score=c.risk_score,
        io_id=c.io_id,
        pp_id=c.pp_id,
        sp_id=c.sp_id,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(req: CaseCreateRequest, db: DbSession, user: IoUser) -> CaseResponse:
    # v1.1 Kishore review item 5: normalize the FIR number so
    # "123/2025" / "123-2025" / " 123 2025 " collapse to the same
    # canonical form. Defends the UNIQUE(fir_no, district) constraint
    # from typo-collision. The original is preserved in the audit log
    # metadata so a court challenge can still see what the IO typed.
    raw_fir = req.fir_no
    fir_no = _normalize_fir_no(raw_fir)
    if not fir_no:
        raise HTTPException(
            status_code=400,
            detail="fir_no is empty after normalization (e.g. all whitespace)",
        )
    case = Case(
        id=str(uuid.uuid4()),
        fir_no=fir_no,
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
        # v1.1 Kishore review item 3: the IO sets the POCSO/304B
        # flag at FIR-filing time. Without this, the F11 endpoint
        # rejects the family liaison and the IO has no production
        # path to set the flag.
        is_pocso_or_304b_case=req.is_pocso_or_304b_case,
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
        metadata={
            "fir_no": fir_no,
            "fir_no_raw": raw_fir,
            "is_pocso_or_304b_case": req.is_pocso_or_304b_case,
        },
    )
    log.info("case.create", case_id=case.id[:8], fir_no=fir_no)
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
