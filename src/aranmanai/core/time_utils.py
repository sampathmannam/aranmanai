"""Local-time helpers for day-boundary queries.

Aranmanai is a district-court operations tool for Indian police — "today"
always means the local (India Standard Time) calendar day, never the UTC
calendar day. Several services store timestamps as naive UTC
(`datetime.utcnow()`) but previously computed "today" boundaries by
combining a local `date.today()`/`date.fromisoformat()` value directly
with midnight and comparing it to those UTC columns. Since IST is UTC+5:30,
that silently misclassified up to ~5.5 hours of every day (hearings just
after local midnight were excluded from "today"; hearings in the last
~5.5 hours of UTC "today" were wrongly included as if they were the next
local day).

Use `local_today()` instead of `date.today()` when the caller actually
wants the IST calendar date. Use `local_day_utc_range()` to convert a
local calendar date into the naive-UTC `[start, end)` range to compare
against UTC-stored `DateTime` columns.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# India Standard Time: fixed UTC+5:30, no DST.
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def local_today() -> date:
    """Today's calendar date in India Standard Time."""
    return datetime.now(LOCAL_TZ).date()


def local_day_utc_range(target_date: date) -> tuple[datetime, datetime]:
    """Convert a local (IST) calendar date into a naive-UTC datetime range.

    Returns `(start, end)` such that `start <= t < end` selects every
    naive-UTC timestamp that falls within `target_date` in India Standard
    Time. Both values are naive (tzinfo stripped) so they compare directly
    against naive-UTC `DateTime` columns populated via `datetime.utcnow()`.
    """
    start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC).replace(tzinfo=None)
    return start_utc, end_utc
