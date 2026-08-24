"""AI assist routes: complaint intake, FIR draft, chargesheet draft, etc."""
from __future__ import annotations

from fastapi import APIRouter

from aranmanai.ai.services.case_diary_drafting import (
    CaseDiaryDraftingService,
    CaseDiaryRequest,
    CaseDiaryResponse,
)
from aranmanai.ai.services.chargesheet_drafting import (
    ChargesheetDraftingService,
    ChargesheetRequest,
    ChargesheetResponse,
)
from aranmanai.ai.services.complaint_intake import (
    ComplaintIntakeRequest,
    ComplaintIntakeResponse,
    ComplaintIntakeService,
)
from aranmanai.ai.services.fir_drafting import FirDraftingService, FirDraftRequest, FirDraftResponse
from aranmanai.ai.services.investigation_recommendations import (
    InvestigationRecommendationsRequest,
    InvestigationRecommendationsResponse,
    InvestigationRecommendationsService,
)
from aranmanai.api.deps import CurrentUser, DbSession, IoUser, PpUser
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter()


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


@router.post("/complaint-intake", response_model=ComplaintIntakeResponse)
def complaint_intake(req: ComplaintIntakeRequest, user: IoUser) -> ComplaintIntakeResponse:
    svc = ComplaintIntakeService()
    result = svc.intake(req)
    _audit().append(
        AuditAction.AI_COMPLAINT_INTAKE,
        actor_id=user.id,
        subject_id=result.draft_id,
        success=True,
    )
    return result


@router.post("/fir-draft", response_model=FirDraftResponse)
def fir_draft(req: FirDraftRequest, user: IoUser) -> FirDraftResponse:
    svc = FirDraftingService()
    result = svc.draft(req)
    _audit().append(
        AuditAction.AI_FIR_DRAFT,
        actor_id=user.id,
        subject_id=result.draft_id,
        fields_used=["complainant_name", "incident_time", "location", "facts", "sections_bns"],
    )
    return result


@router.post("/case-diary-draft", response_model=CaseDiaryResponse)
def case_diary_draft(req: CaseDiaryRequest, user: IoUser) -> CaseDiaryResponse:
    svc = CaseDiaryDraftingService()
    result = svc.draft(req)
    _audit().append(
        AuditAction.AI_FIR_DRAFT,  # reuse enum; case-diary has no specific
        actor_id=user.id,
        subject_id=result.draft_id,
    )
    return result


@router.post("/chargesheet-draft", response_model=ChargesheetResponse)
def chargesheet_draft(req: ChargesheetRequest, user: IoUser) -> ChargesheetResponse:
    svc = ChargesheetDraftingService()
    result = svc.draft(req)
    _audit().append(
        AuditAction.AI_CHARGESHEET_DRAFT,
        actor_id=user.id,
        subject_id=result.draft_id,
    )
    return result


@router.post("/investigation-recommendations", response_model=InvestigationRecommendationsResponse)
def investigation_recommendations(
    req: InvestigationRecommendationsRequest, user: IoUser
) -> InvestigationRecommendationsResponse:
    svc = InvestigationRecommendationsService()
    result = svc.recommend(req)
    _audit().append(
        AuditAction.AI_INVESTIGATION_RECOMMENDATIONS,
        actor_id=user.id,
        subject_id=result.rec_id,
    )
    return result
