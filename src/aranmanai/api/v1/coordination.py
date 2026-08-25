"""Coordination endpoints for the Court Monitoring Cell (CMC) workflow.

The CMC is what moved conviction rate in Eluru (per Kishore Kommi's
public record: 156% conviction rate increase, 51 convictions in 41
cases, 29 life sentences). The mechanism is daily operational
coordination: SP + IO + PP + court constable working together to
ensure witness production, evidence readiness, PP preparation, and
bottleneck resolution.

Endpoints:
- GET  /api/v1/cms/daily-review               - SP morning view
- GET  /api/v1/cms/hearing/{id}/checklist     - per-hearing pre-hearing checklist
- PATCH /api/v1/cms/hearing/{id}/witness-status - IO/constable updates per-witness production
- PATCH /api/v1/cms/hearing/{id}/coordination - PP/defense/accused status
- PATCH /api/v1/cms/hearing/{id}/outcome     - mark hearing outcome (adjourned, argued, judgment)
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aranmanai.api.deps import CurrentUser, DbSession
from aranmanai.config import get_settings
from aranmanai.db.models.case import Case, CaseStage, CaseStatus
from aranmanai.db.models.hearing import Hearing
from aranmanai.db.models.witness import Witness, WitnessPrepStatus
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, decrypt_field

log = get_logger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Daily review (the CMC's main view)
# ─────────────────────────────────────────────────────────────────────

class DailyReviewWitness(BaseModel):
    """Per-witness status for the daily review."""
    witness_id: str
    name: str
    type: str
    category: str
    prep_status: str
    # Per-hearing production status (for THIS hearing)
    production_status: str = "unknown"  # "unknown" | "confirmed" | "uncertain" | "no_show" | "appeared"
    transport_arranged: bool = False
    last_contact: str | None = None
    needs_call: bool = False  # SP/IO should call this witness before tomorrow


class DailyReviewHearing(BaseModel):
    """Per-hearing coordination view for the SP."""
    hearing_id: str
    case_id: str
    fir_no: str
    sections: list[str]
    court: str | None
    judge: str | None
    date: str  # ISO format
    stage: str

    # Coordination status (the CMC's main value: who has confirmed)
    accused_present: bool | None = None
    pp_present: bool | None = None
    defense_present: bool | None = None
    judge_name: str | None = None

    # Witnesses — per-witness production status
    witnesses: list[DailyReviewWitness]
    total_witnesses: int
    hostile_witnesses: int
    ready_witnesses: int
    witnesses_needing_call: int  # not contacted in 7 days AND prep != ready

    # Bottleneck signals
    bottleneck_risk: str = "low"  # "low" | "medium" | "high"
    bottleneck_reason: str = ""

    # Action items (what SP needs to do today for this hearing)
    action_items: list[str]


class DailyReviewResponse(BaseModel):
    """The full daily-review for the SP."""
    date: str  # YYYY-MM-DD
    district: str
    n_hearings: int
    n_critical: int
    n_need_call: int
    n_witnesses_uncontacted: int
    n_cases_with_bottleneck: int
    hearings: list[DailyReviewHearing]
    # Top action items across all hearings
    top_actions: list[str]


@router.get("/daily-review", response_model=DailyReviewResponse)
def get_daily_review(
    target_date: str | None = None,  # YYYY-MM-DD, default = today
    user: CurrentUser = None,
    db: DbSession = None,
) -> DailyReviewResponse:
    """SP's daily review: today's hearings with full coordination status.

    The CMC's main value is showing the SP exactly what needs attention
    before each hearing. This endpoint answers:
    - Which hearings are today (and which are critical)
    - For each hearing, which witnesses are uncontacted / un-prepared
    - For each hearing, whether PP / defense / accused are confirmed
    - What action items the SP needs to push today
    """
    if not target_date:
        target_date = datetime.utcnow().date().isoformat()

    district = user.district

    # All hearings for this district on this date
    from sqlalchemy import func
    target_day = datetime.fromisoformat(target_date)
    hearings = (
        db.query(Hearing)
        .join(Case, Hearing.case_id == Case.id)
        .filter(
            Case.district == district,
            func.date(Hearing.date) == target_day.date(),
        )
        .all()
    )

    review_hearings: list[DailyReviewHearing] = []
    top_actions: list[str] = []
    n_critical = 0
    n_need_call = 0
    n_witnesses_uncontacted = 0
    n_bottleneck = 0

    for h in hearings:
        c = h.case
        if c is None:
            continue

        # Per-witness production
        witnesses_data: list[DailyReviewWitness] = []
        uncontacted = 0
        hostile = 0
        ready = 0
        need_call = 0
        for w in c.witnesses:
            wname = decrypt_field(w.name_encrypted) or "(encrypted)"
            # Per-hearing production: for v1 we use the witness_ids_present list
            production = "unknown"
            if h.witness_ids_present and w.id in h.witness_ids_present:
                production = "appeared"
            # Days since last contact
            days_since = None
            needs_call_flag = False
            if w.last_contact:
                days_since = (datetime.utcnow() - w.last_contact).days
            # Uncontacted in 7 days AND not yet ready = need to call
            if w.prep_status not in (
                WitnessPrepStatus.READY, WitnessPrepStatus.TESTIFIED,
            ) and (days_since is None or days_since >= 7):
                needs_call_flag = True
                need_call += 1
                if days_since is None:
                    uncontacted += 1
            if w.category.value == "hostile":
                hostile += 1
            if w.prep_status == WitnessPrepStatus.READY:
                ready += 1
            witnesses_data.append(DailyReviewWitness(
                witness_id=w.id,
                name=wname,
                type=w.type.value,
                category=w.category.value,
                prep_status=w.prep_status.value,
                production_status=production,
                transport_arranged=False,
                last_contact=days_since.__str__() + " days ago" if days_since is not None else "never",
                needs_call=needs_call_flag,
            ))

        # Bottleneck risk
        bottleneck_risk = "low"
        bottleneck_reason = ""
        n_confirmed = sum(1 for w in witnesses_data if w.production_status == "appeared")
        if hostile > 0 and ready < hostile:
            bottleneck_risk = "high"
            bottleneck_reason = f"{hostile} hostile witnesses, only {ready} ready"
        elif h.pp_present is False:
            bottleneck_risk = "high"
            bottleneck_reason = "PP not confirmed present"
        elif h.accused_present is False:
            bottleneck_risk = "medium"
            bottleneck_reason = "Accused production not confirmed"
        elif n_confirmed < len(witnesses_data) * 0.5:
            bottleneck_risk = "medium"
            bottleneck_reason = f"Only {n_confirmed}/{len(witnesses_data)} witnesses confirmed"
        if bottleneck_risk in ("high", "medium"):
            n_bottleneck += 1
        if bottleneck_risk == "high":
            n_critical += 1

        # Action items
        actions: list[str] = []
        for w in witnesses_data:
            if w.needs_call:
                actions.append(f"Call witness {w.name[:20]}... (last contact: {w.last_contact})")
                n_need_call += 1
        if h.pp_present is False:
            actions.append("Confirm PP availability with Public Prosecutor")
        if h.accused_present is False:
            actions.append("Confirm accused production with court constable")
        if h.defense_present is False:
            actions.append("Confirm defense counsel attendance")
        if bottleneck_reason:
            actions.insert(0, f"⚠ {bottleneck_risk.upper()}: {bottleneck_reason}")

        sections = c.bns_sections or c.bnss_sections or []
        review_hearings.append(DailyReviewHearing(
            hearing_id=h.id,
            case_id=c.id,
            fir_no=c.fir_no,
            sections=sections,
            court=c.court,
            judge=c.judge,
            date=h.date.isoformat(),
            stage=h.stage,
            accused_present=h.accused_present,
            pp_present=h.pp_present,
            defense_present=h.defense_present,
            judge_name=h.judge_name,
            witnesses=witnesses_data,
            total_witnesses=len(witnesses_data),
            hostile_witnesses=hostile,
            ready_witnesses=ready,
            witnesses_needing_call=need_call,
            bottleneck_risk=bottleneck_risk,
            bottleneck_reason=bottleneck_reason,
            action_items=actions,
        ))

        for a in actions[:3]:
            top_actions.append(f"[{h.date.strftime('%H:%M')}] {c.fir_no}: {a}")

    # Sort by bottleneck risk (high first), then date
    risk_order = {"high": 0, "medium": 1, "low": 2}
    review_hearings.sort(key=lambda h: (risk_order.get(h.bottleneck_risk, 3), h.date))

    return DailyReviewResponse(
        date=target_date,
        district=district,
        n_hearings=len(review_hearings),
        n_critical=n_critical,
        n_need_call=n_need_call,
        n_witnesses_uncontacted=n_witnesses_uncontacted,
        n_cases_with_bottleneck=n_bottleneck,
        hearings=review_hearings,
        top_actions=top_actions[:20],
    )


# ─────────────────────────────────────────────────────────────────────
# Per-hearing coordination updates
# ─────────────────────────────────────────────────────────────────────

class WitnessProductionStatus(BaseModel):
    """One witness's production status for a hearing."""
    witness_id: str
    production_status: str  # "unknown" | "confirmed" | "uncertain" | "no_show" | "appeared"
    transport_arranged: bool = False
    notes: str | None = None


class HearingCoordinationUpdate(BaseModel):
    """Per-hearing coordination status update by IO/PP/constable."""
    pp_present: bool | None = None
    defense_present: bool | None = None
    accused_present: bool | None = None
    judge_name: str | None = None
    witness_production: list[WitnessProductionStatus] = Field(default_factory=list)


@router.patch("/hearing/{hearing_id}/coordination")
def update_hearing_coordination(
    hearing_id: str,
    payload: HearingCoordinationUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """Update per-hearing coordination: PP, defense, accused, witness production.

    Called by IO, PP, or court constable to mark who has confirmed.
    SP uses the daily-review endpoint to see these updates.
    """
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if h is None:
        raise HTTPException(404, "Hearing not found")
    if h.case is None or h.case.district != user.district:
        raise HTTPException(403, "Not in your district")

    if payload.pp_present is not None:
        h.pp_present = payload.pp_present
    if payload.defense_present is not None:
        h.defense_present = payload.defense_present
    if payload.accused_present is not None:
        h.accused_present = payload.accused_present
    if payload.judge_name is not None:
        h.judge_name = payload.judge_name

    # Per-witness production
    if payload.witness_production:
        present_ids = list(h.witness_ids_present or [])
        for ws in payload.witness_production:
            w = db.query(Witness).filter(Witness.id == ws.witness_id, Witness.case_id == h.case_id).first()
            if w is None:
                continue
            if ws.production_status == "appeared":
                if ws.witness_id not in present_ids:
                    present_ids.append(ws.witness_id)
                w.hearings_attended = (w.hearings_attended or 0) + 1
                w.last_attended = datetime.utcnow()
            elif ws.production_status == "no_show":
                if ws.witness_id in present_ids:
                    present_ids.remove(ws.witness_id)
            w.last_contact = datetime.utcnow()
        h.witness_ids_present = present_ids

    db.commit()

    # Audit
    AuditLog(get_settings().audit_log_path).append(
        AuditAction.UPDATE_HEARING,
        actor_id=user.id,
        subject_id=hearing_id,
        success=True,
        fields_used=["pp_present", "defense_present", "accused_present", "witness_production"],
    )

    log.info("cms.coordination_update hearing=%s pp=%s def=%s acc=%s witnesses=%d",
             hearing_id, payload.pp_present, payload.defense_present,
             payload.accused_present, len(payload.witness_production))

    return {
        "status": "ok",
        "hearing_id": hearing_id,
        "pp_present": h.pp_present,
        "defense_present": h.defense_present,
        "accused_present": h.accused_present,
        "judge_name": h.judge_name,
        "witness_ids_present": h.witness_ids_present,
    }


# ─────────────────────────────────────────────────────────────────────
# Hearing outcome
# ─────────────────────────────────────────────────────────────────────

class HearingOutcomeRequest(BaseModel):
    outcome: str  # "adjourned" | "argued" | "evidence_recorded" | "judgment" | "withdrawn"
    next_hearing_date: str | None = None
    adjournment_reason: str | None = None
    caused_by: str = "none"  # "none" | "witness" | "pp" | "defense" | "accused" | "judge"
    notes: str | None = None


@router.patch("/hearing/{hearing_id}/outcome")
def update_hearing_outcome(
    hearing_id: str,
    payload: HearingOutcomeRequest,
    user: CurrentUser,
    db: DbSession,
):
    """Mark the outcome of a hearing (adjourned, argued, judgment, etc.).

    Updates case.status / case.stage based on outcome. Feeds the
    bottleneck detection.
    """
    h = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if h is None:
        raise HTTPException(404, "Hearing not found")
    if h.case is None or h.case.district != user.district:
        raise HTTPException(403, "Not in your district")

    h.outcome = payload.outcome
    h.adjournment_reason = payload.adjournment_reason
    h.caused_by = payload.caused_by
    h.notes = payload.notes
    if payload.next_hearing_date:
        from datetime import datetime as _dt
        h.next_hearing_date = _dt.fromisoformat(payload.next_hearing_date)
        h.case.next_hearing = h.next_hearing_date

    # Update case status / stage
    if payload.outcome == "judgment":
        # Caller should separately close the case with the judgment outcome
        h.case.stage = CaseStage.JUDGMENT
    elif payload.outcome == "argued":
        h.case.stage = CaseStage.ARGUMENT
    elif payload.outcome == "evidence_recorded":
        h.case.stage = CaseStage.EVIDENCE
    elif payload.outcome == "adjourned":
        # Stage stays where it is, but we may need a new hearing
        h.case.next_hearing = h.next_hearing_date
    elif payload.outcome == "withdrawn":
        h.case.status = CaseStatus.CLOSED_WITHDRAWN

    h.case.last_hearing = h.date
    db.commit()

    log.info("cms.hearing_outcome hearing=%s outcome=%s caused_by=%s",
             hearing_id, payload.outcome, payload.caused_by)

    return {
        "status": "ok",
        "hearing_id": hearing_id,
        "outcome": h.outcome,
        "case_status": h.case.status.value,
        "case_stage": h.case.stage.value,
        "next_hearing_date": h.next_hearing_date.isoformat() if h.next_hearing_date else None,
    }
