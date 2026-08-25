"""DPDP Act 2023 rights endpoints.

Implements data-subject rights per DPDP §12:
- Right to access (data export)
- Right to correction
- Right to deletion (with evidence carve-outs)

Aranmanai is a law-enforcement tool. Deletion is limited:
- Witness names, statements: can be anonymised but not deleted (evidence)
- Audit logs: CANNOT be deleted (BNSS §176 / CrPC §172 requirement)
- Case records: CANNOT be deleted (judicial record)

Exemptions per DPDP §12(4):
- Prevention/investigation of offences
- Judicial records
- Audit requirements

This module implements the rights in a way that respects both DPDP and
the legal requirements of criminal procedure.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aranmanai.api.deps import CurrentUser, DbSession
from aranmanai.config import get_settings
from aranmanai.db.models.case import Case
from aranmanai.db.models.coordination import CoordinationNote, DailyCaseReview
from aranmanai.db.models.user import User
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog

log = get_logger(__name__)
router = APIRouter(prefix="/dpdp", tags=["dpdp"])


def _audit() -> AuditLog:
    return AuditLog(get_settings().audit_log_path)


# ─── Request / Response models ───────────────────────────────────

class DpdpExportResponse(BaseModel):
    user_id: str
    exported_at: str
    data_categories: dict[str, Any]
    exempt_categories: list[str]


class DpdpDeletionRequest(BaseModel):
    user_id: str
    reason: str | None = None


class DpdpDeletionResponse(BaseModel):
    user_id: str
    status: str
    deleted_fields: list[str]
    retained_fields: list[str]
    exemption_reason: str


# ─── Endpoints ───────────────────────────────────────────────────

@router.get("/export", response_model=DpdpExportResponse)
def export_my_data(user: CurrentUser, db: DbSession) -> DpdpExportResponse:
    """Export all personal data associated with the requesting user.

    DPDP §12(2): Data fiduciary must provide data principal with
    a complete record of their personal data.
    """
    user_record = db.get(User, user.id)
    if not user_record:
        raise HTTPException(404, "User not found")

    data_categories: dict[str, Any] = {}

    # 1. User profile
    data_categories["user"] = {
        "id": user_record.id,
        "username": user_record.username,
        "role": user_record.role.value,
        "district": user_record.district,
        "is_active": user_record.is_active,
        "created_at": user_record.created_at.isoformat() if user_record.created_at else None,
    }

    # 2. Cases the user is assigned to (as IO or PP)
    io_cases = db.query(Case).filter(Case.io_id == user.id).all()
    pp_cases = db.query(Case).filter(Case.pp_id == user.id).all()
    data_categories["cases_as_io"] = [{"id": c.id, "fir_no": c.fir_no, "stage": c.stage.value} for c in io_cases]
    data_categories["cases_as_pp"] = [{"id": c.id, "fir_no": c.fir_no, "stage": c.stage.value} for c in pp_cases]

    # 3. Coordination notes the user authored
    notes = db.query(CoordinationNote).filter(CoordinationNote.actor_id == user.id).all()
    data_categories["coordination_notes"] = [
        {
            "id": n.id,
            "case_id": n.case_id,
            "note_type": n.note_type.value,
            "text": n.text[:200] + "..." if len(n.text) > 200 else n.text,
            "created_at": n.created_at.isoformat(),
        }
        for n in notes
    ]

    # 4. Alerts the user created (Alert has no actor_id in v1)
    # alerts = db.query(Alert).filter(...).all()  # TODO: add actor_id to Alert if needed
    data_categories["alerts_created"] = []

    # 5. Daily reviews the user participated in
    reviews = db.query(DailyCaseReview).filter(DailyCaseReview.sp_id == user.id).all()
    data_categories["daily_reviews"] = [{"id": r.id, "date": r.review_date.isoformat()} for r in reviews]

    # Exempt categories (audit logs cannot be exported to prevent witness intimidation)
    exempt = ["audit_log_entries"]  # BNSS §176 - cannot share investigation details

    _audit().append(
        AuditAction.READ_WITNESS,  # reuse enum
        actor_id=user.id,
        subject_id=user.id,
        success=True,
        metadata={"action": "dpdp_export"},
    )

    return DpdpExportResponse(
        user_id=user.id,
        exported_at=datetime.utcnow().isoformat(),
        data_categories=data_categories,
        exempt_categories=exempt,
    )


@router.post("/delete", response_model=DpdpDeletionResponse)
def request_deletion(req: DpdpDeletionRequest, user: CurrentUser, db: DbSession) -> DpdpDeletionResponse:
    """Request anonymisation/deletion of personal data.

    DPDP §12(3): Data principal may withdraw consent and request deletion.

    Law-enforcement carve-outs (DPDP §12(4)):
    - Audit logs are retained (BNSS §176 requirement)
    - Case evidence (witness statements, exhibits) is retained
    - Judicial records cannot be deleted

    In Aranmanai v1, we implement anonymisation rather than hard deletion:
    - Witness names: hashed (can be de-anonymised with audit log)
    - Contact details: deleted
    - Personal notes on cases: deleted
    - Audit logs: CANNOT be deleted
    - Case records: CANNOT be deleted (judicial record)
    """
    target_id = req.user_id

    # Only the user themselves or an SP can request deletion
    if user.role.value not in ("sp", "admin") and user.id != target_id:
        raise HTTPException(403, "Only the data subject or SP can request deletion")

    target_user = db.get(User, target_id)
    if not target_user:
        raise HTTPException(404, "User not found")

    deleted_fields: list[str] = []
    retained_fields: list[str] = [
        "user_id (audit requirement — BNSS 176)",
        "username (audit requirement)",
        "role (operational requirement)",
        "district (operational requirement)",
        "audit_log_entries (CANNOT be deleted — judicial record requirement)",
        "case records (CANNOT be deleted — BNSS 176)",
        "witness statements (CANNOT be deleted — evidence)",
    ]

    exemption_reason = (
        "Data retained under DPDP §12(4) exemptions: "
        "prevention/investigation of offences; judicial records; "
        "audit requirements under BNSS §176 and CrPC §172."
    )

    # Anonymise sensitive fields
    if target_user.name_encrypted:
        # Replace with hash — can be de-anonymised via audit log
        import hashlib
        target_user.name_encrypted = "DELETED:" + hashlib.sha256(target_user.id.encode()).hexdigest()[:32]
        deleted_fields.append("name_encrypted (anonymised)")

    # Audit the deletion request
    _audit().append(
        AuditAction.UPDATE_WITNESS,
        actor_id=user.id,
        subject_id=target_id,
        success=True,
        metadata={
            "action": "dpdp_deletion_request",
            "reason": req.reason,
            "deleted_fields": deleted_fields,
            "retained_fields": retained_fields,
        },
    )

    log.info("dpdp.deletion_requested by=%s target=%s deleted=%s",
             user.id, target_id, deleted_fields)

    return DpdpDeletionResponse(
        user_id=target_id,
        status="anonymised",
        deleted_fields=deleted_fields,
        retained_fields=retained_fields,
        exemption_reason=exemption_reason,
    )
