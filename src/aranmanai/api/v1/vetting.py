"""Chargesheet vetting API — gap-check a case before filing.

Per Kishore's Project DHARMA: the AI has a chargesheet vetting module
that auto-checks if a case file is missing required elements. This
endpoint is the deterministic rules version of that module.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
from aranmanai.api.deps import CurrentUser, DbSession, IoUser
from aranmanai.observability import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/vetting", tags=["vetting"])


class VettingItemResponse(BaseModel):
    code: str
    label: str
    required: bool
    passed: bool
    note: str | None = None


class VettingReportResponse(BaseModel):
    case_id: str
    fir_no: str
    checked_at: str
    passed_count: int
    failed_count: int
    required_failed: int
    verdict: str
    summary: str
    items: list[VettingItemResponse]


@router.post("/chargesheet/{case_id}", response_model=VettingReportResponse)
def vet_chargesheet(case_id: str, user: IoUser, db: DbSession) -> VettingReportResponse:
    """Vet a case's evidence before chargesheet filing.

    Returns a checklist of CrPC 173(2) elements:
    - READY: all required elements present, file the chargesheet
    - NEEDS_FIXES: 1-2 required missing, fix and re-vet
    - BLOCKED: 3+ required missing, do not file

    Per Kishore's DHARMA chargesheet vetting module — but as a
    deterministic rules engine, not an LLM judge.
    """
    svc = ChargesheetVettingService(db)
    try:
        report = svc.vet(case_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return VettingReportResponse(
        case_id=report.case_id,
        fir_no=report.fir_no,
        checked_at=report.checked_at,
        passed_count=report.passed_count,
        failed_count=report.failed_count,
        required_failed=report.required_failed,
        verdict=report.verdict,
        summary=report.summary,
        items=[VettingItemResponse(**i) for i in report.to_dict()["items"]],
    )
