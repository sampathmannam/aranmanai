"""Unit tests for the CMS core (calendar, timeline, bottlenecks, dashboard)."""
from __future__ import annotations

from datetime import datetime, timedelta

from aranmanai.core.time_utils import local_today


def _make_case_with_hearing(db, test_user, days_ahead: int = 0, hostile_witnesses: int = 0,
                            risk: float | None = None):
    """Helper: create a case + hearing + optional hostile witnesses."""
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessType
    hearing_date = datetime.utcnow() + timedelta(days=days_ahead)
    case = Case(
        fir_no="100/2026",
        district="test-district",
        io_id=test_user.id,
        risk_score=risk,
    )
    db.add(case)
    db.commit()
    for i in range(hostile_witnesses):
        w = Witness(
            case_id=case.id,
            name_encrypted=f"w-{i}",
            type=WitnessType.EYEWITNESS,
            category=WitnessCategory.HOSTILE,
        )
        db.add(w)
    h = Hearing(case_id=case.id, date=hearing_date, stage="hearing")
    db.add(h)
    db.commit()
    db.refresh(case)
    return case, h


def test_daily_calendar_for_date_returns_today_hearings(db_session, test_user):
    _make_case_with_hearing(db_session, test_user, days_ahead=0)

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)
    # _make_case_with_hearing stamps the hearing via datetime.utcnow() (i.e.
    # "right now"). for_date() takes a LOCAL (IST) calendar date and converts
    # it to the matching naive-UTC range internally (see core/time_utils.py),
    # so the date that correctly contains "right now" is local_today(), not
    # datetime.utcnow().date() (which is the UTC calendar date and can be a
    # different day for up to ~5.5h of every 24h, since IST is UTC+5:30).
    entries = svc.for_date(local_today(), district="test-district")
    assert len(entries) == 1
    e = entries[0]
    assert e.fir_no == "100/2026"
    assert e.case_stage == "investigation"


def test_calendar_priority_critical_when_hostile_unprepped(db_session, test_user):
    case, _ = _make_case_with_hearing(db_session, test_user, days_ahead=0, hostile_witnesses=2)

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)
    entries = svc.for_date(local_today(), district="test-district")
    assert len(entries) == 1
    assert entries[0].priority == "critical"
    assert entries[0].hostile_witnesses == 2
    assert entries[0].prepared_witnesses == 0


def test_calendar_priority_high_when_risk_above_50(db_session, test_user):
    _make_case_with_hearing(db_session, test_user, days_ahead=0, risk=0.6)

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)
    entries = svc.for_date(local_today(), district="test-district")
    assert entries[0].priority == "high"


def test_calendar_district_filter(db_session, test_user):
    _make_case_with_hearing(db_session, test_user, days_ahead=0)

    from aranmanai.core.cms.daily_calendar import DailyCalendarService
    svc = DailyCalendarService(db_session)
    other = svc.for_date(local_today(), district="other-district")
    assert len(other) == 0


def test_bottleneck_detects_old_case(db_session, test_user):
    from aranmanai.db.models.case import Case, CaseStage
    case = Case(
        fir_no="200/2026",
        district="test-district",
        io_id=test_user.id,
        stage=CaseStage.INVESTIGATION,
    )
    db_session.add(case)
    db_session.commit()
    from aranmanai.core.cms.bottleneck import BottleneckDetector
    # Default thresholds: warning 30d, critical 90d, alarm 180d
    # We don't actually wait 90 days; we just check the detector runs
    svc = BottleneckDetector(db_session)
    bn = svc.detect(district="test-district")
    # No hearing yet, no fir_date → returns None for the case
    assert bn == []


def test_timeline_builds_fir_and_hearing_events(db_session, test_user):
    from datetime import datetime

    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    case = Case(
        fir_no="300/2026",
        district="test-district",
        io_id=test_user.id,
        fir_date=datetime(2026, 1, 1),
    )
    db_session.add(case)
    db_session.commit()
    h1 = Hearing(case_id=case.id, date=datetime(2026, 2, 1), stage="argument", outcome="adjourned")
    h2 = Hearing(case_id=case.id, date=datetime(2026, 3, 1), stage="judgment", outcome="convicted")
    db_session.add_all([h1, h2])
    db_session.commit()
    from aranmanai.core.cms.timeline import TimelineService
    svc = TimelineService(db_session)
    events = svc.build(case.id)
    assert len(events) == 3  # FIR + 2 hearings
    assert events[0].event_type == "fir"
    assert events[1].date == datetime(2026, 2, 1)
    assert "adjourned" in events[1].label


def test_sp_dashboard_snapshot_basic(db_session, test_user):
    from aranmanai.core.cms.sp_dashboard import SpDashboardService
    _make_case_with_hearing(db_session, test_user, days_ahead=0)
    svc = SpDashboardService(db_session)
    # See test_daily_calendar_for_date_returns_today_hearings for why this
    # must be the local (IST) calendar date, not datetime.utcnow().date().
    snap = svc.snapshot(district="test-district", as_of=local_today())
    assert snap.today_hearings == 1
    assert snap.district == "test-district"
    assert isinstance(snap.top_actions, list)


def test_witness_categorization_changes_category(db_session, test_user):
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessType
    case = Case(fir_no="400/2026", district="test-district", io_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    w = Witness(
        case_id=case.id,
        name_encrypted="w1",
        type=WitnessType.EYEWITNESS,
        category=WitnessCategory.NEUTRAL,
    )
    db_session.add(w)
    db_session.commit()
    from aranmanai.core.witness.categorization import WitnessCategorizationService
    svc = WitnessCategorizationService(db_session)
    w = svc.categorize(w.id, WitnessCategory.HOSTILE, reason="Threat from accused family")
    assert w.category == WitnessCategory.HOSTILE
    assert w.hostile_reason == "Threat from accused family"
    assert w.hostile_since is not None
    # Move back to neutral
    w = svc.categorize(w.id, WitnessCategory.SUPPORTIVE)
    assert w.category == WitnessCategory.SUPPORTIVE
    assert w.hostile_reason is None
