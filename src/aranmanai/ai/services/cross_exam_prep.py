"""Cross-examination prep service. The "Nyaya Sahayak" layer."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.ai.prompts.cross_exam import build_cross_exam_prompt
from aranmanai.observability import Timer, get_logger

log = get_logger(__name__)


class CrossExamPrepRequest(BaseModel):
    case_id: str
    witness_id: str
    witness_type: str
    witness_category: str  # supportive / neutral / hostile
    witness_statement: str
    case_facts: str
    hostile_reason: str | None = None
    language: str = "en"


class CrossExamPrepResponse(BaseModel):
    prep_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brief: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: str
    pp_approved: bool = False
    # Real wall-clock seconds spent in the AI-generation call (LLM.complete
    # only). Feeds the Month-3 drafting-time-reduction milestone measurement.
    elapsed_seconds: float = 0.0


class CrossExamPrepService:
    """Generate cross-exam prep brief for a witness."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def prepare(self, request: CrossExamPrepRequest) -> CrossExamPrepResponse:
        messages = build_cross_exam_prompt(
            case_id=request.case_id,
            witness_id=request.witness_id,
            witness_type=request.witness_type,
            witness_category=request.witness_category,
            witness_statement=request.witness_statement,
            case_facts=request.case_facts,
            hostile_reason=request.hostile_reason,
            language=request.language,
        )
        with Timer() as t:
            response = self.llm.complete(messages, temperature=0.2, max_tokens=2048)
        log.info(
            "ai.cross_exam_prep",
            case_id=request.case_id,
            witness_id=request.witness_id,
            elapsed_seconds=t.elapsed_seconds,
        )
        return CrossExamPrepResponse(
            brief=response.content,
            model=response.model,
            elapsed_seconds=t.elapsed_seconds or 0.0,
        )
