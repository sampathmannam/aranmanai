"""Mock eSakshya adapter.

eSakshya is MHA's mobile app for evidence collection (BNSS §105, 173,
176, 180, 185, 497). Each piece of evidence has a 16-digit SID packet
with hash + timestamp + geo. v1 uses a local file; swap for real API
when MHA access is granted.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from aranmanai.config import get_settings
from aranmanai.observability import get_logger

log = get_logger(__name__)


def generate_sid() -> str:
    """Generate a 16-digit SID per eSakshya spec."""
    return "".join(secrets.choice(string.digits) for _ in range(16))


def compute_content_hash(content: bytes) -> str:
    """SHA-256 hash for tamper detection per eSakshya spec."""
    return hashlib.sha256(content).hexdigest()


class MockEsakshyaAdapter:
    """Read/write eSakshya-shaped SID packets for evidence."""

    def __init__(self, data_dir: Path | None = None) -> None:
        settings = get_settings()
        self.data_dir = data_dir or settings.mock_esakshya_data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        return self.data_dir / f"{sid}.json"

    def create_packet(
        self,
        fir_no: str,
        evidence_type: str,  # video / photo / statement
        captured_by: str,
        content_bytes: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new SID packet."""
        sid = generate_sid()
        now = datetime.utcnow()
        packet = {
            "sid": sid,
            "fir_no": fir_no,
            "evidence_type": evidence_type,
            "captured_by": captured_by,
            "captured_at": now.isoformat(),
            "content_hash": compute_content_hash(content_bytes),
            "content_size_bytes": len(content_bytes),
            "metadata": metadata or {},
            "version": "1.0",
        }
        with self._path(sid).open("w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2, ensure_ascii=False)
        log.info("esakshya.packet_created", sid=sid, fir_no=fir_no, type=evidence_type)
        return packet

    def read(self, sid: str) -> dict[str, Any] | None:
        p = self._path(sid)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_for_fir(self, fir_no: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in self.data_dir.glob("*.json"):
            try:
                with p.open("r", encoding="utf-8") as f:
                    rec = json.load(f)
                if rec.get("fir_no") == fir_no:
                    out.append(rec)
            except (json.JSONDecodeError, OSError):
                continue
        return out
