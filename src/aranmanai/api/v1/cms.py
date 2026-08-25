"""Court Monitoring System routes: calendar, timeline, bottlenecks, SP dashboard."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from aranmanai.api.deps import CurrentUser, DbSession, SpUser
from aranmanai.core.cms.bottleneck import BottleneckDetector
from aranmanai.core.cms.daily_calendar import DailyCalendarService
from aranmanai.core.cms.sp_dashboard import SpDashboardService
from aranmanai.core.cms.timeline import TimelineService
from aranmanai.core.time_utils import local_today
from aranmanai.observability import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.get("/calendar/today")
def today_calendar(
    db: DbSession,
    user: CurrentUser,
    district: str | None = None,
) -> list[dict[str, Any]]:
    svc = DailyCalendarService(db)
    return [e.__dict__ for e in svc.for_date(local_today(), district=district)]


@router.get("/calendar/date/{target_date}")
def calendar_for_date(
    target_date: date,
    db: DbSession,
    user: CurrentUser,
    district: str | None = None,
) -> list[dict[str, Any]]:
    svc = DailyCalendarService(db)
    return [e.__dict__ for e in svc.for_date(target_date, district=district)]


@router.get("/calendar/week")
def week_calendar(
    db: DbSession,
    user: CurrentUser,
    start: date | None = None,
    district: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    start = start or local_today()
    svc = DailyCalendarService(db)
    out = svc.for_week(start, district=district)
    return {d.isoformat(): [e.__dict__ for e in entries] for d, entries in out.items()}


@router.get("/timeline/{case_id}")
def case_timeline(case_id: str, db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    svc = TimelineService(db)
    return [e.__dict__ for e in svc.build(case_id)]


@router.get("/bottlenecks")
def bottlenecks(
    db: DbSession,
    user: CurrentUser,
    district: str | None = None,
) -> list[dict[str, Any]]:
    svc = BottleneckDetector(db)
    return [b.__dict__ for b in svc.detect(district=district)]


@router.get("/sp-dashboard")
def sp_dashboard(
    db: DbSession,
    user: SpUser,
    district: str = Query(...),
) -> dict[str, Any]:
    svc = SpDashboardService(db)
    snap = svc.snapshot(district=district)
    return {
        "as_of": snap.as_of.isoformat(),
        "district": snap.district,
        "today_hearings": snap.today_hearings,
        "critical_hearings": snap.critical_hearings,
        "hostile_witnesses_needing_prep": snap.hostile_witnesses_needing_prep,
        "cases_stuck": snap.cases_stuck,
        "cases_stuck_critical": snap.cases_stuck_critical,
        "conviction_rate_30d": snap.conviction_rate_30d,
        "conviction_rate_baseline": snap.conviction_rate_baseline,
        "trend_delta": snap.trend_delta,
        "top_actions": snap.top_actions,
    }
