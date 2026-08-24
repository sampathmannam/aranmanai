"""Tests for the chargesheet vetting service (FIR gap-checker)."""
from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture
def case_with_witnesses(db_session, test_user):
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    from aranmanai.db.models.witness import Witness, WitnessType, WitnessCategory
    c = Case(
        id="vet-case-1", fir_no="FIR/2026/001", district="test-district",
        bns_sections=["BNS 103(1)"], bnss_sections=["BNSS 173(1)(a)"],
        io_id=test_user.id, status=CaseStatus.TRIAL, stage=CaseStage.EVIDENCE,
    )
    db_session.add(c)
    db_session.commit()
    # Add a witness with statement
    w = Witness(
        id="w-stmt", case_id=c.id, name_encrypted="w1",
        type=WitnessType.EYEWITNESS, category=WitnessCategory.NEUTRAL,
        statement_text_encrypted="My statement",
    )
    db_session.add(w)
    db_session.commit()
    return c


def test_vet_passes_when_all_required_present(db_session, case_with_witnesses):
    from aranmanai.db.models.evidence import Evidence
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    db_session.add(Evidence(
        id="ev-1", case_id="vet-case-1",
        description="Knife recovered from accused house under Section 27 BSA",
        chain_status="sealed", fsl_status="returned",
    ))
    db_session.commit()

    svc = ChargesheetVettingService(db_session)
    report = svc.vet("vet-case-1")
    assert report.verdict == "READY"
    assert report.required_failed == 0


def test_vet_blocks_when_no_io_assigned(db_session):
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    c = Case(
        id="vet-case-2", fir_no="FIR/2026/002", district="test-district",
        bns_sections=["BNS 376"], stage=CaseStage.EVIDENCE,
    )
    db_session.add(c)
    db_session.commit()
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    svc = ChargesheetVettingService(db_session)
    report = svc.vet("vet-case-2")
    assert report.verdict in ("NEEDS_FIXES", "BLOCKED")
    items_by_code = {i.code: i for i in report.items}
    assert items_by_code["fir_parties_named"].passed is False


def test_vet_blocks_when_no_witnesses_or_evidence(db_session, case_with_witnesses):
    """No evidence at all → BLOCKED."""
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    svc = ChargesheetVettingService(db_session)
    report = svc.vet("vet-case-1")
    assert report.verdict in ("NEEDS_FIXES", "BLOCKED")
    items_by_code = {i.code: i for i in report.items}
    assert items_by_code["fir_evidence"].passed is False


def test_vet_flags_witnesses_without_161_statements(db_session, case_with_witnesses):
    """A witness without 161 statement → gap-checker fails that item."""
    from aranmanai.db.models.witness import Witness, WitnessType
    db_session.add(Witness(
        id="w-nostmt", case_id="vet-case-1", name_encrypted="w2",
        type=WitnessType.EYEWITNESS,
    ))
    db_session.commit()
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    svc = ChargesheetVettingService(db_session)
    report = svc.vet("vet-case-1")
    items_by_code = {i.code: i for i in report.items}
    assert items_by_code["fir_161_statements"].passed is False


def test_vet_too_early_in_stage(db_session, test_user):
    """Case still in INVESTIGATION stage → can't file chargesheet yet."""
    from aranmanai.db.models.case import Case, CaseStage, CaseStatus
    c = Case(
        id="vet-case-3", fir_no="FIR/2026/003", district="test-district",
        bns_sections=["BNS 103"], stage=CaseStage.INVESTIGATION,
        io_id=test_user.id,
    )
    db_session.add(c)
    db_session.commit()
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    svc = ChargesheetVettingService(db_session)
    report = svc.vet("vet-case-3")
    items_by_code = {i.code: i for i in report.items}
    assert items_by_code["fir_charge_sheet_drafted"].passed is False


def test_vet_finds_case_not_found(db_session):
    from aranmanai.ai.services.chargesheet_vetting import ChargesheetVettingService
    svc = ChargesheetVettingService(db_session)
    with pytest.raises(ValueError, match="not found"):
        svc.vet("nonexistent-case-id")
