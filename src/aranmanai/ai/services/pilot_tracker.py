"""Pilot tracker service.

Tracks the 20-30 case conviction-rate pilot. The pilot is the make-or-break
measurement for Aranmanai v1: did the system move conviction rate?

Measurement protocol:
1. Enroll a case: record baseline p_conviction + lapse counts (before cures)
2. Apply cures: record each Aranmanai intervention
3. Mid-review: record post-p_conviction after first hearing cycle
4. Close: record actual case outcome (convicted/acquitted/compromised/pending)

Measured delta:
- Δp = post_p_conviction - baseline_p_conviction
- Δhostile = post_hostile_witnesses - baseline_hostile_witnesses
- Aggregate conviction rate change across all pilot cases

Per Kishore Kommi's evidence (156% increase, Eluru 2023-24):
- 51 convictions in 41 cases → 132/41 with CMC coordination loop
- Aranmanai aims to replicate this via AI + operational coordination
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case
from aranmanai.db.models.coordination import PilotCase
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class PilotMetrics:
    """Aggregated pilot measurement results."""
    n_enrolled: int
    n_closed: int
    n_pending: int
    n_convicted: int
    n_acquitted: int
    n_compromised: int
    conviction_rate: float | None   # closed cases only
    conviction_rate_baseline: float | None
    delta_conviction_rate: float | None
    delta_p_conviction_avg: float | None  # avg Δp across all enrolled
    hostile_reduction_avg: float | None  # avg reduction in hostile witnesses
    cases: list[dict[str, Any]]


class PilotTrackerService:
    """Enroll, track, and measure pilot cases."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def enroll(
        self,
        case_id: str,
        district: str,
        enrolled_by: str,
        baseline_p_conviction: float | None = None,
        baseline_offence: str | None = None,
        baseline_court: str | None = None,
        baseline_lapse_count: int | None = None,
        baseline_fatal_lapse_count: int | None = None,
        notes: str | None = None,
    ) -> PilotCase:
        """Enroll a case in the pilot. One case = one pilot row."""
        existing = self.db.query(PilotCase).filter(PilotCase.case_id == case_id).first()
        if existing:
            raise ValueError(f"Case {case_id} is already enrolled in the pilot")

        case = self.db.get(Case, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")

        pc = PilotCase(
            id=str(uuid.uuid4()),
            case_id=case_id,
            district=district,
            enrolled_by=enrolled_by,
            baseline_p_conviction=baseline_p_conviction,
            baseline_offence=baseline_offence or (case.bns_sections[0] if case.bns_sections else None),
            baseline_court=baseline_court or case.court,
            baseline_lapse_count=baseline_lapse_count,
            baseline_fatal_lapse_count=baseline_fatal_lapse_count,
            notes=notes,
        )
        self.db.add(pc)
        self.db.commit()
        self.db.refresh(pc)
        log.info("pilot.enrolled case_id=%s by=%s", case_id, enrolled_by)
        return pc

    def apply_cure(self, pilot_case_id: str, lapse_key: str, cure_action: str) -> PilotCase:
        """Record an Aranmanai cure applied to a pilot case."""
        pc = self.db.get(PilotCase, pilot_case_id)
        if not pc:
            raise ValueError(f"Pilot case {pilot_case_id} not found")

        cure = {
            "lapse_key": lapse_key,
            "cure_action": cure_action,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        pc.cures_applied = (pc.cures_applied or []) + [cure]
        self.db.commit()
        self.db.refresh(pc)
        log.info("pilot.cure case_id=%s cure=%s action=%s", pc.case_id, lapse_key, cure_action)
        return pc

    def mid_review(
        self,
        pilot_case_id: str,
        post_p_conviction: float | None = None,
        post_lapse_count: int | None = None,
        post_fatal_lapse_count: int | None = None,
        post_hostile_witnesses: int | None = None,
        notes: str | None = None,
    ) -> PilotCase:
        """Record mid-pilot review (after at least one hearing cycle)."""
        pc = self.db.get(PilotCase, pilot_case_id)
        if not pc:
            raise ValueError(f"Pilot case {pilot_case_id} not found")

        if post_p_conviction is not None:
            pc.post_p_conviction = post_p_conviction
        if post_lapse_count is not None:
            pc.post_lapse_count = post_lapse_count
        if post_fatal_lapse_count is not None:
            pc.post_fatal_lapse_count = post_fatal_lapse_count
        if post_hostile_witnesses is not None:
            pc.post_hostile_witnesses = post_hostile_witnesses
        if notes:
            pc.notes = (pc.notes or "") + f"\n[mid-review] {notes}"
        pc.mid_review_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(pc)
        log.info("pilot.mid_review case_id=%s post_p=%.2f", pc.case_id, post_p_conviction)
        return pc

    def close_case(
        self,
        pilot_case_id: str,
        outcome: str,  # convicted | acquitted | compromised | pending
        outcome_date: datetime | None = None,
        sentence: str | None = None,
        notes: str | None = None,
    ) -> PilotCase:
        """Close a pilot case with the final outcome."""
        pc = self.db.get(PilotCase, pilot_case_id)
        if not pc:
            raise ValueError(f"Pilot case {pilot_case_id} not found")

        pc.outcome = outcome
        pc.outcome_date = outcome_date or datetime.now(timezone.utc)
        pc.sentence = sentence
        if notes:
            pc.notes = (pc.notes or "") + f"\n[close] {notes}"
        pc.closed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(pc)
        log.info("pilot.close case_id=%s outcome=%s", pc.case_id, outcome)
        return pc

    def get_metrics(self, district: str | None = None) -> PilotMetrics:
        """Compute aggregate pilot metrics."""
        q = self.db.query(PilotCase)
        if district:
            q = q.filter(PilotCase.district == district)

        cases = q.all()
        n = len(cases)

        closed = [c for c in cases if c.outcome in ("convicted", "acquitted", "compromised")]
        pending = [c for c in cases if c.outcome == "pending" or c.outcome is None]

        n_closed = len(closed)
        n_convicted = sum(1 for c in closed if c.outcome == "convicted")
        n_acquitted = sum(1 for c in closed if c.outcome == "acquitted")
        n_compromised = sum(1 for c in closed if c.outcome == "compromised")

        conviction_rate = n_convicted / n_closed if n_closed > 0 else None

        # Baseline conviction rate (proxy: if we had no Aranmanai)
        baseline_rates = [c.baseline_p_conviction for c in cases if c.baseline_p_conviction is not None]
        conviction_rate_baseline = sum(baseline_rates) / len(baseline_rates) if baseline_rates else None

        delta_conviction = (
            (conviction_rate - conviction_rate_baseline)
            if conviction_rate is not None and conviction_rate_baseline is not None
            else None
        )

        # Avg Δp conviction
        delta_ps = []
        for c in cases:
            if c.baseline_p_conviction is not None and c.post_p_conviction is not None:
                delta_ps.append(c.post_p_conviction - c.baseline_p_conviction)
        delta_p_avg = sum(delta_ps) / len(delta_ps) if delta_ps else None

        # Avg hostile witness reduction
        hostile_reductions = []
        for c in cases:
            if c.baseline_lapse_count is not None and c.post_lapse_count is not None:
                hostile_reductions.append(c.baseline_lapse_count - c.post_lapse_count)
        hostile_avg = sum(hostile_reductions) / len(hostile_reductions) if hostile_reductions else None

        return PilotMetrics(
            n_enrolled=n,
            n_closed=n_closed,
            n_pending=len(pending),
            n_convicted=n_convicted,
            n_acquitted=n_acquitted,
            n_compromised=n_compromised,
            conviction_rate=conviction_rate,
            conviction_rate_baseline=conviction_rate_baseline,
            delta_conviction_rate=delta_conviction,
            delta_p_conviction_avg=delta_p_avg,
            hostile_reduction_avg=hostile_avg,
            cases=[
                {
                    "id": c.id,
                    "case_id": c.case_id,
                    "enrolled_at": c.enrolled_at.isoformat() if c.enrolled_at else None,
                    "outcome": c.outcome,
                    "outcome_date": c.outcome_date.isoformat() if c.outcome_date else None,
                    "sentence": c.sentence,
                    "baseline_p_conviction": c.baseline_p_conviction,
                    "post_p_conviction": c.post_p_conviction,
                    "delta_p": (
                        (c.post_p_conviction - c.baseline_p_conviction)
                        if c.baseline_p_conviction is not None and c.post_p_conviction is not None
                        else None
                    ),
                    "cures_applied": c.cures_applied or [],
                    "n_cures": len(c.cures_applied or []),
                }
                for c in cases
            ],
        )
