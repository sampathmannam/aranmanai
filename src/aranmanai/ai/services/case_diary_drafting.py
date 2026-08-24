"""Case diary drafting service. Section 174 BNSS (renumbered from CrPC §172)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.case_diary import build_case_diary_prompt
from aranmanai.observability import get_logger

log = get_logger(__name__)


class CaseDiaryRequest(BaseModel):
    case_id: str
    fir_no: str
    io_name: str
    date: str
    progress_notes: str
    investigation_steps: str
    language: str = "en"


class CaseDiaryResponse(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    diary_entry: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str
    io_approved: bool = False


class CaseDiaryDraftingService:
    """Draft a Section 174 BNSS case diary entry."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def draft(self, request: CaseDiaryRequest) -> CaseDiaryResponse:
        messages = build_case_diary_prompt(
            case_id=request.case_id,
            fir_no=request.fir_no,
            io_name=request.io_name,
            date=request.date,
            progress_notes=request.progress_notes,
            investigation_steps=request.investigation_steps,
            language=request.language,
        )
        response = self.llm.complete(messages, temperature=0.1, max_tokens=2048)
        log.info("ai.case_diary_draft", case_id=request.case_id)
        return CaseDiaryResponse(diary_entry=response.content, model=response.model)
