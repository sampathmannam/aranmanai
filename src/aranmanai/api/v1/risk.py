"""Risk-scoring routes (advisory)."""
from __future__ import annotations

from fastapi import APIRouter

from aranmanai.ai.services.risk_scoring import RiskScoreRequest, RiskScoreResponse, RiskScoringService
from aranmanai.api.deps import IoUser
from aranmanai.config import get_settings
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog

log = get_logger(__name__)
router = APIRouter()


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


@router.post("/score", response_model=RiskScoreResponse)
def score_case(req: RiskScoreRequest, user: IoUser) -> RiskScoreResponse:
    svc = RiskScoringService()
    result = svc.score(req)
    _audit().append(
        AuditAction.AI_RISK_SCORE,
        actor_id=user.id,
        subject_id=req.case_id,
        success=True,
        metadata={"score": result.score, "band": result.band},
    )
    return result
