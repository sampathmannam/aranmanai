"""FIR drafting service. Voice/text complaint → formal FIR draft."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.fir import build_fir_prompt
from aranmanai.observability import Timer, get_logger

log = get_logger(__name__)


class FirDraftRequest(BaseModel):
    complainant_name: str
    complainant_contact: str
    incident_time: str
    location: str
    facts: str = Field(..., min_length=10, max_length=20_000)
    sections_bns: list[str] = Field(default_factory=list)
    sections_bnss: list[str] = Field(default_factory=list)
    police_station: str
    district: str
    io_name: str
    language: str = "en"


class FirDraftResponse(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fir_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str
    # Approval flag — every AI output must be approved by IO before persistence
    io_approved: bool = False
    # Real wall-clock seconds spent in the AI-generation call (LLM.complete
    # only — excludes request parsing / DB / audit I/O). Feeds the Month-3
    # drafting-time-reduction milestone measurement.
    elapsed_seconds: float = 0.0


class FirDraftingService:
    """Draft a formal FIR per BNSS §154."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def draft(self, request: FirDraftRequest) -> FirDraftResponse:
        messages = build_fir_prompt(
            complainant_name=request.complainant_name,
            complainant_contact=request.complainant_contact,
            incident_time=request.incident_time,
            location=request.location,
            facts=request.facts,
            sections_bns=request.sections_bns,
            sections_bnss=request.sections_bnss,
            police_station=request.police_station,
            district=request.district,
            io_name=request.io_name,
            language=request.language,
        )
        with Timer() as t:
            response = self.llm.complete(messages, temperature=0.1, max_tokens=2048)
        log.info(
            "ai.fir_draft",
            tokens_in=response.prompt_tokens,
            tokens_out=response.completion_tokens,
            ps=request.police_station,
            elapsed_seconds=t.elapsed_seconds,
        )
        return FirDraftResponse(
            fir_text=response.content,
            model=response.model,
            elapsed_seconds=t.elapsed_seconds or 0.0,
        )
