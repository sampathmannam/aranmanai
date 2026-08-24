"""Tests for the court constable personnel loop (reward/penalty) +
PP answer accountability + DSP weekly rollup + pilot measurement.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest


@pytest.fixture
def users(db_session):
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import hash_password, encrypt_field
    sp = User(
        username="sp_t", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("SP"), role=UserRole.SP,
        district="test-district", is_active=True,
    )
    io = User(
        username="io_t", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("IO"), role=UserRole.IO,
        district="test-district", is_active=True,
    )
    pp = User(
        username="pp_t", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("PP"), role=UserRole.PP,
        district="test-district", is_active=True,
    )
    cc = User(
        username="cc_t", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("CC"), role=UserRole.COURT_CONSTABLE,
        district="test-district", is_active=True,
    )
    dsp = User(
        username="dsp_t", hashed_password=hash_password("t"),
        name_encrypted=encrypt_field("DSP"), role=UserRole.DSP,
        district="test-district", is_active=True,
    )
    db_session.add_all([sp, io, pp, cc, dsp])
    db_session.commit()
    for u in (sp, io, pp, cc, dsp):
        db_session.refresh(u)
    return {"sp": sp, "io": io, "pp": pp, "cc": cc, "dsp": dsp}


@pytest.fixture
def case(db_session, users):
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    c = Case(
        id="case-001", fir_no="100/2026", district="test-district",
        bns_sections=["BNS 103(1)"], bnss_sections=["BNSS 173(1)(a)"],
        io_id=users["io"].id, pp_id=users["pp"].id,
        sp_id=users["sp"].id,
        status=CaseStatus.TRIAL, stage=CaseStage.EVIDENCE,
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_pp_answer_recorded_separately_from_io(db_session, users, case):
    """PP answer is tracked on its own, distinct from IO's ActionItem.answer."""
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionItem, ActionPriority, ActionStatus, PpAnswer

    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=users["sp"].id)
    action = svc.assign_action(
        meeting_id=m.id, case_id=case.id,
        description="Confirm exhibits for tomorrow",
        action_type="evidence_check", assigned_to=users["io"].id,
        assigned_role="io",
        due_date=datetime.utcnow() + timedelta(hours=2),
        priority=ActionPriority.HIGH,
    )

    # IO answers first
    svc.answer_action(action.id, answer="done", answered_by=users["io"].id)
    db_session.refresh(action)
    assert action.answer == "done"

    # PP answers separately
    pp_ans = svc.pp_answer(
        action_id=action.id, pp_id=users["pp"].id,
        answer="ready", answer_detail="All exhibits prepared",
        evidence_needed=[],
    )
    assert pp_ans.answer == "ready"
    assert pp_ans.pp_id == users["pp"].id

    # Both rows exist, independent
    db_session.refresh(action)
    assert action.answer == "done"  # IO's answer unchanged
    pp_count = db_session.query(PpAnswer).filter(PpAnswer.action_id == action.id).count()
    assert pp_count == 1


def test_pp_answer_needs_evidence_tracks_list(db_session, users, case):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionPriority

    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=users["sp"].id)
    action = svc.assign_action(
        meeting_id=m.id, case_id=case.id,
        description="Final exhibit list", action_type="evidence",
        assigned_to=users["pp"].id, assigned_role="pp",
        due_date=datetime.utcnow() + timedelta(hours=1),
        priority=ActionPriority.MEDIUM,
    )
    pp_ans = svc.pp_answer(
        action_id=action.id, pp_id=users["pp"].id,
        answer="needs_evidence",
        answer_detail="Need FSL report and 2 more 161 statements",
        evidence_needed=["FSL report", "161 statement from witness-3", "161 statement from witness-4"],
    )
    assert pp_ans.answer == "needs_evidence"
    assert len(pp_ans.evidence_needed) == 3
    assert "FSL report" in pp_ans.evidence_needed


def test_record_constable_performance_auto_computes(db_session, users, case):
    """Performance record counts hearings attended, witnesses produced, etc."""
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.hearing import Hearing
    from aranmanai.db.models.witness import Witness, WitnessType

    db_session.add(Witness(
        id="w-1", case_id=case.id, name_encrypted="w1",
        type=WitnessType.EYEWITNESS,
    ))
    h = Hearing(
        case_id=case.id, date=datetime.utcnow(),
        stage="evidence", witness_ids_present=["w-1"],
    )
    db_session.add(h)
    db_session.commit()

    svc = CmcLoopService(db_session)
    period = datetime.utcnow().strftime("%Y-%m")
    perf = svc.record_constable_performance(
        constable_id=users["cc"].id,
        district="test-district",
        period_month=period,
    )
    assert perf.constable_id == users["cc"].id
    assert perf.hearings_attended == 1
    assert perf.witnesses_produced == 1
    assert perf.witness_production_rate == 1.0


def test_commend_constable_awards_cash_and_certificate(db_session, users):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import CourtConstablePerformance

    # First create a performance record
    db_session.add(CourtConstablePerformance(
        id="cc-perf-1", constable_id=users["cc"].id,
        district="test-district", period_month="2026-08",
    ))
    db_session.commit()

    svc = CmcLoopService(db_session)
    perf = svc.commend_constable(
        performance_id="cc-perf-1",
        commended_by=users["sp"].id,
        cash_reward_amount=5000,
        issue_certificate=True,
        reason="100% witness production for August",
    )
    assert perf.excellence_flag is True
    assert perf.cash_reward_amount == 5000
    assert perf.commendation_certificate is True
    assert perf.commended_by == users["sp"].id
    assert perf.commended_at is not None


def test_penalize_constable_records_action(db_session, users):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import CourtConstablePerformance

    db_session.add(CourtConstablePerformance(
        id="cc-perf-2", constable_id=users["cc"].id,
        district="test-district", period_month="2026-08",
    ))
    db_session.commit()

    svc = CmcLoopService(db_session)
    perf = svc.penalize_constable(
        performance_id="cc-perf-2",
        actioned_by=users["sp"].id,
        action_type="warning",
        reason="Failed to produce 3 witnesses in July",
    )
    assert perf.negligence_flag is True
    assert perf.action_taken == "warning"
    assert perf.action_taken_by == users["sp"].id
    assert "3 witnesses" in perf.negligence_reason


def test_penalize_constable_rejects_invalid_action_type(db_session, users):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import CourtConstablePerformance

    db_session.add(CourtConstablePerformance(
        id="cc-perf-3", constable_id=users["cc"].id,
        district="test-district", period_month="2026-08",
    ))
    db_session.commit()

    svc = CmcLoopService(db_session)
    with pytest.raises(ValueError, match="action_type must be"):
        svc.penalize_constable(
            performance_id="cc-perf-3",
            actioned_by=users["sp"].id,
            action_type="INVALID",
            reason="test",
        )


def test_dsp_weekly_rollup_returns_per_station(db_session, users, case):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    svc = CmcLoopService(db_session)
    rollup = svc.dsp_weekly_rollup(
        district="test-district",
        week_start=date.today() - timedelta(days=date.today().weekday()),
    )
    assert rollup["district"] == "test-district"
    assert rollup["n_stations"] >= 1
    assert "stations" in rollup
    assert "n_flagged_stations" in rollup


def test_pilot_conviction_metrics_computes_delta(db_session, users, case):
    """Pilot metrics: conviction rate + delta vs baseline."""
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    from aranmanai.db.models.coordination import PilotCase

    # Create real Case records first (FK constraint)
    for i in range(4):
        c = Case(
            id=f"pilot-case-{i}", fir_no=f"PILOT/{i:03d}/2026",
            district="test-district",
            bns_sections=["BNS 103(1)"],
            io_id=users["io"].id,
            stage=CaseStage.EVIDENCE,
            status=CaseStatus.TRIAL,
        )
        db_session.add(c)
    db_session.commit()

    # Enroll 4 pilot cases
    for i, outcome in enumerate(["convicted", "convicted", "acquitted", "pending"]):
        pc = PilotCase(
            id=f"pc-{i}", case_id=f"pilot-case-{i}",
            district="test-district", enrolled_by=users["sp"].id,
            baseline_p_conviction=0.30,
            outcome=outcome,
        )
        db_session.add(pc)
    db_session.commit()

    svc = CmcLoopService(db_session)
    metrics = svc.pilot_conviction_metrics(district="test-district")
    assert metrics["n_enrolled"] == 4
    assert metrics["n_convicted"] == 2
    assert metrics["n_acquitted"] == 1
    assert metrics["n_pending"] == 1
    # 2 convicted / 3 closed = 0.6667
    assert abs(metrics["conviction_rate"] - 2/3) < 0.01
    # Baseline was 0.30, conviction rate is 0.6667, delta is +0.3667
    assert metrics["delta_conviction_rate"] > 0.36
