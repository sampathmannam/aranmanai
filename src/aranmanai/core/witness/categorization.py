"""Witness categorization. Dheeraj's pattern: Supportive / Neutral / Hostile.

Each category drives different prep:
- Supportive: standard prep, focus on cross-exam tactics
- Neutral: prep + escort, may flip
- Hostile: aggressive prep, re-record 161 statement, witness protection
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case
from aranmanai.db.models.witness import Witness, WitnessCategory
from aranmanai.observability import get_logger

log = get_logger(__name__)


class WitnessCategorizationService:
    """Per-witness categorization + per-case aggregation."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def categorize(self, witness_id: str, category: WitnessCategory, reason: str | None = None) -> Witness:
        """Update a witness's category. Logs hostile reason for audit."""
        witness = self.db.get(Witness, witness_id)
        if not witness:
            raise ValueError(f"Witness not found: {witness_id}")
        old_category = witness.category
        witness.category = category
        if category == WitnessCategory.HOSTILE:
            witness.hostile_reason = reason
            witness.hostile_since = datetime.utcnow()
        else:
            witness.hostile_reason = None
            witness.hostile_since = None
        self.db.commit()
        log.info(
            "witness.categorize",
            witness_id=witness_id[:8],
            case_id=witness.case_id[:8],
            old=old_category.value,
            new=category.value,
        )
        return witness

    def bulk_categorize(self, witness_ids: Iterable[str], category: WitnessCategory) -> int:
        """Bulk categorize. Returns count updated."""
        count = 0
        for wid in witness_ids:
            try:
                self.categorize(wid, category)
                count += 1
            except ValueError:
                continue
        return count

    def case_witness_breakdown(self, case_id: str) -> dict[str, int]:
        """Per-case witness breakdown by category."""
        witnesses = self.db.execute(
            select(Witness).where(Witness.case_id == case_id)
        ).scalars().all()
        breakdown: dict[str, int] = {c.value: 0 for c in WitnessCategory}
        for w in witnesses:
            breakdown[w.category.value] = breakdown.get(w.category.value, 0) + 1
        return breakdown

    def district_hostile_needing_prep(self, district: str) -> list[Witness]:
        """Hostile witnesses in the district that haven't been prepped yet."""
        rows = self.db.execute(
            select(Witness)
            .join(Case, Witness.case_id == Case.id)
            .where(Case.district == district)
            .where(Witness.category == WitnessCategory.HOSTILE)
            .where(Witness.prep_status.not_in(["ready", "testified"]))
        ).scalars().all()
        return list(rows)
