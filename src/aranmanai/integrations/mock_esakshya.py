"""Mock eSakshya SID packet adapter.

eSakshya (MHA, launched 4 Aug 2024) issues 16-digit SID (Sakshya ID) packets
for each piece of evidence. Real access requires NIC coordination.
v1 generates + validates SID packets locally.

SID packet fields (per Maharashtra eSakshya Management Rules 2025):
- sid: 16-digit unique ID
- fir_no: linked FIR number
- case_id: linked case
- evidence_type: video | photo | audio | document
- timestamp_open, timestamp_close
- geo_location: lat/lon (string)
- hash_sha256: SHA-256 of the content
- stored_in: "immutable_storage"
- io_badge: investigating officer ID
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.aranmanai.config import settings
from src.aranmanai.logging_config import get_logger

log = get_logger(__name__)

_SID_RE = re.compile(r"^\d{16}$")


class SIDPacket(BaseModel):
    """One eSakshya SID packet."""
    sid: str
    fir_no: str
    case_id: str
    evidence_type: str  # video | photo | audio | document | witness_statement
    timestamp_open: str  # ISO 8601
    timestamp_close: str
    geo_location: str = "13.0878,80.2785"  # Vellore district default
    hash_sha256: str = Field(min_length=64, max_length=64)
    stored_in: str = "immutable_storage"
    io_badge: str

    @field_validator("sid")
    @classmethod
    def _validate_sid(cls, v: str) -> str:
        if not _SID_RE.match(v):
            raise ValueError("sid must be exactly 16 digits")
        return v

    @field_validator("hash_sha256")
    @classmethod
    def _validate_hash(cls, v: str) -> str:
        if not re.match(r"^[0-9a-f]{64}$", v):
            raise ValueError("hash_sha256 must be 64 hex chars")
        return v


def generate_sid() -> str:
    """Generate a fresh 16-digit SID. Uses cryptographic random."""
    return secrets.randbelow(10**16).__format__("016d")


def hash_content(content: bytes) -> str:
    """SHA-256 of arbitrary content. Returns lowercase hex."""
    return hashlib.sha256(content).hexdigest()


def build_packet(
    *,
    fir_no: str,
    case_id: str,
    evidence_type: str,
    content: bytes,
    io_badge: str,
    geo_location: str = "13.0878,80.2785",
) -> SIDPacket:
    """Build a new SID packet for the given content. Auto-generates SID + hash."""
    now = datetime.now(tz=timezone.utc)
    return SIDPacket(
        sid=generate_sid(),
        fir_no=fir_no,
        case_id=case_id,
        evidence_type=evidence_type,
        timestamp_open=now.isoformat(),
        timestamp_close=now.isoformat(),
        geo_location=geo_location,
        hash_sha256=hash_content(content),
        io_badge=io_badge,
    )


# --- File storage ---

def _mock_path() -> Path:
    p = settings.data_dir / "mock_esakshya.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_all() -> dict[str, SIDPacket]:
    p = _mock_path()
    if not p.exists():
        return {}
    try:
        import json
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: SIDPacket.model_validate(v) for k, v in raw.items()}
    except Exception as e:
        log.error("mock_esakshya.load failed: %s", e)
        return {}


def _save_all(packets: dict[str, SIDPacket]) -> None:
    import json
    p = _mock_path()
    p.write_text(
        json.dumps({k: v.model_dump() for k, v in packets.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Public API ---

def upload_packet(packet: SIDPacket) -> bool:
    if settings.esakshya_mode != "mock":
        return False
    packets = _load_all()
    packets[packet.sid] = packet
    _save_all(packets)
    log.info("mock_esakshya.upload sid=%s case=%s type=%s", packet.sid, packet.case_id, packet.evidence_type)
    return True


def get_packet(sid: str) -> SIDPacket | None:
    if settings.esakshya_mode != "mock":
        return None
    return _load_all().get(sid)


def list_packets_for_case(case_id: str) -> list[SIDPacket]:
    if settings.esakshya_mode != "mock":
        return []
    return [p for p in _load_all().values() if p.case_id == case_id]


def validate_hash(sid: str, content: bytes) -> bool:
    """Verify a stored SID packet's hash matches new content. Returns True if match."""
    p = get_packet(sid)
    if p is None:
        return False
    return p.hash_sha256 == hash_content(content)
