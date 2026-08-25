"""Daily case calendar. Dheeraj's pattern: today's hearings + this week + this month."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from aranmanai.core.time_utils import local_day_utc_range
from aranmanai.db.models.case import Case, CaseStatus
from aranmanai.db.models.hearing import Hearing
from aranmanai.db.models.witness import WitnessCategory
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class DailyCalendarEntry:
    case_id: str
    fir_no: str
    case_stage: str
    hearing_id: str
    hearing_date: datetime
    docket_label: str | None
    judge: str | None
    # Witness breakdown
    total_witnesses: int
    hostile_witnesses: int
    prepared_witnesses: int
    # Attendance
    pp_confirmed: bool | None
    defense_confirmed: bool | None
    accused_confirmed: bool | None
    # Risk + priority
    risk_score: float | None
    priority: str  # "critical" / "high" / "normal" / "low"


class DailyCalendarService:
    """Generate the daily case calendar for a given date."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def for_date(self, target_date: date, district: str | None = None) -> list[DailyCalendarEntry]:
        """All hearings on target_date (an India Standard Time calendar day),
        sorted by priority (critical first).

        Hearing.date is stored as naive UTC. `local_day_utc_range` converts
        the IST calendar day into the equivalent naive-UTC instant range so
        hearings in the ~5.5h IST/UTC offset window are bucketed into the
        correct local day (see core/time_utils.py).
        """
        start, end = local_day_utc_range(target_date)
        stmt = (
            select(Hearing, Case)
            .join(Case, Hearing.case_id == Case.id)
            .where(and_(Hearing.date >= start, Hearing.date < end))
            .where(Case.status.not_in([CaseStatus.CLOSED_ACQUITTED, CaseStatus.CLOSED_CONVICTED,
                                       CaseStatus.CLOSED_COMPROMISED, CaseStatus.CLOSED_WITHDRAWN]))
        )
        if district:
            stmt = stmt.where(Case.district == district)
        rows = self.db.execute(stmt).all()
        entries: list[DailyCalendarEntry] = []
        for hearing, case in rows:
            entry = self._build_entry(hearing, case)
            entries.append(entry)
        # Sort: critical > high > normal > low, then by FIR no
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        entries.sort(key=lambda e: (priority_order.get(e.priority, 99), e.fir_no))
        log.info("cms.calendar.for_date", date=target_date.isoformat(), count=len(entries))
        return entries

    def for_week(self, start_date: date, district: str | None = None) -> dict[date, list[DailyCalendarEntry]]:
        """7-day calendar starting at start_date."""
        out: dict[date, list[DailyCalendarEntry]] = {}
        for i in range(7):
            d = start_date + timedelta(days=i)
            out[d] = self.for_date(d, district=district)
        return out

    def _build_entry(self, hearing: Hearing, case: Case) -> DailyCalendarEntry:
        witnesses = list(case.witnesses) if case.witnesses else []
        total_w = len(witnesses)
        hostile_w = sum(1 for w in witnesses if w.category == WitnessCategory.HOSTILE)
        prepared_w = sum(1 for w in witnesses if w.prep_status.value in ("ready", "testified"))

        # Priority heuristic: critical if hostile > 0 AND prepared < hostile
        # OR risk_score is high
        risk = case.risk_score
        if risk is not None and risk >= 0.7 or hostile_w > 0 and prepared_w < hostile_w:
            priority = "critical"
        elif risk is not None and risk >= 0.5 or hostile_w > 0:
            priority = "high"
        elif hearing.outcome is None:
            priority = "normal"
        else:
            priority = "low"

        return DailyCalendarEntry(
            case_id=case.id,
            fir_no=case.fir_no,
            case_stage=case.stage.value,
            hearing_id=hearing.id,
            hearing_date=hearing.date,
            docket_label=hearing.docket_label,
            judge=case.judge,
            total_witnesses=total_w,
            hostile_witnesses=hostile_w,
            prepared_witnesses=prepared_w,
            pp_confirmed=hearing.pp_present,
            defense_confirmed=hearing.defense_present,
            accused_confirmed=hearing.accused_present,
            risk_score=risk,
            priority=priority,
        )
