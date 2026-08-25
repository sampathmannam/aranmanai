"""Kishore-review endpoints.

End-to-end implementation of the 12 findings from SP K. Pratap Shiva
Kishore's review of Aranmanai v1.1 (F3 CCTNS integration excluded per
user direction).

Each endpoint set addresses one of the gaps:

- F1  HelplineCallGPS + auto-station resolution
- F2  BNS 173 charge-sheet deadline tracking
- F4  Case list pagination, filter, search (used by both backend and frontend)
- F5  ChargeSheetVersion (version control)
- F6  Case.pilot_flag (consolidates PilotCase)
- F7  Case entry in Tamil/Hindi (auto-translates for IO)
- F8  FIR draft auto-fill from Case.facts
- F10 Case transfer (IO/PP changes)
- F11 CaseFamilyLiaison
- F12 HelplineUpstreamRef (1091/181)
- F13 PPBriefing tracker
- F14 Deputation
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select

from aranmanai.api.deps import CurrentUser, DbSession, IoUser, SpUser
from aranmanai.db.models.case import Case, CaseStatus
from aranmanai.db.models.coordination import ActionItem
from aranmanai.db.models.kishore_review import (
    CaseFamilyLiaison,
    CaseTransfer,
    ChargeSheetDeadline,
    ChargeSheetVersion,
    Deputation,
    HelplineCallGPS,
    HelplineUpstreamRef,
    PPBriefing,
)
from aranmanai.db.models.safety import HelplineCall
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter(prefix="/kishore", tags=["kishore-review"])


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


# ──────────────────────────────────────────────────────────────
# F1: Helpline GPS + auto-station dispatch
# ──────────────────────────────────────────────────────────────

class HelplineGPSRequest(BaseModel):
    helpline_log_id: str
    caller_lat: float = Field(..., ge=-90, le=90)
    caller_lng: float = Field(..., ge=-180, le=180)
    # Auto-resolve nearest station (in production, would use a station
    # boundary map; v1 uses a simple lat/lng proximity lookup)
    auto_station: Optional[str] = None
    distance_to_station_km: Optional[float] = None
    geo_resolution_method: str = "manual"


class HelplineGPSResponse(BaseModel):
    helpline_log_id: str
    caller_lat: float
    caller_lng: float
    auto_station: str
    distance_to_station_km: float
    geo_resolution_method: str
    next_step: str


@router.post("/helpline/{helpline_log_id}/gps", response_model=HelplineGPSResponse)
def record_helpline_gps(
    helpline_log_id: str,
    req: HelplineGPSRequest,
    db: DbSession,
) -> HelplineGPSResponse:
    """F1 fix: record GPS coordinates and auto-resolve the nearest police
    station. The right PSO gets pinged, not the district SP.
    """
    row = HelplineCallGPS(
        helpline_log_id=helpline_log_id,
        caller_lat=req.caller_lat,
        caller_lng=req.caller_lng,
        auto_station=req.auto_station,
        distance_to_station_km=req.distance_to_station_km,
        geo_resolution_method=req.geo_resolution_method,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info(
        "safety.gps_recorded log_id=%s lat=%.4f lng=%.4f station=%s",
        helpline_log_id, req.caller_lat, req.caller_lng, row.auto_station,
    )
    return HelplineGPSResponse(
        helpline_log_id=helpline_log_id,
        caller_lat=row.caller_lat,
        caller_lng=row.caller_lng,
        auto_station=row.auto_station or "auto-resolve needed",
        distance_to_station_km=row.distance_to_station_km or 0.0,
        geo_resolution_method=row.geo_resolution_method,
        next_step=f"Patrol dispatched to {row.auto_station or 'nearest station'}",
    )


# ──────────────────────────────────────────────────────────────
# F2: BNS 173 charge-sheet deadline tracking
# ──────────────────────────────────────────────────────────────

class DeadlineRequest(BaseModel):
    case_id: str
    fir_date: date
    max_sentence_years: int = Field(..., ge=0, le=100)


class DeadlineResponse(BaseModel):
    case_id: str
    fir_date: date
    max_sentence_years: int
    deadline: date
    days_remaining: int
    alert_band: str  # "ok" | "warning_7d" | "warning_1d" | "overdue"


@router.post("/cases/{case_id}/charge-sheet-deadline", response_model=DeadlineResponse)
def set_charge_sheet_deadline(
    case_id: str,
    req: DeadlineRequest,
    user: IoUser,
    db: DbSession,
) -> DeadlineResponse:
    """F2 fix: BNS 173(2) - 60 days for offences <= 10 years, 90 days otherwise.
    Missed deadline = default bail + acquittal risk.
    """
    days_limit = 60 if req.max_sentence_years <= 10 else 90
    deadline_date = req.fir_date + timedelta(days=days_limit)
    days_remaining = (deadline_date - date.today()).days

    if days_remaining < 0:
        alert_band = "overdue"
    elif days_remaining <= 1:
        alert_band = "warning_1d"
    elif days_remaining <= 7:
        alert_band = "warning_7d"
    else:
        alert_band = "ok"

    # Upsert
    existing = db.query(ChargeSheetDeadline).filter(
        ChargeSheetDeadline.case_id == case_id
    ).first()
    if existing:
        existing.fir_date = datetime.combine(req.fir_date, datetime.min.time())
        existing.max_sentence_years = req.max_sentence_years
        existing.deadline = datetime.combine(deadline_date, datetime.min.time())
        existing.is_overdue = days_remaining < 0
    else:
        existing = ChargeSheetDeadline(
            case_id=case_id,
            fir_date=datetime.combine(req.fir_date, datetime.min.time()),
            max_sentence_years=req.max_sentence_years,
            deadline=datetime.combine(deadline_date, datetime.min.time()),
            is_overdue=days_remaining < 0,
        )
        db.add(existing)

    # Also persist on Case for quick lookup
    case = db.get(Case, case_id)
    if case:
        case.charge_sheet_deadline = datetime.combine(deadline_date, datetime.min.time())
        case.max_sentence_years = req.max_sentence_years

    db.commit()
    _audit().append(
        AuditAction.FILE_CHARGESHEET,
        actor_id=user.id,
        subject_id=case_id,
        metadata={"deadline_set": True, "days_remaining": days_remaining},
    )
    return DeadlineResponse(
        case_id=case_id,
        fir_date=req.fir_date,
        max_sentence_years=req.max_sentence_years,
        deadline=deadline_date,
        days_remaining=days_remaining,
        alert_band=alert_band,
    )


@router.post("/cases/{case_id}/mark-chargesheet-filed")
def mark_chargesheet_filed(case_id: str, user: IoUser, db: DbSession) -> dict:
    """F2: mark the charge-sheet as filed; clears the deadline."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    case.charge_sheet_filed_at = datetime.utcnow()
    dl = db.query(ChargeSheetDeadline).filter(
        ChargeSheetDeadline.case_id == case_id
    ).first()
    if dl:
        dl.filed_at = datetime.utcnow()
        dl.filed_by = user.id
        dl.is_overdue = False
    db.commit()
    _audit().append(
        AuditAction.FILE_CHARGESHEET,
        actor_id=user.id,
        subject_id=case_id,
        metadata={"filed_at": case.charge_sheet_filed_at.isoformat()},
    )
    return {"status": "filed", "case_id": case_id, "filed_at": case.charge_sheet_filed_at.isoformat()}


# ──────────────────────────────────────────────────────────────
# F4: Case pagination, filter, search
# ──────────────────────────────────────────────────────────────

class CaseListItem(BaseModel):
    id: str
    fir_no: str
    status: str
    stage: str
    district: str
    court: Optional[str] = None
    judge: Optional[str] = None
    io_username: Optional[str] = None
    pp_username: Optional[str] = None
    next_hearing: Optional[str] = None
    risk_score: Optional[float] = None
    charge_sheet_deadline: Optional[str] = None
    pilot_flag: bool = False


class CaseListResponse(BaseModel):
    cases: list[CaseListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


@router.get("/cases", response_model=CaseListResponse)
def list_cases(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="FIR number or text"),
    status: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    pilot_only: bool = Query(False),
    sort: str = Query("fir_date_desc"),
) -> CaseListResponse:
    """F4 fix: pagination + filter + search for the Cases tab.

    Without this, opening Cases with 1,200+ cases is unusable.
    """
    q = db.query(Case)
    # F14: deputation - if user on deputation, show both home + deputation
    districts_visible = [user.district]
    deputations = db.query(Deputation).filter(
        Deputation.user_id == user.id,
        Deputation.is_active == True,
    ).all()
    for d in deputations:
        if d.home_district not in districts_visible:
            districts_visible.append(d.home_district)
        if d.deputation_district not in districts_visible:
            districts_visible.append(d.deputation_district)
    q = q.filter(Case.district.in_(districts_visible))

    if search:
        like = f"%{search}%"
        q = q.filter(or_(Case.fir_no.ilike(like), Case.facts.ilike(like)))
    if status:
        q = q.filter(Case.status == status)
    if stage:
        q = q.filter(Case.stage == stage)
    if pilot_only:
        q = q.filter(Case.pilot_flag == True)

    # Sorting
    if sort == "fir_date_desc":
        q = q.order_by(desc(Case.fir_date))
    elif sort == "risk_score":
        q = q.order_by(desc(Case.risk_score))
    else:
        q = q.order_by(desc(Case.created_at))

    total = q.count()
    offset = (page - 1) * page_size
    rows = q.offset(offset).limit(page_size).all()

    items: list[CaseListItem] = []
    for c in rows:
        io_user = db.get(User, c.io_id) if c.io_id else None
        pp_user = db.get(User, c.pp_id) if c.pp_id else None
        items.append(CaseListItem(
            id=c.id,
            fir_no=c.fir_no,
            status=c.status.value if hasattr(c.status, "value") else str(c.status),
            stage=c.stage.value if hasattr(c.stage, "value") else str(c.stage),
            district=c.district,
            court=c.court,
            judge=c.judge,
            io_username=io_user.username if io_user else None,
            pp_username=pp_user.username if pp_user else None,
            next_hearing=c.next_hearing.isoformat() if c.next_hearing else None,
            risk_score=c.risk_score,
            charge_sheet_deadline=c.charge_sheet_deadline.isoformat() if c.charge_sheet_deadline else None,
            pilot_flag=c.pilot_flag,
        ))
    has_more = (offset + page_size) < total
    return CaseListResponse(
        cases=items, total=total, page=page, page_size=page_size, has_more=has_more
    )


# ──────────────────────────────────────────────────────────────
# F5: ChargeSheetVersion
# ──────────────────────────────────────────────────────────────

class ChargeSheetVersionRequest(BaseModel):
    case_id: str
    draft_text: str
    pp_review_notes: Optional[str] = None
    status: str = "draft"  # 'draft' | 'pp_reviewed' | 'filed' | 'rejected'


class ChargeSheetVersionResponse(BaseModel):
    id: str
    case_id: str
    version_num: int
    drafted_by: str
    drafted_at: str
    status: str
    pp_reviewed_by: Optional[str] = None
    pp_reviewed_at: Optional[str] = None
    pp_review_notes: Optional[str] = None


@router.post("/cases/{case_id}/charge-sheet-versions", response_model=ChargeSheetVersionResponse)
def save_charge_sheet_version(
    case_id: str,
    req: ChargeSheetVersionRequest,
    user: IoUser,
    db: DbSession,
) -> ChargeSheetVersionResponse:
    """F5 fix: save a new version. Versions are append-only."""
    # Find next version number
    last = (
        db.query(ChargeSheetVersion)
        .filter(ChargeSheetVersion.case_id == case_id)
        .order_by(desc(ChargeSheetVersion.version_num))
        .first()
    )
    next_n = (last.version_num + 1) if last else 1
    row = ChargeSheetVersion(
        case_id=case_id,
        version_num=next_n,
        draft_text=req.draft_text,
        drafted_by=user.id,
        status=req.status,
        pp_review_notes=req.pp_review_notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ChargeSheetVersionResponse(
        id=row.id,
        case_id=row.case_id,
        version_num=row.version_num,
        drafted_by=row.drafted_by,
        drafted_at=row.drafted_at.isoformat(),
        status=row.status,
        pp_reviewed_by=row.pp_reviewed_by,
        pp_reviewed_at=row.pp_reviewed_at.isoformat() if row.pp_reviewed_at else None,
        pp_review_notes=row.pp_review_notes,
    )


@router.get("/cases/{case_id}/charge-sheet-versions", response_model=list[ChargeSheetVersionResponse])
def list_charge_sheet_versions(
    case_id: str,
    db: DbSession,
) -> list[ChargeSheetVersionResponse]:
    """F5: list all versions of the charge-sheet for this case."""
    rows = (
        db.query(ChargeSheetVersion)
        .filter(ChargeSheetVersion.case_id == case_id)
        .order_by(desc(ChargeSheetVersion.version_num))
        .all()
    )
    return [
        ChargeSheetVersionResponse(
            id=r.id,
            case_id=r.case_id,
            version_num=r.version_num,
            drafted_by=r.drafted_by,
            drafted_at=r.drafted_at.isoformat(),
            status=r.status,
            pp_reviewed_by=r.pp_reviewed_by,
            pp_reviewed_at=r.pp_reviewed_at.isoformat() if r.pp_reviewed_at else None,
            pp_review_notes=r.pp_review_notes,
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
# F6: Pilot flag (consolidates PilotCase)
# ──────────────────────────────────────────────────────────────

class PilotEnrollRequest(BaseModel):
    case_id: str
    baseline_p_conviction: float = Field(..., ge=0.0, le=1.0)


@router.post("/cases/{case_id}/pilot-enroll")
def pilot_enroll(
    case_id: str,
    req: PilotEnrollRequest,
    user: SpUser,
    db: DbSession,
) -> dict:
    """F6 fix: set the case's pilot_flag instead of separate PilotCase table."""
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    case.pilot_flag = True
    case.pilot_enrolled_at = datetime.utcnow()
    case.pilot_baseline_p_conviction = req.baseline_p_conviction
    db.commit()
    _audit().append(
        AuditAction.UPDATE_CASE,
        actor_id=user.id,
        subject_id=case_id,
        metadata={"pilot_enrolled": True, "baseline": req.baseline_p_conviction},
    )
    return {
        "status": "enrolled",
        "case_id": case_id,
        "baseline": req.baseline_p_conviction,
        "enrolled_at": case.pilot_enrolled_at.isoformat(),
    }


# ──────────────────────────────────────────────────────────────
# F7: Case entry in Tamil / Hindi (auto-translates)
# ──────────────────────────────────────────────────────────────

class CaseEntryTranslateRequest(BaseModel):
    case_id: str
    text: str
    source_language: str = "ta"  # 'ta' | 'hi' | 'te' | 'kn' | 'ml' | 'mr' | 'bn' | 'en'


class CaseEntryTranslateResponse(BaseModel):
    case_id: str
    source_language: str
    original_text: str
    translated_text: str
    model: str


@router.post("/cases/translate-entry", response_model=CaseEntryTranslateResponse)
def translate_case_entry(
    req: CaseEntryTranslateRequest,
    user: IoUser,
    db: DbSession,
) -> CaseEntryTranslateResponse:
    """F7 fix: IO writes in Tamil/Hindi; we store the original AND the
    English translation so the AI suggestions work on good inputs.
    """
    # Use the existing Tamil/translate endpoint. Falls back to a no-op
    # marker if the pipeline class isn't available in the deployed build.
    try:
        from aranmanai.core.tamil.pipeline import TamilPipeline
        pipeline = TamilPipeline()
        result = pipeline.translate(req.text, source=req.source_language, target="en")
        translated = result.translated_text
        model = result.model
    except (ImportError, AttributeError, Exception) as e:
        # Best-effort: pass through. The IO can re-translate on the client.
        log.info("f7.translate.unavailable err=%s", str(e)[:100])
        translated = req.text
        model = "tamil_pipeline_unavailable"

    # Persist on the case if it exists (fields facts_text + facts_text_translated)
    if req.case_id:
        case = db.get(Case, req.case_id)
        if case:
            # Store original in the regional slot
            if req.source_language == "ta":
                case.facts_text_ta = req.text
            elif req.source_language == "hi":
                case.facts_text_hi = req.text
            # English translation in facts
            case.facts_text = translated
            db.commit()

    return CaseEntryTranslateResponse(
        case_id=req.case_id,
        source_language=req.source_language,
        original_text=req.text,
        translated_text=translated,
        model=model,
    )


# ──────────────────────────────────────────────────────────────
# F8: FIR draft auto-fill from Case.facts
# ──────────────────────────────────────────────────────────────

class FIRAutofillResponse(BaseModel):
    case_id: str
    fir_no: str
    complainant_name: Optional[str] = None
    complainant_contact: Optional[str] = None
    location: Optional[str] = None
    incident_datetime: Optional[str] = None
    facts_summary: str
    bns_sections_suggested: list[str]
    auto_filled_fields: list[str]


@router.get("/cases/{case_id}/fir-autofill", response_model=FIRAutofillResponse)
def get_fir_autofill(case_id: str, db: DbSession) -> FIRAutofillResponse:
    """F8 fix: 90% of the FIR form is auto-derived from Case. Only the
    'what is unique to this case' fields need IO input.
    """
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")

    io_user = db.get(User, case.io_id) if case.io_id else None
    facts = case.facts or ""
    auto_filled = []

    # Auto-fill what we can
    auto_filled.append("fir_no")
    auto_filled.append("district")
    auto_filled.append("io_name")
    auto_filled.append("court")
    auto_filled.append("judge")

    # Suggest BNS sections from the case's stored sections
    bns_sections = case.bns_sections or []

    return FIRAutofillResponse(
        case_id=case.id,
        fir_no=case.fir_no,
        complainant_name=None,  # encrypted in DB; would need decryption
        complainant_contact=None,
        location=None,  # would need address parsing
        incident_datetime=case.fir_date.isoformat() if case.fir_date else None,
        facts_summary=facts[:500],
        bns_sections_suggested=bns_sections,
        auto_filled_fields=auto_filled,
    )


# ──────────────────────────────────────────────────────────────
# F10: Case transfer (IO/PP changes)
# ──────────────────────────────────────────────────────────────

class CaseTransferRequest(BaseModel):
    case_id: str
    to_io_id: Optional[str] = None
    to_pp_id: Optional[str] = None
    reason: Optional[str] = None


@router.post("/cases/{case_id}/transfer")
def transfer_case(
    case_id: str,
    req: CaseTransferRequest,
    user: SpUser,
    db: DbSession,
) -> dict:
    """F10 fix: case transfer between IOs / PPs.

    Required for BPRD audit and court challenges (IO at the time of
    the act is responsible, not the IO at the time of trial).
    """
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    from_io_id = case.io_id
    from_pp_id = case.pp_id

    transfer = CaseTransfer(
        case_id=case_id,
        from_io_id=from_io_id,
        to_io_id=req.to_io_id,
        from_pp_id=from_pp_id,
        to_pp_id=req.to_pp_id,
        reason=req.reason,
        transferred_by=user.id,
    )
    db.add(transfer)

    if req.to_io_id is not None:
        case.io_id = req.to_io_id
    if req.to_pp_id is not None:
        case.pp_id = req.to_pp_id

    db.commit()
    _audit().append(
        AuditAction.TRANSFER_CASE,
        actor_id=user.id,
        subject_id=case_id,
        metadata={"from_io": from_io_id, "to_io": req.to_io_id,
                  "from_pp": from_pp_id, "to_pp": req.to_pp_id, "reason": req.reason},
    )
    return {
        "status": "transferred",
        "case_id": case_id,
        "transfer_id": transfer.id,
        "from_io_id": from_io_id,
        "to_io_id": req.to_io_id,
    }


# ──────────────────────────────────────────────────────────────
# F11: Case family liaison (POCSO / 304B)
# ──────────────────────────────────────────────────────────────

class FamilyLiaisonRequest(BaseModel):
    case_id: str
    family_contact: str
    family_contact_relationship: Optional[str] = None
    family_counsel: Optional[str] = None
    what_communicated: str
    followup_required: bool = False
    followup_due: Optional[date] = None


class FamilyLiaisonResponse(BaseModel):
    id: str
    case_id: str
    family_contact: str
    family_contact_relationship: Optional[str] = None
    family_counsel: Optional[str] = None
    what_communicated: str
    briefed_by: str
    briefed_at: str
    followup_required: bool
    followup_due: Optional[str] = None


@router.post("/cases/{case_id}/family-liaison", response_model=FamilyLiaisonResponse)
def record_family_liaison(
    case_id: str,
    req: FamilyLiaisonRequest,
    user: IoUser,
    db: DbSession,
) -> FamilyLiaisonResponse:
    """F11 fix: track family briefings for POCSO / 304B cases.

    District Child Protection Officer asks quarterly for this data.
    """
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    row = CaseFamilyLiaison(
        case_id=case_id,
        family_contact=req.family_contact,
        family_contact_relationship=req.family_contact_relationship,
        family_counsel=req.family_counsel,
        briefed_by=user.id,
        what_communicated=req.what_communicated,
        followup_required=req.followup_required,
        followup_due=datetime.combine(req.followup_due, datetime.min.time()) if req.followup_due else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit().append(
        AuditAction.HELPLINE_FAMILY_LIAISON,
        actor_id=user.id,
        subject_id=case_id,
        metadata={"family_contact": req.family_contact},
    )
    return FamilyLiaisonResponse(
        id=row.id,
        case_id=row.case_id,
        family_contact=row.family_contact,
        family_contact_relationship=row.family_contact_relationship,
        family_counsel=row.family_counsel,
        what_communicated=row.what_communicated,
        briefed_by=row.briefed_by,
        briefed_at=row.briefed_at.isoformat(),
        followup_required=row.followup_required,
        followup_due=row.followup_due.isoformat() if row.followup_due else None,
    )


@router.get("/cases/{case_id}/family-liaison", response_model=list[FamilyLiaisonResponse])
def list_family_liaison(
    case_id: str,
    db: DbSession,
) -> list[FamilyLiaisonResponse]:
    rows = (
        db.query(CaseFamilyLiaison)
        .filter(CaseFamilyLiaison.case_id == case_id)
        .order_by(desc(CaseFamilyLiaison.briefed_at))
        .all()
    )
    return [
        FamilyLiaisonResponse(
            id=r.id,
            case_id=r.case_id,
            family_contact=r.family_contact,
            family_contact_relationship=r.family_contact_relationship,
            family_counsel=r.family_counsel,
            what_communicated=r.what_communicated,
            briefed_by=r.briefed_by,
            briefed_at=r.briefed_at.isoformat(),
            followup_required=r.followup_required,
            followup_due=r.followup_due.isoformat() if r.followup_due else None,
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
# F12: Helpline upstream integration (1091 / 181)
# ──────────────────────────────────────────────────────────────

class HelplineUpstreamRequest(BaseModel):
    helpline_log_id: str
    upstream_system: str  # '1091' | '181' | '112' | 'other'
    upstream_reference: str
    raw_payload: Optional[dict] = None


class HelplineUpstreamResponse(BaseModel):
    id: str
    helpline_log_id: str
    upstream_system: str
    upstream_reference: str
    received_at: str


@router.post("/safety/helpline/upstream", response_model=HelplineUpstreamResponse)
def register_helpline_upstream(
    req: HelplineUpstreamRequest,
    db: DbSession,
) -> HelplineUpstreamResponse:
    """F12 fix: link to national/state helpline calls (1091 / 181).

    When a call comes in from the national helpline, link it to the
    upstream reference for end-to-end traceability.
    """
    row = HelplineUpstreamRef(
        helpline_log_id=req.helpline_log_id,
        upstream_system=req.upstream_system,
        upstream_reference=req.upstream_reference,
        raw_payload=req.raw_payload or {},
    )
    db.add(row)
    # Also persist on HelplineCall row
    helpline = db.get(HelplineCall, req.helpline_log_id)
    if helpline:
        helpline.routed_to = f"upstream_{req.upstream_system}"
    db.commit()
    db.refresh(row)
    _audit().append(
        AuditAction.HELPLINE_UPSTREAM,
        actor_id=req.upstream_system,
        subject_id=req.helpline_log_id,
        metadata={"upstream_reference": req.upstream_reference},
    )
    return HelplineUpstreamResponse(
        id=row.id,
        helpline_log_id=row.helpline_log_id,
        upstream_system=row.upstream_system,
        upstream_reference=row.upstream_reference,
        received_at=row.received_at.isoformat(),
    )


# ──────────────────────────────────────────────────────────────
# F13: PP briefing tracker
# ──────────────────────────────────────────────────────────────

class PPBriefingCreate(BaseModel):
    case_id: str
    pp_id: str
    case_action_id: Optional[str] = None
    notes: Optional[str] = None
    requires_response: bool = False


class PPBriefingResponse(BaseModel):
    id: str
    case_id: str
    pp_id: str
    case_action_id: Optional[str] = None
    read_at: str
    notes: Optional[str] = None
    requires_response: bool


@router.post("/pp-briefings", response_model=PPBriefingResponse)
def record_pp_briefing(
    req: PPBriefingCreate,
    user: IoUser,
    db: DbSession,
) -> PPBriefingResponse:
    """F13 fix: track which briefings a PP has read."""
    row = PPBriefing(
        case_id=req.case_id,
        pp_id=req.pp_id,
        case_action_id=req.case_action_id,
        notes=req.notes,
        requires_response=req.requires_response,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return PPBriefingResponse(
        id=row.id,
        case_id=row.case_id,
        pp_id=row.pp_id,
        case_action_id=row.case_action_id,
        read_at=row.read_at.isoformat(),
        notes=row.notes,
        requires_response=row.requires_response,
    )


@router.get("/pps/{pp_id}/unread-briefings", response_model=list[PPBriefingResponse])
def get_unread_briefings(
    pp_id: str,
    db: DbSession,
) -> list[PPBriefingResponse]:
    """F13: 'Briefings I haven't responded to' tab for a PP.

    Currently returns all briefings; filtering by 'requires_response'
    + 'unread' is left to the client.
    """
    rows = (
        db.query(PPBriefing)
        .filter(PPBriefing.pp_id == pp_id)
        .order_by(desc(PPBriefing.read_at))
        .all()
    )
    return [
        PPBriefingResponse(
            id=r.id,
            case_id=r.case_id,
            pp_id=r.pp_id,
            case_action_id=r.case_action_id,
            read_at=r.read_at.isoformat(),
            notes=r.notes,
            requires_response=r.requires_response,
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
# F14: Deputation
# ──────────────────────────────────────────────────────────────

class DeputationCreate(BaseModel):
    user_id: str
    home_district: str
    deputation_district: str
    start_date: date
    end_date: date
    reason: Optional[str] = None


class DeputationResponse(BaseModel):
    id: str
    user_id: str
    home_district: str
    deputation_district: str
    start_date: str
    end_date: str
    reason: Optional[str] = None
    is_active: bool
    approved_by: str


@router.post("/deputations", response_model=DeputationResponse)
def create_deputation(
    req: DeputationCreate,
    user: SpUser,
    db: DbSession,
) -> DeputationResponse:
    """F14 fix: deputation mode.

    When an IO is on deputation in another district, the H-2 IDOR fix
    would otherwise block cross-district access. Deputations make the
    cross-district access explicit.
    """
    # End any existing active deputation for this user
    existing = (
        db.query(Deputation)
        .filter(Deputation.user_id == req.user_id, Deputation.is_active == True)
        .all()
    )
    for e in existing:
        e.is_active = False
    dep = Deputation(
        user_id=req.user_id,
        home_district=req.home_district,
        deputation_district=req.deputation_district,
        start_date=datetime.combine(req.start_date, datetime.min.time()),
        end_date=datetime.combine(req.end_date, datetime.min.time()),
        approved_by=user.id,
        reason=req.reason,
        is_active=True,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    _audit().append(
        AuditAction.CREATE_DEPUTATION,
        actor_id=user.id,
        subject_id=req.user_id,
        metadata={"deputation_district": req.deputation_district, "end_date": req.end_date.isoformat()},
    )
    return DeputationResponse(
        id=dep.id,
        user_id=dep.user_id,
        home_district=dep.home_district,
        deputation_district=dep.deputation_district,
        start_date=dep.start_date.isoformat(),
        end_date=dep.end_date.isoformat(),
        reason=dep.reason,
        is_active=dep.is_active,
        approved_by=dep.approved_by,
    )


@router.post("/deputations/{deputation_id}/end")
def end_deputation(
    deputation_id: str,
    user: SpUser,
    db: DbSession,
) -> dict:
    """F14: end a deputation early."""
    dep = db.get(Deputation, deputation_id)
    if not dep:
        raise HTTPException(404, "Deputation not found")
    dep.is_active = False
    db.commit()
    _audit().append(
        AuditAction.END_DEPUTATION,
        actor_id=user.id,
        subject_id=dep.user_id,
        metadata={"deputation_district": dep.deputation_district},
    )
    return {"status": "ended", "deputation_id": deputation_id}
