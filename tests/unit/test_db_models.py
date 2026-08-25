"""Unit tests for DB models + session."""
from __future__ import annotations


def test_init_db_creates_all_tables(tmp_env):
    from aranmanai.db import init_db
    from aranmanai.db.session import Base
    init_db()
    tables = set(Base.metadata.tables.keys())
    expected = {"case", "witness", "hearing", "evidence", "user", "audit_log"}
    assert expected.issubset(tables)


def test_create_and_query_case(db_session, test_user):
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    case = Case(
        fir_no="123/2026",
        district="test-district",
        bns_sections=["BNS 308"],
        bnss_sections=["154 BNSS"],
        io_id=test_user.id,
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    fetched = db_session.get(Case, case.id)
    assert fetched.fir_no == "123/2026"
    assert fetched.bns_sections == ["BNS 308"]
    assert fetched.status == CaseStatus.OPEN
    assert fetched.stage == CaseStage.INVESTIGATION
    assert fetched.io_id == test_user.id


def test_create_witness_with_encrypted_name(db_session, test_user):
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.witness import Witness, WitnessCategory, WitnessType
    case = Case(fir_no="124/2026", district="test-district", io_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    witness = Witness(
        case_id=case.id,
        name_encrypted="gAAAAA_encrypted_Ravi",  # mock encrypted
        type=WitnessType.EYEWITNESS,
        category=WitnessCategory.SUPPORTIVE,
    )
    db_session.add(witness)
    db_session.commit()
    db_session.refresh(witness)
    assert witness.type == WitnessType.EYEWITNESS
    assert witness.category == WitnessCategory.SUPPORTIVE
    assert witness.prep_status.value == "untouched"


def test_create_hearing_attendance_tracking(db_session, test_user):
    from datetime import datetime

    from aranmanai.db.models.case import Case
    from aranmanai.db.models.hearing import Hearing
    case = Case(fir_no="125/2026", district="test-district", io_id=test_user.id)
    db_session.add(case)
    db_session.commit()
    h = Hearing(
        case_id=case.id,
        date=datetime(2026, 9, 1, 10, 0),
        stage="hearing",
        pp_present=True,
        defense_present=True,
        accused_present=True,
    )
    db_session.add(h)
    db_session.commit()
    db_session.refresh(h)
    assert h.pp_present is True
    assert h.accused_present is True
    assert h.outcome is None


def test_create_evidence_with_sid(tmp_env):
    from aranmanai.db import init_db
    from aranmanai.db.models.case import Case
    from aranmanai.db.models.evidence import Evidence, EvidenceChainStatus, EvidenceType, FslStatus
    init_db()
    from aranmanai.db import SessionLocal
    from aranmanai.db.models.user import User, UserRole
    from aranmanai.security import encrypt_field, hash_password
    db = SessionLocal()
    try:
        user = User(
            username="u1",
            hashed_password=hash_password("p1234567"),
            name_encrypted=encrypt_field("User 1"),
            role=UserRole.ADMIN,
            district="test-district",
        )
        db.add(user)
        db.commit()
        case = Case(fir_no="126/2026", district="test-district", io_id=user.id)
        db.add(case)
        db.commit()
        e = Evidence(
            case_id=case.id,
            type=EvidenceType.FSL,
            description="Knife recovered from accused",
            chain_status=EvidenceChainStatus.SEALED,
            fsl_status=FslStatus.SENT,
            sid="1234567890123456",
            content_hash="a" * 64,
        )
        db.add(e)
        db.commit()
        db.refresh(e)
        assert e.sid == "1234567890123456"
        assert e.chain_status == EvidenceChainStatus.SEALED
    finally:
        db.close()
