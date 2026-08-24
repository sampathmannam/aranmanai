"""Bottleneck detector. Kishore's "intelligent alerts" pattern.

Cases stuck at a stage > threshold days are flagged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case, CaseStage
from aranmanai.db.models.hearing import Hearing
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class Bottleneck:
    case_id: str
    fir_no: str
    case_stage: str
    days_in_stage: int
    last_event: str
    last_event_date: datetime
    severity: str  # "warning" (>30d) / "critical" (>90d) / "alarm" (>180d)
    suggested_action: str


class BottleneckDetector:
    """Detect cases stuck at a procedural stage.

    Default thresholds (overridable in v2):
    - warning: 30 days
    - critical: 90 days
    - alarm: 180 days
    """

    DEFAULT_THRESHOLDS = {
        "warning": 30,
        "critical": 90,
        "alarm": 180,
    }

    def __init__(self, db: Session, thresholds: dict[str, int] | None = None) -> None:
        self.db = db
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}

    def detect(self, district: str | None = None) -> list[Bottleneck]:
        """Find all cases stuck at their current stage for too long."""
        today = datetime.utcnow()
        cases = self.db.execute(
            select(Case).where(
                Case.stage.not_in([CaseStage.CLOSED, CaseStage.JUDGMENT])
            )
        ).scalars().all()
        if district:
            cases = [c for c in cases if c.district == district]

        bottlenecks: list[Bottleneck] = []
        for case in cases:
            b = self._check_case(case, today)
            if b:
                bottlenecks.append(b)
        bottlenecks.sort(key=lambda x: -x.days_in_stage)
        log.info("cms.bottleneck.detect", count=len(bottlenecks))
        return bottlenecks

    def _check_case(self, case: Case, today: datetime) -> Bottleneck | None:
        # Find the last event for this case
        last_hearing = self.db.execute(
            select(Hearing).where(Hearing.case_id == case.id).order_by(Hearing.date.desc()).limit(1)
        ).scalar_one_or_none()
        last_event_date = last_hearing.date if last_hearing else case.fir_date
        if not last_event_date:
            return None
        days = (today - last_event_date).days
        if days < self.thresholds["warning"]:
            return None
        # Severity
        if days >= self.thresholds["alarm"]:
            severity = "alarm"
        elif days >= self.thresholds["critical"]:
            severity = "critical"
        else:
            severity = "warning"

        suggested = self._suggest(case, last_hearing, days)
        return Bottleneck(
            case_id=case.id,
            fir_no=case.fir_no,
            case_stage=case.stage.value,
            days_in_stage=days,
            last_event="hearing" if last_hearing else "FIR",
            last_event_date=last_event_date,
            severity=severity,
            suggested_action=suggested,
        )

    def _suggest(self, case: Case, last_hearing: Hearing | None, days: int) -> str:
        if not last_hearing:
            return "Investigate delays in FIR-to-charge-sheet pipeline. SP review."
        if last_hearing.adjournment_reason:
            return f"Last adjournment due to {last_hearing.adjournment_reason}. Address root cause (witness not produced, IO absent, etc.)."
        if last_hearing.next_action:
            return f"Pending: {last_hearing.next_action}. SP review with IO and PP."
        return "SP daily review: identify root cause of delay (FSL overdue, witness hostile, IO workload)."
