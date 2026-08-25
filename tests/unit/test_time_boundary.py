"""Unit tests proving correct local (IST) calendar-day bucketing across the
UTC/IST boundary, for `local_day_utc_range` (core/time_utils.py) and its
consumer `DailyCalendarService.for_date()` (core/cms/daily_calendar.py).

Regression coverage for the bug where `for_date()` combined the target
LOCAL date with naive midnight (`datetime.combine(target_date,
datetime.min.time())`) and compared it directly against `Hearing.date`
(stored as naive UTC) -- misclassifying up to ~5.5h of every day, since
IST is UTC+5:30.
"""
from __future__ import annotations

from datetime import date, datetime


def test_local_day_utc_range_ist_offset():
    """Pure function check: the IST calendar day 2026-08-26 spans naive-UTC
    [2026-08-25 18:30, 2026-08-26 18:30) -- IST midnight on the 26th is
    18:30 UTC on the 25th, since IST is UTC+5:30.
    """
    from aranmanai.core.time_utils import local_day_utc_range
    start, end = local_day_utc_range(date(2026, 8, 26))
    assert start == datetime(2026, 8, 25, 18, 30)
    assert end == datetime(2026, 8, 26, 18, 30)


def test_hearing_early_ist_morning_bucketed_into_same_local_day(db_session, test_user):
    """A hearing stored at 2026-08-26 02:00:00 UTC is 2026-08-26 07:30 IST
    -- it must appear on local Aug 26's calendar (and only Aug 26's).
    """
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    case = Case(fir_no="930/2026", district="test-district", io_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    h = Hearing(case_id=case.id, date=datetime(2026, 8, 26, 2, 0, 0), stage="hearing")
    db_session.add(h)
    db_session.commit()

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)

    entries_26 = svc.for_date(date(2026, 8, 26), district="test-district")
    assert len(entries_26) == 1
    assert entries_26[0].fir_no == "930/2026"

    entries_25 = svc.for_date(date(2026, 8, 25), district="test-district")
    assert entries_25 == []


def test_hearing_before_utc_midnight_bucketed_into_next_local_day(db_session, test_user):
    """The tricky case: a hearing stored at 2026-08-25 20:00:00 UTC is
    2026-08-26 01:30 IST -- it belongs to local Aug 26's calendar, NOT
    Aug 25's, even though its naive-UTC calendar date reads as the 25th.
    The old code (datetime.combine(target_date, midnight), no timezone
    conversion) would have bucketed this into the 25th instead.
    """
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    case = Case(fir_no="940/2026", district="test-district", io_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    h = Hearing(case_id=case.id, date=datetime(2026, 8, 25, 20, 0, 0), stage="hearing")
    db_session.add(h)
    db_session.commit()

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)

    entries_26 = svc.for_date(date(2026, 8, 26), district="test-district")
    assert len(entries_26) == 1
    assert entries_26[0].fir_no == "940/2026"

    entries_25 = svc.for_date(date(2026, 8, 25), district="test-district")
    assert entries_25 == []
