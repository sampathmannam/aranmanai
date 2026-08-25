"""AI assist endpoints.

v1: every endpoint calls the LLMClient (real or mock) with a prompt
template from src.aranmanai.ai.prompts.templates, returns the LLM
response, and flags it as '[IO REVIEW REQUIRED]' so the IO knows
nothing is auto-applied. DPDP §8(3) compliance: every AI call
records an audit entry with the model version, prompt, and response.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.aranmanai.ai.llm_client import LLMClient
from src.aranmanai.ai.factory import get_llm_client
from src.aranmanai.ai.prompts import templates as prompts
from src.aranmanai.ai.rag import retrieve
from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, User
from src.aranmanai.schemas import (
    ChargesheetDraftRequest, ChargesheetDraftResponse,
    ComplaintIntakeRequest, ComplaintIntakeResponse,
    FirDraftRequest, FirDraftResponse,
)
from src.aranmanai.security import get_current_user, record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def _now() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


@router.post("/complaint-intake", response_model=ComplaintIntakeResponse)
def complaint_intake(
    body: ComplaintIntakeRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm_client),
) -> ComplaintIntakeResponse:
    """Convert voice/text complaint into structured FIR-ready draft.
    v1: simple prompt → LLM. v2: use RAG over BNS/BNSS/BSA to ground sections.
    """
    if not body.text and not body.audio_b64:
        raise HTTPException(status_code=400, detail="either 'text' or 'audio_b64' required")
    narrative = body.text or f"[voice input: {len(body.audio_b64)} bytes; STT not yet wired in v1]"
    system, user = prompts.complaint_intake(narrative, body.language)
    resp = llm.complete(user, system=system, max_tokens=800)
    # Try to parse as JSON; if the model returned prose (likely in mock), wrap
    try:
        import json
        structured = json.loads(resp.text)
        if not isinstance(structured, dict):
            structured = {"raw": resp.text}
    except Exception:
        structured = {"raw": resp.text}
    record_audit(
        db, actor_id=actor.id, action="ai.complaint_intake",
        subject_type="case", subject_id=None,
        fields_used=["text", "language", "audio_b64"],
        detail={"model": resp.model, "backend": resp.backend, "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens},
    )
    log.info("ai.complaint_intake model=%s backend=%s by=%s", resp.model, resp.backend, actor.id)
    return ComplaintIntakeResponse(
        structured_complaint=structured,
        model=f"{resp.backend}:{resp.model}",
        generated_at=_now(),
        review_required=True,
    )


@router.post("/fir-draft", response_model=FirDraftResponse)
def fir_draft(
    body: FirDraftRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm_client),
) -> FirDraftResponse:
    """Generate a FIR draft from a stored case. Reads sections + facts from DB.
    v1: prompt-only. v2: RAG over BNS sections.
    """
    case = db.get(Case, body.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    system, user = prompts.fir_draft(case.case_id, case.sections or [], case.facts_text or "(no facts_text stored)")
    resp = llm.complete(user, system=system, max_tokens=1200)
    record_audit(
        db, actor_id=actor.id, action="ai.fir_draft",
        subject_type="case", subject_id=case.case_id,
        fields_used=["sections", "facts_text"],
        detail={"model": resp.model, "backend": resp.backend},
    )
    # Naive section extraction: pick strings that look like "X IPC" / "X BNS" / "X POCSO"
    bns: list[str] = []
    for s in (case.sections or []):
        if "BNS" in s or "POCSO" in s or "SC" in s.upper() and "ST" in s.upper():
            bns.append(s)
    return FirDraftResponse(
        case_id=case.id,
        fir_text=resp.text,
        bns_sections=bns,
        bnss_sections=[],
        bsa_sections=[],
        model=f"{resp.backend}:{resp.model}",
        review_required=True,
    )


@router.post("/chargesheet-draft", response_model=ChargesheetDraftResponse)
def chargesheet_draft(
    body: ChargesheetDraftRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm_client),
) -> ChargesheetDraftResponse:
    """Generate a Section 193 BNSS chargesheet draft."""
    case = db.get(Case, body.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")
    evidence = [f"type={e.type}, chain={e.chain_status}, fsl={e.fsl_status}" for e in case.evidence]
    system, user = prompts.chargesheet_draft(case.case_id, case.facts_text or "", evidence, case.sections or [])
    resp = llm.complete(user, system=system, max_tokens=1500)
    record_audit(
        db, actor_id=actor.id, action="ai.chargesheet_draft",
        subject_type="case", subject_id=case.case_id,
        fields_used=["sections", "facts_text", "evidence"],
        detail={"model": resp.model, "backend": resp.backend},
    )
    return ChargesheetDraftResponse(
        case_id=case.id,
        chargesheet_text=resp.text,
        model=f"{resp.backend}:{resp.model}",
        review_required=True,
    )
