"""Investigation recommendations service. Cure actions per detected lapse."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.investigation import build_investigation_prompt
from aranmanai.observability import get_logger

log = get_logger(__name__)


class LapseInfo(BaseModel):
    key: str
    tier: str = "UNKNOWN"  # FATAL / SERIOUS / MINOR
    description: str = ""


class InvestigationRecommendationsRequest(BaseModel):
    case_id: str
    lapses: list[LapseInfo] = Field(default_factory=list)
    case_facts: str
    evidence_list: list[str] = Field(default_factory=list)
    witness_list: list[str] = Field(default_factory=list)
    language: str = "en"


class InvestigationRecommendationsResponse(BaseModel):
    rec_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    recommendations: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str


class InvestigationRecommendationsService:
    """Generate cure-action recommendations per detected lapse."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def recommend(self, request: InvestigationRecommendationsRequest) -> InvestigationRecommendationsResponse:
        messages = build_investigation_prompt(
            case_id=request.case_id,
            lapses=[l.model_dump() for l in request.lapses],
            case_facts=request.case_facts,
            evidence_list=request.evidence_list,
            witness_list=request.witness_list,
            language=request.language,
        )
        response = self.llm.complete(messages, temperature=0.2, max_tokens=2048)
        log.info("ai.investigation_recommendations", case_id=request.case_id, lapse_count=len(request.lapses))
        return InvestigationRecommendationsResponse(recommendations=response.content, model=response.model)
