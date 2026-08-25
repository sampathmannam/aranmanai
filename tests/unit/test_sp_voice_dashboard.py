"""Unit tests for the SP voice dashboard service (_build_daily_review /
_build_bottlenecks).

Regression coverage for a crash bug: these methods referenced attributes
that do not exist on DailyCalendarEntry (e.time, e.court,
e.ready_witnesses, e.case_stuck, e.days_since_last) or on Bottleneck
(b.reason) -- any non-empty query result raised AttributeError. There was
previously zero test coverage of this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def _make_case_with_hearing(
    db, test_user, fir_no="900/2026", days_ahead=0, hostile_witnesses=0, docket_label="Court Hall 3",
):
    """Create a case + hearing (+ optional hostile witnesses), stamped via
    datetime.utcnow() so it lands in "today" regardless of the machine's
    local timezone (mirrors tests/unit/test_cms.py's helper).
    """
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessType
    hearing_date = datetime.utcnow() + timedelta(days=days_ahead)
    case = Case(
        fir_no=fir_no,
        district="test-district",
        io_id=test_user.id,
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
    h = Hearing(case_id=case.id, date=hearing_date, stage="hearing", docket_label=docket_label)
    db.add(h)
    db.commit()
    db.refresh(case)
    return case, h


def _make_stale_case(db, test_user, fir_no, days_stale):
    """Create a case with no hearings and a stale fir_date, so
    BottleneckDetector flags it (see core/cms/bottleneck.py)."""
    from aranmanai.db.models.case import Case, CaseStage
    case = Case(
        fir_no=fir_no,
        district="test-district",
        io_id=test_user.id,
        stage=CaseStage.INVESTIGATION,
        fir_date=datetime.utcnow() - timedelta(days=days_stale),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ── _build_daily_review ──────────────────────────────────────────────


def test_daily_review_nonempty_uses_real_fields(db_session, test_user):
    """_build_daily_review must use the real DailyCalendarEntry fields
    (hearing_date, docket_label, prepared_witnesses) -- not the nonexistent
    e.time / e.court / e.ready_witnesses that used to raise AttributeError
    the instant a query returned a non-empty result.
    """
    case, _hearing = _make_case_with_hearing(db_session, test_user, hostile_witnesses=2)

    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, actions = svc._build_daily_review("today", district="test-district")

    assert case.fir_no in summary
    assert "Court Hall 3" in summary
    assert "court TBC" not in summary
    # 2 hostile witnesses, 0 prepared (freshly created, no prep_status set)
    assert "2 hostile witness(es), 0 prepared" in summary
    assert any("hostile witness" in a and case.fir_no in a for a in actions)


def test_daily_review_docket_label_falls_back_to_court_tbc(db_session, test_user):
    """When docket_label is None, the summary shows 'court TBC' instead of
    crashing on a nonexistent e.court attribute.
    """
    case, _hearing = _make_case_with_hearing(db_session, test_user, docket_label=None)

    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, _actions = svc._build_daily_review("today", district="test-district")

    assert case.fir_no in summary
    assert "court TBC" in summary


def test_daily_review_empty_when_no_hearings(db_session, test_user):
    """No crash, clean message when there are no hearings today."""
    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, actions = svc._build_daily_review("today", district="test-district")
    assert "No hearings scheduled" in summary
    assert actions == []


def test_daily_review_cross_references_stuck_case(db_session, test_user, monkeypatch):
    """DailyCalendarEntry has no case_stuck / days_since_last of its own --
    the fix cross-references BottleneckDetector by case_id instead. A case
    with a hearing today can't ALSO be genuinely "stuck" under
    BottleneckDetector's own "days since last hearing" rule (a hearing
    today IS the most recent event for that case), so this test
    monkeypatches detect() to exercise the STUCK render path
    deterministically and prove it uses the real Bottleneck fields
    (days_in_stage / case_stage), not the nonexistent e.days_since_last.
    """
    case, _hearing = _make_case_with_hearing(db_session, test_user)

    from aranmanai.core.cms.bottleneck import Bottleneck, BottleneckDetector
    fake_bottleneck = Bottleneck(
        case_id=case.id,
        fir_no=case.fir_no,
        case_stage="investigation",
        days_in_stage=45,
        last_event="hearing",
        last_event_date=datetime.utcnow() - timedelta(days=45),
        severity="critical",
        suggested_action="SP review with IO and PP.",
    )
    monkeypatch.setattr(BottleneckDetector, "detect", lambda self, district=None: [fake_bottleneck])

    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, actions = svc._build_daily_review("today", district="test-district")

    assert "STUCK — 45 days at investigation" in summary
    assert any("escalate" in a and "45 days" in a and case.fir_no in a for a in actions)


# ── _build_bottlenecks ───────────────────────────────────────────────


def test_bottlenecks_nonempty_uses_suggested_action(db_session, test_user):
    """_build_bottlenecks must use b.suggested_action -- not the
    nonexistent b.reason that used to raise AttributeError.
    """
    _make_stale_case(db_session, test_user, "910/2026", days_stale=40)   # warning
    _make_stale_case(db_session, test_user, "920/2026", days_stale=100)  # critical

    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, actions = svc._build_bottlenecks(district="test-district")

    assert "910/2026" in summary
    assert "920/2026" in summary
    assert "Investigate delays in FIR-to-charge-sheet pipeline" in summary
    # The critical-severity one should also produce an immediate-action item
    assert any("920/2026" in a for a in actions)


def test_bottlenecks_empty_when_no_stale_cases(db_session, test_user):
    """No crash, clean message when there are no bottlenecks."""
    from aranmanai.ai.services.sp_voice_dashboard import SpVoiceDashboardService
    svc = SpVoiceDashboardService()
    summary, actions = svc._build_bottlenecks(district="test-district")
    assert "No bottlenecks detected" in summary
    assert actions == []
