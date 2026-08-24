"""Chargesheet drafting service. Section 173 BNSS final report."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.chargesheet import build_chargesheet_prompt
from aranmanai.observability import get_logger

log = get_logger(__name__)


class ChargesheetRequest(BaseModel):
    case_id: str
    fir_no: str
    court: str
    accused_name: str
    accused_address: str
    arrest_date: str
    sections_bns: list[str]
    facts: str
    evidence_summary: str
    witness_summary: str
    io_name: str
    language: str = "en"


class ChargesheetResponse(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chargesheet_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str
    io_approved: bool = False


class ChargesheetDraftingService:
    """Draft a Section 173 BNSS chargesheet."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def draft(self, request: ChargesheetRequest) -> ChargesheetResponse:
        messages = build_chargesheet_prompt(
            case_id=request.case_id,
            fir_no=request.fir_no,
            court=request.court,
            accused_name=request.accused_name,
            accused_address=request.accused_address,
            arrest_date=request.arrest_date,
            sections_bns=request.sections_bns,
            facts=request.facts,
            evidence_summary=request.evidence_summary,
            witness_summary=request.witness_summary,
            io_name=request.io_name,
            language=request.language,
        )
        response = self.llm.complete(messages, temperature=0.1, max_tokens=4096)
        log.info("ai.chargesheet_draft", case_id=request.case_id)
        return ChargesheetResponse(chargesheet_text=response.content, model=response.model)
