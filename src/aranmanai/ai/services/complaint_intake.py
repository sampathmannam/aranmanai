"""Complaint intake service. Raw voice/text → structured complaint record."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.complaint_intake import build_complaint_intake_prompt
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, hash_password  # noqa: F401

log = get_logger(__name__)


class ComplaintIntakeRequest(BaseModel):
    raw_complaint: str = Field(..., min_length=1, max_length=20_000)
    complainant_name: str | None = None
    complainant_contact: str | None = None
    language: str = "en"


class ComplaintIntakeResponse(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    structured: str
    likely_sections_bns: list[str] = Field(default_factory=list)
    registerable: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ComplaintIntakeService:
    """Convert raw complaint text/voice into a structured complaint."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def intake(self, request: ComplaintIntakeRequest) -> ComplaintIntakeResponse:
        messages = build_complaint_intake_prompt(
            raw_complaint=request.raw_complaint,
            complainant_name=request.complainant_name,
            complainant_contact=request.complainant_contact,
            language=request.language,
        )
        response = self.llm.complete(messages, temperature=0.1, max_tokens=2048)
        log.info(
            "ai.complaint_intake",
            tokens_in=response.prompt_tokens,
            tokens_out=response.completion_tokens,
            language=request.language,
        )
        # Light heuristic: look for likely BNS sections in the response
        likely_sections: list[str] = []
        for marker in ("BNS 103", "BNS 63", "BNS 303", "BNS 305", "BNS 115", "BNS 117", "BNS 351"):
            if marker in response.content:
                likely_sections.append(marker.replace("BNS ", ""))
        registerable = "FIR registerable: True" in response.content or "register FIR" in response.content.lower()
        return ComplaintIntakeResponse(
            structured=response.content,
            likely_sections_bns=likely_sections,
            registerable=registerable,
        )
