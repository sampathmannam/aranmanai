"""Mock CCTNS (Crime and Criminal Tracking Network & Systems) adapter.

CCTNS uses the Core Application Software (CAS) v5.0 schema. Real
access requires NIC sign-off + state SCRB coordination. v1 reads +
writes to a local JSON file shaped like the CAS case-export format.

CAS case fields we mirror (per NIC CAS v5.0 docs, public summary):
- case_id, fir_no, fir_date, sections[], ps_code, district, state
- accused[], victim[], witness[], investigation_officer
- chargesheet_no, chargesheet_date, court_code
- status (open / chargesheeted / trial / conviction / acquittal)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.aranmanai.config import settings
from src.aranmanai.logging_config import get_logger

log = get_logger(__name__)


class CCTNSCase(BaseModel):
    """CCTNS CAS v5.0 case export — minimal fields we mirror."""
    case_id: str
    fir_no: str | None = None
    fir_date: str | None = None  # ISO 8601
    sections: list[str] = Field(default_factory=list)
    ps_code: str = "TN-VLR"  # Police station code, default Vellore
    district: str = "Vellore"
    state: str = "Tamil Nadu"
    accused: list[dict[str, Any]] = Field(default_factory=list)
    victim: list[dict[str, Any]] = Field(default_factory=list)
    witness: list[dict[str, Any]] = Field(default_factory=list)
    investigation_officer: str | None = None
    chargesheet_no: str | None = None
    chargesheet_date: str | None = None
    court_code: str | None = None
    status: str = "open"  # open | chargesheeted | trial | conviction | acquittal | appeal
    last_modified: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


# --- File storage ---

def _mock_path() -> Path:
    """Local JSON file shaped like the CAS export directory."""
    p = settings.data_dir / "mock_cctns.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_all() -> dict[str, CCTNSCase]:
    """Load all mock cases from the JSON file. Empty if file doesn't exist."""
    p = _mock_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: CCTNSCase.model_validate(v) for k, v in raw.items()}
    except Exception as e:
        log.error("mock_cctns.load failed: %s", e)
        return {}


def _save_all(cases: dict[str, CCTNSCase]) -> None:
    p = _mock_path()
    p.write_text(
        json.dumps({k: v.model_dump() for k, v in cases.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Public API ---

def push_case(case: CCTNSCase) -> bool:
    """Push a case to mock CCTNS. Idempotent on case_id."""
    if settings.cctns_mode != "mock":
        log.warning("cctns.push_case called but mode=%s (not mock)", settings.cctns_mode)
        return False
    cases = _load_all()
    cases[case.case_id] = case
    _save_all(cases)
    log.info("mock_cctns.push case_id=%s status=%s", case.case_id, case.status)
    return True


def pull_case(case_id: str) -> CCTNSCase | None:
    """Pull a case from mock CCTNS. Returns None if not found."""
    if settings.cctns_mode != "mock":
        log.warning("cctns.pull_case called but mode=%s", settings.cctns_mode)
        return None
    return _load_all().get(case_id)


def list_case_ids() -> list[str]:
    """List all case_ids in the mock CCTNS store."""
    if settings.cctns_mode != "mock":
        return []
    return list(_load_all().keys())


def delete_case(case_id: str) -> bool:
    """Remove a case from mock CCTNS. Returns True if removed."""
    if settings.cctns_mode != "mock":
        return False
    cases = _load_all()
    if case_id in cases:
        del cases[case_id]
        _save_all(cases)
        return True
    return False
