"""Acquittal-risk scoring service. ADVISORY. Combines LightGBM model + LLM narrative."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.risk_score import build_risk_prompt
from aranmanai.core.risk.features import compute_features
from aranmanai.core.risk.predictor import RiskPredictor
from aranmanai.observability import get_logger

log = get_logger(__name__)

VALID_EVIDENCE_STRENGTH = ("STRONG", "MEDIUM", "WEAK")
VALID_FSL_STATUS = ("not_sent", "in_queue", "returned", "overdue", "sent")


class RiskScoreRequest(BaseModel):
    case_id: str = Field(..., min_length=1, max_length=36)
    case_facts: str = Field(..., min_length=1)
    lapses: list[dict] = Field(default_factory=list, max_length=50)
    evidence_strength: Literal["STRONG", "MEDIUM", "WEAK"] = "MEDIUM"
    witness_count: int = Field(0, ge=0)
    hostile_witness_count: int = Field(0, ge=0)
    fsl_status: Literal["not_sent", "in_queue", "returned", "overdue", "sent"] = "not_sent"
    bnss_173_compliant: bool = False
    language: str = "en"

    @field_validator("lapses")
    @classmethod
    def _lapses_size(cls, v):
        # M-4 fix: cap per-element description to prevent prompt-injection
        # payloads and to keep total prompt size bounded
        for l in v:
            desc = l.get("description", "")
            if isinstance(desc, str) and len(desc) > 1000:
                l["description"] = desc[:1000]
        return v

    @field_validator("hostile_witness_count")
    @classmethod
    def _hostile_le_total(cls, v, info):
        wc = info.data.get("witness_count", 0)
        if v > wc:
            # Clamp to total instead of failing — better UX
            return wc
        return v

    @field_validator("case_facts")
    @classmethod
    def _facts_size(cls, v):
        if len(v) > 100_000:
            raise ValueError("case_facts too large (max 100k chars)")
        return v


class RiskScoreResponse(BaseModel):
    score_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    score: float  # 0-1, higher = more likely acquittal (i.e. more risky)
    band: str  # low / medium / high
    narrative: str
    contributing_factors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str
    # ADVISORY — never used for automated decisions
    advisory_only: bool = True


class RiskScoringService:
    """Score case acquittal-risk (advisory). Combines ML model + LLM narrative."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()
        self.predictor = RiskPredictor()

    def score(self, request: RiskScoreRequest) -> RiskScoreResponse:
        features = compute_features(
            evidence_strength=request.evidence_strength,
            witness_count=request.witness_count,
            hostile_witness_count=request.hostile_witness_count,
            fsl_status=request.fsl_status,
            bnss_173_compliant=request.bnss_173_compliant,
            lapse_count=len(request.lapses),
            fatal_lapse_count=sum(1 for l in request.lapses if l.get("tier") == "FATAL"),
            offence_type="other",
            days_since_fir=0,
            has_cctv=False,
            evidence_chain_broken=False,
            witness_last_contact_days=None,
        )
        score = self.predictor.predict_proba(features)
        band = self.predictor.band(score)

        # LLM narrative
        messages = build_risk_prompt(
            case_id=request.case_id,
            case_facts=request.case_facts,
            lapses=request.lapses,
            evidence_strength=request.evidence_strength,
            witness_count=request.witness_count,
            hostile_witness_count=request.hostile_witness_count,
            fsl_status=request.fsl_status,
            bnss_173_compliant=request.bnss_173_compliant,
            language=request.language,
        )
        response = self.llm.complete(messages, temperature=0.1, max_tokens=1024)
        log.info("ai.risk_score", case_id=request.case_id, score=score, band=band)

        return RiskScoreResponse(
            case_id=request.case_id,
            score=score,
            band=band,
            narrative=response.content,
            contributing_factors=self.predictor.top_factors(features),
            model=response.model,
        )
