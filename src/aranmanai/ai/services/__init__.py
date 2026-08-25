"""AI assist services. Each service uses the LLM client + a prompt template."""
from aranmanai.ai.services.case_diary_drafting import CaseDiaryDraftingService
from aranmanai.ai.services.chargesheet_drafting import ChargesheetDraftingService
from aranmanai.ai.services.complaint_intake import ComplaintIntakeService
from aranmanai.ai.services.cross_exam_prep import CrossExamPrepService
from aranmanai.ai.services.fir_drafting import FirDraftingService
from aranmanai.ai.services.investigation_recommendations import InvestigationRecommendationsService
from aranmanai.ai.services.risk_scoring import RiskScoringService

__all__ = [
    "ComplaintIntakeService",
    "FirDraftingService",
    "CaseDiaryDraftingService",
    "ChargesheetDraftingService",
    "CrossExamPrepService",
    "InvestigationRecommendationsService",
    "RiskScoringService",
]
