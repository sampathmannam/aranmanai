"""Witness protection tracking. BNSS §327 (in-camera), SC/ST PoA §17 (identity)."""
from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from aranmanai.db.models.witness import Witness
from aranmanai.observability import get_logger

log = get_logger(__name__)


ProtectionLevel = Literal["none", "escort", "in_camera", "identity_protected", "full_relocation"]


class WitnessProtectionService:
    """Track and update witness protection level + notes.

    NOTE: This is a TRACKING system, not a protection OPERATIONS system.
    The IO / district witness protection unit does the actual work;
    Aranmanai records what was done.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def set_level(self, witness_id: str, level: ProtectionLevel, notes: str | None = None) -> Witness:
        witness = self.db.get(Witness, witness_id)
        if not witness:
            raise ValueError(f"Witness not found: {witness_id}")
        witness.protection_level = level
        if notes:
            witness.protection_notes = notes
        self.db.commit()
        log.info(
            "witness.protection.set",
            witness_id=witness_id[:8],
            level=level,
        )
        return witness
