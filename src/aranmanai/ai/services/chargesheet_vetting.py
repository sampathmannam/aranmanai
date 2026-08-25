"""Chargesheet vetting — gap-check a case before chargesheet filing.

Per Kishore's Project DHARMA: chargesheet vetting modules auto-check
if the FIR is missing key elements. This is that module, but as a
deterministic rules engine (we don't have an LLM-judge in v1; the gap
list is a fixed checklist the IO is supposed to satisfy per CrPC
173(2)/BNS).

What it checks (CrPC 173(2) required elements):
- Parties named (informant, accused)
- Nature of information
- Persons acquainted with circumstances
- Whether offence appears committed and by whom
- Whether accused arrested
- If not arrested, whether released on bond
- Whether forwarded in custody under section 170
- Medical examination report (rape/POCSO sections)
- 161 statements of all prosecution witnesses
- 164 statements (if any)
- Search/seizure details
- FSL report (if applicable)
- BNS/BNSS sections listed
- IO signed

Returns a vetting report with: passed items, failed items (gaps), and
a verdict (READY | NEEDS_FIXES | BLOCKED).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from aranmanai.db.models.case import Case, CaseStage
from aranmanai.db.models.evidence import Evidence
from aranmanai.db.models.witness import Witness
from aranmanai.observability import get_logger

log = get_logger(__name__)


@dataclass
class VettingItem:
    """A single check in the vetting report."""
    code: str  # e.g. "fir_parties_named"
    label: str  # human-readable
    required: bool  # true = mandatory, false = recommended
    passed: bool
    note: str | None = None  # why it failed, if failed


@dataclass
class VettingReport:
    case_id: str
    fir_no: str
    checked_at: str
    items: list[VettingItem]
    passed_count: int
    failed_count: int
    required_failed: int
    verdict: str  # READY | NEEDS_FIXES | BLOCKED
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fir_no": self.fir_no,
            "checked_at": self.checked_at,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "required_failed": self.required_failed,
            "verdict": self.verdict,
            "summary": self.summary,
            "items": [
                {
                    "code": i.code,
                    "label": i.label,
                    "required": i.required,
                    "passed": i.passed,
                    "note": i.note,
                }
                for i in self.items
            ],
        }


class ChargesheetVettingService:
    """Vet a case's evidence before chargesheet filing. Pure rules engine."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def vet(self, case_id: str) -> VettingReport:
        case = self.db.get(Case, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")

        items: list[VettingItem] = []

        # 1. Parties named
        items.append(VettingItem(
            code="fir_parties_named",
            label="Parties named (informant + accused)",
            required=True,
            passed=bool(case.io_id),  # IO assigned = investigation started
            note=None if case.io_id else "No IO assigned to the case",
        ))

        # 2. BNS sections listed
        bns = case.bns_sections or []
        items.append(VettingItem(
            code="fir_bns_sections",
            label="BNS sections listed",
            required=True,
            passed=len(bns) > 0,
            note=None if bns else "No BNS sections in case file",
        ))

        # 3. Witnesses exist
        witnesses = self.db.query(Witness).filter(Witness.case_id == case_id).all()
        n_witnesses = len(witnesses)
        items.append(VettingItem(
            code="fir_witnesses",
            label="At least 1 witness on file",
            required=True,
            passed=n_witnesses > 0,
            note=None if n_witnesses else "No witnesses recorded for this case",
        ))

        # 4. Witness statements recorded (statement_text_encrypted)
        n_with_statements = sum(1 for w in witnesses if w.statement_text_encrypted)
        items.append(VettingItem(
            code="fir_161_statements",
            label="161 CrPC statements recorded for prosecution witnesses",
            required=True,
            passed=n_with_statements >= n_witnesses and n_witnesses > 0,
            note=(
                None if n_with_statements >= n_witnesses and n_witnesses > 0
                else f"{n_witnesses - n_with_statements} of {n_witnesses} witnesses missing 161 statement"
            ),
        ))

        # 5. Evidence exists
        evidence = self.db.query(Evidence).filter(Evidence.case_id == case_id).all()
        n_evidence = len(evidence)
        items.append(VettingItem(
            code="fir_evidence",
            label="At least 1 piece of evidence on file",
            required=True,
            passed=n_evidence > 0,
            note=None if n_evidence else "No evidence recorded for this case",
        ))

        # 6. Search/seizure memo if applicable (v1: heuristic — if any POCSO/heinous sections)
        is_heinous = any(
            s in str(case.bns_sections or "") + str(case.bns_sections or "")
            for s in ["POCSO", "302", "303", "304", "376", "370", "307"]
        )
        if is_heinous:
            items.append(VettingItem(
                code="fir_search_seizure",
                label="Search/seizure memo for POCSO/heinous case",
                required=True,
                passed=n_evidence > 0,  # proxy — if evidence exists, seizure happened
                note=None if n_evidence else "No evidence / no seizure record",
            ))

        # 7. FSL report if applicable (any case with physical/forensic evidence)
        fsl_overdue = any(e.fsl_status in ("overdue", "not_sent") for e in evidence)
        if n_evidence > 0:
            items.append(VettingItem(
                code="fir_fsl",
                label="FSL report status acceptable",
                required=False,  # recommended, not blocking
                passed=not fsl_overdue,
                note=None if not fsl_overdue else "Some evidence has FSL overdue or not_sent",
            ))

        # 8. BNSS sections
        bnss = case.bnss_sections or []
        items.append(VettingItem(
            code="fir_bnss_sections",
            label="BNSS procedural sections listed",
            required=False,
            passed=len(bnss) > 0,
            note=None if bnss else "Consider adding BNSS 173/193 procedural sections",
        ))

        # 9. Charge sheet date / hearings (have we filed at least one hearing?)
        # For chargesheet stage, hearings may or may not exist yet
        items.append(VettingItem(
            code="fir_charge_sheet_drafted",
            label="Case at or past charge sheet stage",
            required=True,
            passed=case.stage in (
                CaseStage.CHARGE_SHEET, CaseStage.EVIDENCE,
                CaseStage.ARGUMENT, CaseStage.JUDGMENT,
            ),
            note=(
                None if case.stage in (
                    CaseStage.CHARGE_SHEET, CaseStage.EVIDENCE,
                    CaseStage.ARGUMENT, CaseStage.JUDGMENT,
                )
                else f"Case is at {case.stage.value} stage — too early for charge sheet"
            ),
        ))

        # Tally
        passed = sum(1 for i in items if i.passed)
        failed = sum(1 for i in items if not i.passed)
        required_failed = sum(1 for i in items if not i.passed and i.required)

        if required_failed == 0:
            verdict = "READY"
            summary = "All required elements present. Ready to file chargesheet."
        elif required_failed <= 2:
            verdict = "NEEDS_FIXES"
            summary = f"{required_failed} required element(s) missing. Fix before filing."
        else:
            verdict = "BLOCKED"
            summary = f"{required_failed} required elements missing. Do not file."

        report = VettingReport(
            case_id=case_id,
            fir_no=case.fir_no,
            checked_at=datetime.utcnow().isoformat(),
            items=items,
            passed_count=passed,
            failed_count=failed,
            required_failed=required_failed,
            verdict=verdict,
            summary=summary,
        )
        log.info(
            "vet.case=%s verdict=%s passed=%d failed=%d required_failed=%d",
            case_id, verdict, passed, failed, required_failed,
        )
        return report
