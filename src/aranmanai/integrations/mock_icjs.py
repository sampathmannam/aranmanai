"""Mock ICJS (Inter-Operable Criminal Justice System) adapter.

ICJS is the MHA backbone that cross-references police (CCTNS), courts
(e-Courts), prisons (e-Prisons), forensics (e-Forensics), and prosecution
(e-Prosecution) data on a single CNR/case_id key. Real access requires
NIC integration. v1 stores a tiny local index.

ICJS uses these key IDs:
- FIR number (police) ↔ CNR (Case Number Register, court) ↔ PID (prison)
- One FIR has at most one CNR; CNR has many hearings
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


class ICJSCaseIndex(BaseModel):
    """One entry in the local ICJS index."""
    fir_no: str
    cnr: str | None = None  # Case Number Register (court-side ID)
    pid: str | None = None  # Prison ID (if accused is in custody)
    case_id: str  # Our internal case_id (matches Aranmanai)
    court_code: str | None = None
    court_name: str | None = None
    next_hearing: str | None = None  # ISO 8601
    hearing_count: int = 0
    custody_status: str = "unknown"  # unknown | on_bail | judicial_custody | absconding
    last_synced: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


def _mock_path() -> Path:
    p = settings.data_dir / "mock_icjs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_all() -> dict[str, ICJSCaseIndex]:
    p = _mock_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: ICJSCaseIndex.model_validate(v) for k, v in raw.items()}
    except Exception as e:
        log.error("mock_icjs.load failed: %s", e)
        return {}


def _save_all(index: dict[str, ICJSCaseIndex]) -> None:
    p = _mock_path()
    p.write_text(
        json.dumps({k: v.model_dump() for k, v in index.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Public API ---

def link_case(
    *, fir_no: str, case_id: str, cnr: str | None = None, pid: str | None = None,
    court_code: str | None = None, court_name: str | None = None,
    custody_status: str = "unknown",
) -> ICJSCaseIndex:
    """Create or update an ICJS index entry for a case."""
    if settings.icjs_mode != "mock":
        log.warning("icjs.link_case called but mode=%s", settings.icjs_mode)
        raise RuntimeError("ICJS not in mock mode")
    idx = _load_all()
    entry = idx.get(fir_no) or ICJSCaseIndex(
        fir_no=fir_no, case_id=case_id, cnr=cnr, pid=pid,
        court_code=court_code, court_name=court_name, custody_status=custody_status,
    )
    if cnr is not None:
        entry.cnr = cnr
    if pid is not None:
        entry.pid = pid
    if court_code is not None:
        entry.court_code = court_code
    if court_name is not None:
        entry.court_name = court_name
    if custody_status != "unknown":
        entry.custody_status = custody_status
    entry.last_synced = datetime.now(tz=timezone.utc).isoformat()
    idx[fir_no] = entry
    _save_all(idx)
    log.info("mock_icjs.link fir=%s cnr=%s", fir_no, cnr)
    return entry


def lookup(fir_no: str) -> ICJSCaseIndex | None:
    if settings.icjs_mode != "mock":
        return None
    return _load_all().get(fir_no)


def lookup_by_cnr(cnr: str) -> ICJSCaseIndex | None:
    if settings.icjs_mode != "mock":
        return None
    for v in _load_all().values():
        if v.cnr == cnr:
            return v
    return None


def record_hearing(fir_no: str, next_hearing_iso: str) -> bool:
    """Bump hearing count + update next_hearing for a case."""
    if settings.icjs_mode != "mock":
        return False
    idx = _load_all()
    entry = idx.get(fir_no)
    if entry is None:
        return False
    entry.hearing_count += 1
    entry.next_hearing = next_hearing_iso
    entry.last_synced = datetime.now(tz=timezone.utc).isoformat()
    _save_all(idx)
    return True
