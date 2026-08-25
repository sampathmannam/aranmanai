"""Unit tests for the CMC daily action tracker — Kishore's accountability loop."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from aranmanai.core.time_utils import local_today


@pytest.fixture
def setup_users(db_session):
    """Create one SP, one IO, one PP for testing."""
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import encrypt_field, hash_password

    sp = User(
        username="sp_test",
        hashed_password=hash_password("test"),
        name_encrypted=encrypt_field("SP Test"),
        role=UserRole.SP,
        district="test-district",
        is_active=True,
    )
    io = User(
        username="io_test",
        hashed_password=hash_password("test"),
        name_encrypted=encrypt_field("IO Test"),
        role=UserRole.IO,
        district="test-district",
        is_active=True,
    )
    pp = User(
        username="pp_test",
        hashed_password=hash_password("test"),
        name_encrypted=encrypt_field("PP Test"),
        role=UserRole.PP,
        district="test-district",
        is_active=True,
    )
    db_session.add_all([sp, io, pp])
    db_session.commit()
    for u in (sp, io, pp):
        db_session.refresh(u)
    return {"sp": sp, "io": io, "pp": pp}


@pytest.fixture
def setup_case(db_session, setup_users):
    """Create one case for testing."""
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus

    c = Case(
        id="test-case-001",
        fir_no="FIR/TEST/2026/001",
        district="test-district",
        bns_sections=["BNS 103(1)"],
        bnss_sections=["BNSS 173(1)(a)"],
        bsa_sections=[],
        io_id=setup_users["io"].id,
        pp_id=setup_users["pp"].id,
        sp_id=setup_users["sp"].id,
        status=CaseStatus.TRIAL,
        stage=CaseStage.EVIDENCE,
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


def test_open_meeting(db_session, setup_users):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    svc = CmcLoopService(db_session)
    m = svc.open_meeting(
        district="test-district",
        meeting_date=datetime.utcnow(),
        held_by=setup_users["sp"].id,
        attendees=[setup_users["io"].id, setup_users["pp"].id],
        minutes="Today's hearings reviewed",
    )
    assert m.id
    assert m.district == "test-district"
    assert len(m.attendees) == 2


def test_open_meeting_idempotent(db_session, setup_users):
    """Same day, same district = same meeting."""
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    svc = CmcLoopService(db_session)
    now = datetime.utcnow()
    m1 = svc.open_meeting(district="test-district", meeting_date=now, held_by=setup_users["sp"].id)
    m2 = svc.open_meeting(district="test-district", meeting_date=now, held_by=setup_users["sp"].id)
    assert m1.id == m2.id


def test_assign_and_answer_action(db_session, setup_users, setup_case):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionPriority, ActionStatus
    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=setup_users["sp"].id)
    tomorrow = datetime.utcnow() + timedelta(days=1)
    a = svc.assign_action(
        meeting_id=m.id,
        case_id=setup_case.id,
        description="Call witness X about the incident",
        action_type="call_witness",
        assigned_to=setup_users["io"].id,
        assigned_role="io",
        due_date=tomorrow,
        priority=ActionPriority.HIGH,
    )
    assert a.status == ActionStatus.PENDING

    # IO answers
    a2 = svc.answer_action(a.id, answer="done", answer_detail="Witness confirmed", answered_by=setup_users["io"].id)
    assert a2.status == ActionStatus.ANSWERED
    assert a2.answer == "done"


def test_check_overdue_raises_escalation(db_session, setup_users, setup_case):
    """When an action is overdue, sweep marks it OVERDUE and raises an Escalation."""
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionPriority, ActionStatus, Escalation, EscalationStatus
    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=setup_users["sp"].id)
    past_due = datetime.utcnow() - timedelta(hours=1)
    a = svc.assign_action(
        meeting_id=m.id,
        case_id=setup_case.id,
        description="Old action - missed",
        action_type="call_witness",
        assigned_to=setup_users["io"].id,
        assigned_role="io",
        due_date=past_due,
        priority=ActionPriority.URGENT,
    )
    n_esc = svc.check_overdue()
    assert n_esc == 1
    db_session.refresh(a)
    assert a.status == ActionStatus.OVERDUE
    esc = db_session.query(Escalation).filter(Escalation.action_id == a.id).first()
    assert esc is not None
    assert esc.status == EscalationStatus.OPEN
    assert esc.severity == "critical"  # URGENT priority -> critical


def test_sp_review_case(db_session, setup_users, setup_case):
    from datetime import date

    from aranmanai.ai.services.cmc_loop import CmcLoopService
    svc = CmcLoopService(db_session)
    r = svc.sp_review_case(
        case_id=setup_case.id,
        sp_id=setup_users["sp"].id,
        review_date=date.today(),
        status="reviewed",
        notes="All good",
    )
    assert r.id
    assert r.status == "reviewed"
    assert r.sp_id == setup_users["sp"].id


def test_daily_view(db_session, setup_users, setup_case):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionPriority
    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=setup_users["sp"].id)
    svc.assign_action(
        meeting_id=m.id,
        case_id=setup_case.id,
        description="Today: confirm PP",
        action_type="confirm_production",
        assigned_to=setup_users["io"].id,
        assigned_role="io",
        due_date=datetime.utcnow() + timedelta(hours=2),
        priority=ActionPriority.MEDIUM,
    )
    # daily_view() takes a LOCAL (IST) calendar date and converts it to the
    # matching naive-UTC range internally -- the date that correctly
    # contains "right now" (when the action above was assigned via
    # datetime.utcnow()) is local_today(), not datetime.utcnow().date()
    # (see test_cms.py for why these can differ by a day).
    today = local_today()
    v = svc.daily_view(district="test-district", target_date=today)
    assert v.district == "test-district"
    assert v.n_actions_pending >= 1
    assert v.date == today.isoformat()


def test_escalation_acknowledge_and_resolve(db_session, setup_users, setup_case):
    from aranmanai.ai.services.cmc_loop import CmcLoopService
    from aranmanai.db.models.coordination import ActionPriority, EscalationStatus
    svc = CmcLoopService(db_session)
    m = svc.open_meeting(district="test-district", meeting_date=datetime.utcnow(), held_by=setup_users["sp"].id)
    a = svc.assign_action(
        meeting_id=m.id,
        case_id=setup_case.id,
        description="Missed action",
        action_type="call_witness",
        assigned_to=setup_users["io"].id,
        assigned_role="io",
        due_date=datetime.utcnow() - timedelta(hours=2),
        priority=ActionPriority.HIGH,
    )
    svc.check_overdue()  # marks overdue + raises escalation

    from aranmanai.db.models.coordination import Escalation
    esc = db_session.query(Escalation).filter(Escalation.action_id == a.id).first()
    assert esc.status == EscalationStatus.OPEN

    svc.acknowledge_escalation(esc.id, note="Will do")
    db_session.refresh(esc)
    assert esc.status == EscalationStatus.ACKNOWLEDGED

    svc.resolve_escalation(esc.id, note="Witness called")
    db_session.refresh(esc)
    assert esc.status == EscalationStatus.RESOLVED
