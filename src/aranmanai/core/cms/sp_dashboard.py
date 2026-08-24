"""SP daily review dashboard. Kishore's accountability loop.

The dashboard surfaces:
- Today's hearings (sorted by priority)
- Cases at risk (bottlenecks)
- Witnesses to contact before next hearing
- Conviction rate trend
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import case as sql_case, func, select
from sqlalchemy.orm import Session

from aranmanai.core.cms.bottleneck import BottleneckDetector
from aranmanai.core.cms.daily_calendar import DailyCalendarService
from aranmanai.db.models.case import Case, CaseStatus
from aranmanai.db.models.hearing import Hearing
from aranmanai.db.models.witness import Witness, WitnessCategory
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class SpDashboardSnapshot:
    as_of: datetime
    district: str
    today_hearings: int
    critical_hearings: int
    hostile_witnesses_needing_prep: int
    cases_stuck: int
    cases_stuck_critical: int
    conviction_rate_30d: float | None
    conviction_rate_baseline: float | None
    trend_delta: float | None
    top_actions: list[str] = field(default_factory=list)


class SpDashboardService:
    """Build the SP daily review dashboard."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.calendar = DailyCalendarService(db)
        self.bottleneck = BottleneckDetector(db)

    def snapshot(self, district: str, as_of: date | None = None) -> SpDashboardSnapshot:
        as_of = as_of or date.today()
        now = datetime.utcnow()

        calendar = self.calendar.for_date(as_of, district=district)
        bottlenecks = self.bottleneck.detect(district=district)

        # Hostile witnesses in the district that still need prep
        hostile_untouched = self.db.execute(
            select(func.count(Witness.id))
            .join(Case, Witness.case_id == Case.id)
            .where(Case.district == district)
            .where(Witness.category == WitnessCategory.HOSTILE)
            .where(Witness.prep_status.not_in(["ready", "testified"]))
        ).scalar() or 0

        # Conviction rate trend (last 30 days)
        rate_30d = self._conviction_rate_last_days(district, days=30)
        rate_baseline = self._conviction_rate_last_days(district, days=180)
        trend = (rate_30d - rate_baseline) if (rate_30d is not None and rate_baseline is not None) else None

        top_actions: list[str] = []
        for h in calendar:
            if h.priority == "critical":
                top_actions.append(f"URGENT: hearing {h.fir_no} today, {h.hostile_witnesses} hostile witnesses, {h.prepared_witnesses} prepared")
        for b in bottlenecks[:3]:
            if b.severity in ("critical", "alarm"):
                top_actions.append(f"STUCK {b.days_in_stage}d: {b.fir_no} at {b.case_stage} — {b.suggested_action}")

        snap = SpDashboardSnapshot(
            as_of=now,
            district=district,
            today_hearings=len(calendar),
            critical_hearings=sum(1 for h in calendar if h.priority == "critical"),
            hostile_witnesses_needing_prep=hostile_untouched,
            cases_stuck=len(bottlenecks),
            cases_stuck_critical=sum(1 for b in bottlenecks if b.severity in ("critical", "alarm")),
            conviction_rate_30d=rate_30d,
            conviction_rate_baseline=rate_baseline,
            trend_delta=trend,
            top_actions=top_actions[:10],
        )
        log.info("cms.sp_dashboard.snapshot", district=district, today=as_of.isoformat())
        return snap

    def _conviction_rate_last_days(self, district: str, days: int) -> float | None:
        """Convictions / (convictions + acquittals) in the last `days` days."""
        since = datetime.utcnow() - timedelta(days=days)
        row = self.db.execute(
            select(
                func.sum(sql_case((Case.status == CaseStatus.CLOSED_CONVICTED, 1), else_=0)).label("conv"),
                func.sum(sql_case((Case.status == CaseStatus.CLOSED_ACQUITTED, 1), else_=0)).label("acq"),
            ).where(Case.district == district)
             .where(Case.judgment_date >= since)
        ).one()
        conv, acq = row.conv or 0, row.acq or 0
        if conv + acq == 0:
            return None
        return conv / (conv + acq)
