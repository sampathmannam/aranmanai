"""Mock CCTNS adapter.

Reads/writes local JSON shaped like CCTNS Core Application Software (CAS)
v5.0. The real CCTNS is a national platform under MHA; v1 uses a local
file. When DGP sign-off arrives, swap the implementation.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


class MockCctnsAdapter:
    """Read/write CCTNS-shaped JSON for a case.

    Schema (subset of CCTNS CAS v5.0):
    {
      "fir_no": str,
      "district": str,
      "ps": str,
      "fir_date": ISO8601,
      "sections": list[str],
      "complainant": {name, contact, address},
      "accused": list[{name, address}],
      "io": {name, rank, contact},
      "status": str,  # registered / under_investigation / chargesheeted / etc.
      "modification_time": ISO8601,
    }
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        settings = get_settings()
        self.data_dir = data_dir or settings.mock_cctns_data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, fir_no: str) -> Path:
        # Filename-safe version of fir_no
        safe = fir_no.replace("/", "_").replace("\\", "_")
        return self.data_dir / f"{safe}.json"

    def read(self, fir_no: str) -> dict[str, Any] | None:
        p = self._path(fir_no)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, fir_no: str, record: dict[str, Any]) -> str:
        record = dict(record)
        record["fir_no"] = fir_no
        record["modification_time"] = datetime.utcnow().isoformat()
        p = self._path(fir_no)
        with p.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        log.info("cctns.write", fir_no=fir_no, path=str(p))
        return str(p)

    def list_firs(self, district: str | None = None) -> list[str]:
        out: list[str] = []
        for p in self.data_dir.glob("*.json"):
            try:
                with p.open("r", encoding="utf-8") as f:
                    rec = json.load(f)
                if district is None or rec.get("district") == district:
                    out.append(rec.get("fir_no", p.stem))
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(out)

    def import_fir(self, fir_no: str) -> dict[str, Any] | None:
        """Read a CCTNS FIR and return it in Aranmanai format.

        Maps CCTNS fields to Aranmanai fields. Use this when the user
        imports a real CCTNS FIR for the first time.
        """
        rec = self.read(fir_no)
        if not rec:
            return None
        return {
            "fir_no": rec["fir_no"],
            "district": rec.get("district", ""),
            "court": None,
            "judge": None,
            "bns_sections": rec.get("sections", []),
            "bnss_sections": [],
            "bsa_sections": [],
            "facts_text": rec.get("allegations", ""),
            "fir_date": datetime.fromisoformat(rec["fir_date"]) if "fir_date" in rec else None,
            "cctns_metadata": rec,
        }
