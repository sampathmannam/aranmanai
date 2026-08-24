"""Court Monitoring System (CMS) endpoints.

The operational core. Pattern sources: Kishore Kommi's Court Monitoring
Cell (Eluru) and Dheeraj Kunubilli's CMS (Annamayya). v1 endpoints:
- /cms/daily-calendar          — today's hearings for the district
- /cms/cases-at-risk           — cases sorted by acquittal_risk + hostile witnesses
- /cms/bottlenecks             — cases stuck at stage X > Y days
- /cms/queue-stats             — aggregate metrics (count by status, hostile ratio)
- /cms/witness-prep            — AI-assisted cross-exam prep request
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import Case, Hearing, User, Witness
from src.aranmanai.schemas import (
    BottleneckReport,
    CaseRead,
    DailyCalendarItem,
    DailyCalendarResponse,
    WitnessPrepRequest,
    WitnessPrepResponse,
)
from src.aranmanai.security import get_current_user, record_audit

log = get_logger(__name__)

router = APIRouter(prefix="/cms", tags=["cms"])


def _day_bounds(date: int) -> tuple[int, int]:
    """Convert YYYY-MM-DD (midnight UTC) to (start_of_day, end_of_day) epoch seconds."""
    dt = datetime.fromtimestamp(date, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = int(dt.timestamp())
    end = start + 86400
    return start, end


@router.get("/daily-calendar", response_model=DailyCalendarResponse)
def daily_calendar(
    date: int = Query(description="YYYY-MM-DD as midnight-UTC epoch seconds"),
    district: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> DailyCalendarResponse:
    """Today's hearings for the SP. Sorted by court then case."""
    if actor.role == "SP":
        district = actor.district
    elif district is None:
        district = actor.district
    start, end = _day_bounds(date)
    q = (
        db.query(Hearing, Case, User)
        .join(Case, Hearing.case_id == Case.id)
        .outerjoin(User, Case.pp_id == User.id)
        .filter(Hearing.date >= start, Hearing.date < end)
    )
    if district is not None:
        q = q.filter(Case.district == district)
    items: list[DailyCalendarItem] = []
    for h, c, pp in q.all():
        witnesses = (
            db.query(Witness)
            .filter(Witness.case_id == c.id)
            .order_by(Witness.category, Witness.name)
            .all()
        )
        hostile_count = sum(1 for w in witnesses if w.category == "Hostile")
        items.append(
            DailyCalendarItem(
                case_id=c.case_id,
                case_internal_id=c.id,
                fir_no=c.fir_no,
                section_summary=", ".join(c.sections[:3]) if c.sections else c.offence,
                hearing_id=h.id,
                hearing_date=h.date,
                hearing_stage=h.stage,
                court=c.court,
                judge=c.judge,
                pp_name=pp.name if pp else None,
                witnesses_to_prep=[
                    w for w in witnesses
                    if w.prep_status in ("untouched", "prepped") and w.category in ("Hostile", "Neutral")
                ],
                hostile_witness_count=hostile_count,
                total_witness_count=len(witnesses),
            )
        )
    items.sort(key=lambda i: (i.court or "", i.case_id))
    cases_at_risk = sum(1 for i in items if i.hostile_witness_count > 0)
    return DailyCalendarResponse(
        date=date,
        district=district or "",
        items=items,
        total_hearings=len(items),
        total_cases_at_risk=cases_at_risk,
    )


@router.get("/cases-at-risk", response_model=list[CaseRead])
def cases_at_risk(
    limit: int = Query(default=20, ge=1, le=100),
    min_hostile: int = Query(default=1, ge=0, description="Minimum hostile-witness count"),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[Case]:
    """Cases ranked by acquittal risk. SP dashboard — the 'act this week' list."""
    q = db.query(Case).filter(
        Case.status.in_(("open", "hearing")),
        Case.acquittal_risk.isnot(None),
    )
    if actor.role == "SP":
        q = q.filter(Case.district == actor.district)
    cases = q.order_by(
        Case.acquittal_risk.desc().nullslast(),
        Case.next_hearing.asc().nullslast(),
    ).limit(limit).all()
    # Filter by min hostile count post-query (avoids group-by complexity)
    out: list[Case] = []
    for c in cases:
        hostile = db.query(func.count(Witness.id)).filter(
            Witness.case_id == c.id, Witness.category == "Hostile",
        ).scalar() or 0
        if hostile >= min_hostile:
            out.append(c)
    return out[:limit]


@router.get("/bottlenecks", response_model=BottleneckReport)
def bottlenecks(
    threshold_days: int = Query(default=60, ge=1, description="Days without update = bottleneck"),
    district: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> BottleneckReport:
    """Cases that have been at the same stage for > threshold_days. Default 60 days."""
    threshold_seconds = threshold_days * 86400
    now = int(datetime.now(tz=timezone.utc).timestamp())
    cutoff = now - threshold_seconds
    q = db.query(Case).filter(
        Case.status.in_(("open", "hearing")),
        Case.last_update < cutoff,
    )
    if actor.role == "SP":
        q = q.filter(Case.district == actor.district)
    elif district is not None:
        q = q.filter(Case.district == district)
    items = q.order_by(Case.last_update.asc()).all()
    return BottleneckReport(
        threshold_days=threshold_days,
        items=items,
        bottleneck_count=len(items),
    )


@router.get("/queue-stats")
def queue_stats(
    district: str | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> dict:
    """Aggregate dashboard metrics. Used by SP home page."""
    if actor.role == "SP":
        district = actor.district

    base = db.query(Case)
    if district is not None:
        base = base.filter(Case.district == district)

    total = base.count()
    by_status = dict(
        db.query(Case.status, func.count(Case.id))
        .filter(Case.district == district) if district else
        db.query(Case.status, func.count(Case.id))
        .group_by(Case.status).all()
    )
    by_stage = dict(
        db.query(Case.stage, func.count(Case.id))
        .filter(Case.district == district) if district else
        db.query(Case.stage, func.count(Case.id))
        .group_by(Case.stage).all()
    )
    hostile_count = (
        db.query(func.count(Witness.id))
        .join(Case, Witness.case_id == Case.id)
        .filter(Case.district == district, Witness.category == "Hostile")
        .scalar() or 0 if district else
        db.query(func.count(Witness.id))
        .filter(Witness.category == "Hostile")
        .scalar() or 0
    )
    return {
        "district": district or "ALL",
        "total_cases": total,
        "by_status": by_status,
        "by_stage": by_stage,
        "hostile_witness_count": hostile_count,
        "as_of": int(datetime.now(tz=timezone.utc).timestamp()),
    }


@router.post("/witness-prep", response_model=WitnessPrepResponse)
def witness_prep(
    body: WitnessPrepRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> WitnessPrepResponse:
    """AI-assisted cross-examination prep for one witness.

    v1: returns a structured stub with rule-based likely questions
    derived from the witness's category + case sections. v2 wires in
    the real LLM via src/aranmanai.ai.llm_client.
    """
    witness = db.get(Witness, body.witness_id)
    if witness is None or witness.case_id != body.case_id:
        raise HTTPException(status_code=404, detail="Witness not found in case")
    case = db.get(Case, body.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if actor.role == "SP" and case.district != actor.district:
        raise HTTPException(status_code=403, detail="Cross-district write not allowed")

    # Rule-based prep generation (v1 stub; LLM upgrade in v2)
    likely_questions: list[dict[str, str]] = []
    sections_str = ", ".join(case.sections[:3]) if case.sections else case.offence
    likely_questions.extend([
        {"question": f"Can you describe what you saw on the date of the incident in your own words?",
         "rationale": "Establishes witness's direct observation baseline; defense uses to test consistency."},
        {"question": f"How do you identify the accused? Were you shown the accused before today?",
         "rationale": "Tests TIP compliance and identification reliability; key BNSS §9(7) issue."},
        {"question": f"What is your relationship (if any) to the complainant / victim / accused?",
         "rationale": "Establishes bias or interest — defense's most-used hostile-witness angle."},
    ])
    if "304B" in (case.sections or []) or "dowry" in case.facts_text.lower() if case.facts_text else False:
        likely_questions.append({
            "question": "Were there any demands for money, property, or valuables before the death? Specify each demand and the date.",
            "rationale": "Crucial for 304B / 80 BNS; vague answers here collapse the case per Quint 500 dowry study.",
        })
    if any("POCSO" in s or "376" in s for s in (case.sections or [])):
        likely_questions.append({
            "question": "At what point did you first disclose this incident? To whom? When was the FIR filed?",
            "rationale": "Delay in disclosure is the defense's primary attack; specific dates are critical.",
        })
    if witness.category == "Hostile":
        likely_questions.append({
            "question": "Have you been threatened, pressured, or offered any inducement to change your statement?",
            "rationale": "Pre-empts the hostile-witness impeachment under BSA §155(3); get the answer on record first.",
        })

    suggested_talking_points = [
        f"Stay calm. Use the language you originally used in your 161 statement ({witness.language}).",
        f"If asked about {sections_str or 'the offence'}, answer only what you personally saw, not what others told you.",
        "If you don't remember a detail, say so. Never guess.",
        "Address the judge (or the PP) when answering, not the defense directly.",
    ]
    if witness.category == "Hostile":
        suggested_talking_points.append(
            "If you feel pressured or threatened mid-statement, request a brief recess to speak with the PP."
        )
    if witness.category == "Neutral":
        suggested_talking_points.append(
            "Confirm you have read your 161 statement recently so you can confirm or correct it on the stand."
        )

    # Record the prep request
    witness.prep_status = "prepped"
    witness.prep_notes = (witness.prep_notes or "") + f"\n--- v1 prep {int(datetime.now(tz=timezone.utc).timestamp())} ---\n" + \
        "\n".join([f"Q: {q['question']}" for q in likely_questions])
    witness.updated_at = int(datetime.now(tz=timezone.utc).timestamp())
    db.commit()
    record_audit(
        db, actor_id=actor.id, action="witness.prep",
        subject_type="witness", subject_id=str(witness.id),
        fields_used=["prep_status", "prep_notes"],
        detail={"case_id": case.case_id, "n_questions": len(likely_questions)},
    )
    log.info("witness.prep witness_id=%s case=%s n_questions=%s", witness.id, case.case_id, len(likely_questions))

    return WitnessPrepResponse(
        witness_id=witness.id,
        witness_name=witness.name,
        case_id=case.id,
        case_summary=f"{case.case_id} | {sections_str or case.offence}",
        likely_questions=likely_questions,
        suggested_talking_points=suggested_talking_points,
        prep_completed_at=int(datetime.now(tz=timezone.utc).timestamp()),
    )
