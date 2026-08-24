"""Per-case timeline. Visual progress from FIR to judgment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case
from aranmanai.db.models.hearing import Hearing
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class TimelineEvent:
    date: datetime
    event_type: str  # "fir", "hearing", "witness_added", "evidence_added", "judgment", etc.
    label: str
    case_id: str


class TimelineService:
    """Build a chronological timeline for a single case."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build(self, case_id: str) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []
        case = self.db.get(Case, case_id)
        if not case:
            return events

        # FIR
        if case.fir_date:
            events.append(TimelineEvent(
                date=case.fir_date,
                event_type="fir",
                label=f"FIR registered: {case.fir_no}",
                case_id=case_id,
            ))

        # Hearings
        hearings = self.db.execute(
            select(Hearing).where(Hearing.case_id == case_id).order_by(Hearing.date)
        ).scalars().all()
        for h in hearings:
            label = f"Hearing: {h.docket_label or h.stage}"
            if h.outcome:
                label += f" → {h.outcome}"
            events.append(TimelineEvent(date=h.date, event_type="hearing", label=label, case_id=case_id))

        # Judgment
        if case.judgment_date:
            events.append(TimelineEvent(
                date=case.judgment_date,
                event_type="judgment",
                label=f"Judgment: {case.status.value}",
                case_id=case_id,
            ))

        events.sort(key=lambda e: e.date)
        log.info("cms.timeline.build", case_id=case_id, events=len(events))
        return events
