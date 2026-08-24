"""Witness preparation service. Manages the prep workflow around the AI brief."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from aranmanai.ai.services.cross_exam_prep import (
    CrossExamPrepRequest,
    CrossExamPrepService,
)
from aranmanai.db.models.witness import Witness, WitnessPrepStatus
from aranmanai.observability import get_logger

log = get_logger(__name__)


class WitnessPreparationService:
    """Coordinate witness prep: AI brief → IO/PP review → witness meeting → ready."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.ai_service = CrossExamPrepService()

    def generate_brief(
        self,
        witness_id: str,
        case_facts: str,
        language: str = "en",
    ) -> dict[str, Any]:
        """Generate the cross-exam prep brief. Stores it on the witness."""
        witness = self.db.get(Witness, witness_id)
        if not witness:
            raise ValueError(f"Witness not found: {witness_id}")
        # Decrypt name + statement for the prompt (server-side; never logged)
        from aranmanai.security import decrypt_field
        witness_name = decrypt_field(witness.name_encrypted)
        statement = decrypt_field(witness.statement_text_encrypted) or "(no 161 statement on file)"

        response = self.ai_service.prepare(
            CrossExamPrepRequest(
                case_id=witness.case_id,
                witness_id=witness_id,
                witness_type=witness.type.value,
                witness_category=witness.category.value,
                witness_statement=statement,
                case_facts=case_facts,
                hostile_reason=witness.hostile_reason,
                language=language,
            )
        )
        # Store the brief + history (audit trail)
        qns = self._parse_questions(response.brief)
        witness.cross_exam_questions = qns
        witness.cross_exam_at = datetime.utcnow()
        witness.prep_status = WitnessPrepStatus.PREPPED
        history = list(witness.prep_history or [])
        history.append({
            "prep_id": response.prep_id,
            "at": witness.cross_exam_at.isoformat(),
            "model": response.model,
            "language": language,
        })
        witness.prep_history = history
        self.db.commit()
        log.info(
            "witness.prep_brief_generated",
            witness_id=witness_id[:8],
            case_id=witness.case_id[:8],
            prep_id=response.prep_id,
        )
        return {
            "prep_id": response.prep_id,
            "brief": response.brief,
            "questions": qns,
            "model": response.model,
        }

    def mark_ready(self, witness_id: str, io_approved: bool = True) -> Witness:
        witness = self.db.get(Witness, witness_id)
        if not witness:
            raise ValueError(f"Witness not found: {witness_id}")
        if io_approved:
            witness.prep_status = WitnessPrepStatus.READY
        else:
            witness.prep_status = WitnessPrepStatus.UNTOUCHED
        self.db.commit()
        return witness

    def mark_testified(self, witness_id: str, performance_notes: str | None = None) -> Witness:
        witness = self.db.get(Witness, witness_id)
        if not witness:
            raise ValueError(f"Witness not found: {witness_id}")
        witness.prep_status = WitnessPrepStatus.TESTIFIED
        witness.hearings_attended = (witness.hearings_attended or 0) + 1
        witness.last_attended = datetime.utcnow()
        if performance_notes:
            history = list(witness.prep_history or [])
            history.append({
                "at": witness.last_attended.isoformat(),
                "type": "testified",
                "notes": performance_notes,
            })
            witness.prep_history = history
        self.db.commit()
        return witness

    def _parse_questions(self, brief: str) -> list[dict[str, str]]:
        """Naive parser: pull out numbered Q/A pairs from the brief."""
        import re
        pairs: list[dict[str, str]] = []
        # Match "1. Q: ... A: ..." blocks
        pattern = re.compile(r"(\d+)\.\s*Q:\s*(.+?)\n\s*A:\s*(.+?)(?=\n\s*\d+\.|\Z)", re.DOTALL)
        for m in pattern.finditer(brief):
            pairs.append({"q": m.group(2).strip(), "a": m.group(3).strip()})
        if not pairs:
            # Fallback: just return the whole brief
            return [{"q": "(parse-failed)", "a": brief[:1000]}]
        return pairs
