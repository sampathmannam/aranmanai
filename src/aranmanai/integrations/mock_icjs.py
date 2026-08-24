"""Mock ICJS adapter.

ICJS (Inter-Operable Criminal Justice System) integrates CCTNS + e-Courts
+ e-Prisons + e-Forensics + e-Prosecution + NAFIS. v1 uses a local
file; v2 swaps for the real ICJS API.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


class MockIcjsAdapter:
    """Cross-reference cases between Aranmanai and court CNRs."""

    def __init__(self, data_dir: Path | None = None) -> None:
        settings = get_settings()
        self.data_dir = data_dir or settings.mock_icjs_data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "case_index.json"
        if not self.index_path.exists():
            self.index_path.write_text("{}", encoding="utf-8")

    def _read_index(self) -> dict[str, Any]:
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_index(self, index: dict[str, Any]) -> None:
        self.index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def link_case(self, aranmanai_case_id: str, cnr: str, court: str) -> dict[str, Any]:
        """Link an Aranmanai case to an ICJS CNR."""
        index = self._read_index()
        index[aranmanai_case_id] = {
            "cnr": cnr,
            "court": court,
            "linked_at": __import__("datetime").datetime.utcnow().isoformat(),
        }
        self._write_index(index)
        log.info("icjs.link", case_id=aranmanai_case_id[:8], cnr=cnr, court=court)
        return index[aranmanai_case_id]

    def lookup(self, aranmanai_case_id: str) -> dict[str, Any] | None:
        index = self._read_index()
        return index.get(aranmanai_case_id)
