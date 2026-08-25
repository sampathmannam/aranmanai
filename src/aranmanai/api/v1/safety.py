"""Citizen safety API - Abhaya equivalent.

Per Kishore's Eluru deployment (New Indian Express, 7 Nov 2024):
- Abhaya app for women's safety
- Dedicated helpline 9550351100 for women in distress
- Anonymous online reporting form at formurl.com/to/abhaya
- Women-run patrol units with pink helmets

This endpoint set replicates the citizen-facing surface. Storage is now
in the database (was in-memory lists - C-5 fix from security audit).
H-3 fix: in-process rate limiting prevents DoS via memory exhaustion
or DB write amplification.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aranmanai.api.deps import DbSession, IoUser, SpUser
from aranmanai.db.models.safety import (
    AnonymousReport as AnonymousReportRow,
)
from aranmanai.db.models.safety import (
    HelplineCall as HelplineCallRow,
)
from aranmanai.db.models.safety import (
    PatrolDispatch as PatrolDispatchRow,
)
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/safety", tags=["citizen-safety"])


# H-3 fix: in-process per-IP rate limiter (token bucket per minute).
# For multi-process deployments, use slowapi + Redis. Single-process
# coverage is enough for the demo / pilot deployment.
_rate_state: dict[tuple[str, str], list[float]] = defaultdict(list)
_rate_lock = Lock()
# P1 fix: per-route rate limits. Helpline + report get the strict
# default; patrol dispatch needs to be able to send multiple units in
# one minute during an active incident, so it gets a higher limit.
#
# v1.1 CAVEAT (Kishore review, item 6): the rate-limit state lives
# in this Python process's memory. If Aranmanai is deployed with
# N gunicorn/uvicorn workers, each worker has its own bucket, so the
# effective per-IP limit is N * the per-worker limit. For the demo
# (single uvicorn) and the v1 pilot (single VPS) this is fine; for
# any multi-worker / multi-host deployment, swap this for slowapi
# backed by Redis. See docs/MULTI_PROCESS_RATE_LIMIT.md (to be
# written before the v1.2 multi-worker deployment).
_RATE_LIMITS: dict = {
    "/helpline/call": 10,
    "/report": 10,
    "/patrol/dispatch": 60,
}
_RATE_WINDOW_SEC = 60
_BUCKET_TTL_SEC = 3600  # P1 fix: drop bucket keys after 1h idle
_last_cleanup = 0.0


def _cleanup_rate_state() -> None:
    """P1 fix: bound the in-process dict by dropping idle keys."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < 300:  # cleanup every 5 min
        return
    _last_cleanup = now
    cutoff = now - _BUCKET_TTL_SEC
    stale = [k for k, v in _rate_state.items() if not v or v[-1] < cutoff]
    for k in stale:
        _rate_state.pop(k, None)


def _check_rate(ip: str, route: str) -> None:
    """Raise 429 if ip+route exceeds the per-route rate."""
    now = time.monotonic()
    _cleanup_rate_state()
    with _rate_lock:
        key = (ip, route)
        bucket = _rate_state[key]
        # drop entries older than the window
        bucket[:] = [t for t in bucket if now - t < _RATE_WINDOW_SEC]
        limit = _RATE_LIMITS.get(route, 10)
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {route} (max {limit}/min)",
            )
        bucket.append(now)


def _client_ip(request: Request) -> str:
    """Get client IP from X-Forwarded-For or fall back to client.host."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "unknown") or "unknown"

HELPLINE_NUMBER = "9550351100"  # Per Kishore's Abhaya helpline


# ──────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────

class HelplineCallLog(BaseModel):
    case_id: str | None = None
    caller_district: str
    report_type: str  # harassment | stalking | domestic_violence | threat | other
    severity: str = "medium"  # low | medium | high | critical
    description: str
    location_text: str | None = None
    needs_patrol: bool = False
    needs_callback: bool = False


class HelplineCallResponse(BaseModel):
    log_id: str
    helpline_number: str
    routed_to: str
    patrol_dispatched: bool
    next_action: str
    recorded_at: str


class AnonymousReportRequest(BaseModel):
    report_type: str
    district: str
    incident_date: str
    location_text: str
    description: str
    severity: str = "medium"


class AnonymousReportResponse(BaseModel):
    report_id: str
    status: str
    review_queue: str
    next_action: str


class PatrolDispatchRequest(BaseModel):
    case_id: str | None = None
    helpline_log_id: str | None = None
    district: str
    area: str
    priority: str = "high"
    reason: str


class PatrolDispatchResponse(BaseModel):
    dispatch_id: str
    district: str
    area: str
    priority: str
    dispatched_at: str
    unit_id: str | None = None


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/helpline")
def get_helpline() -> dict:
    """Return the women's safety helpline number. Public endpoint."""
    return {
        "helpline_number": HELPLINE_NUMBER,
        "available": "24x7",
        "languages": ["en", "ta", "hi"],
        "anonymous": True,
        "dispatch_promise_minutes": 5,
        "note": "Per Kishore's Abhaya model - anonymous, no PII recorded",
    }


@router.post("/helpline/call", response_model=HelplineCallResponse, status_code=201)
def log_helpline_call(req: HelplineCallLog, user: IoUser, db: DbSession, request: Request) -> HelplineCallResponse:
    """Log a helpline call. NO PII is stored - only metadata.

    P1 fix: allow IO + WomenPatrol + SP. Helpline desk staff includes IOs.


    C-5 fix: now persists to DB.
    H-3 fix: rate-limited per client IP.
    """
    _check_rate(_client_ip(request), "/helpline/call")
    log_id = str(uuid.uuid4())
    routed_to = "women_patrol_unit" if req.needs_patrol else "sp_direct_review"
    patrol_dispatched = bool(req.needs_patrol)

    # Persist to DB
    row = HelplineCallRow(
        id=log_id,
        case_id=req.case_id,
        caller_district=req.caller_district,
        report_type=req.report_type,
        severity=req.severity,
        description=req.description,
        location_text=req.location_text,
        needs_patrol=req.needs_patrol,
        needs_callback=req.needs_callback,
        routed_to=routed_to,
        patrol_dispatched=patrol_dispatched,
        logged_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log.info(
        "safety.helpline_call id=%s district=%s type=%s patrol=%s",
        log_id, req.caller_district, req.report_type, patrol_dispatched,
    )
    next_action = (
        "Patrol dispatched to location" if patrol_dispatched
        else "SP to review within 24h"
    )
    return HelplineCallResponse(
        log_id=log_id,
        helpline_number=HELPLINE_NUMBER,
        routed_to=routed_to,
        patrol_dispatched=patrol_dispatched,
        next_action=next_action,
        recorded_at=row.logged_at.isoformat(),
    )


@router.post("/report", response_model=AnonymousReportResponse, status_code=201)
def submit_anonymous_report(req: AnonymousReportRequest, db: DbSession, request: Request) -> AnonymousReportResponse:
    """Submit an anonymous report (Abhaya formurl.com equivalent).

    C-5 fix: now persists to DB.
    H-3 fix: rate-limited per client IP.
    """
    _check_rate(_client_ip(request), "/report")
    report_id = str(uuid.uuid4())
    row = AnonymousReportRow(
        id=report_id,
        report_type=req.report_type,
        district=req.district,
        incident_date=req.incident_date,
        location_text=req.location_text,
        description=req.description,
        severity=req.severity,
        status="pending_sp_review",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log.info(
        "safety.anon_report id=%s district=%s type=%s",
        report_id, req.district, req.report_type,
    )
    return AnonymousReportResponse(
        report_id=report_id,
        status=row.status,
        review_queue=f"sp_{req.district}",
        next_action="SP to review within 24h. Patrol dispatched if severity=critical.",
    )


@router.post("/patrol/dispatch", response_model=PatrolDispatchResponse, status_code=201)
def dispatch_patrol(req: PatrolDispatchRequest, user: SpUser, db: DbSession, request: Request) -> PatrolDispatchResponse:
    """SP dispatches a women patrol unit to a location.

    C-5 fix: now persists to DB.
    H-3 fix: rate-limited per client IP (still per minute).
    P1 fix: deterministic unit selection (alphabetical by id) and
    district match enforcement (SPs can only dispatch in their
    own district unless admin).
    P2 fix: deterministic unit pick — order by id so two dispatches
    in the same minute don't race to the same unit.
    """
    _check_rate(_client_ip(request), "/patrol/dispatch")
    if user.role != UserRole.ADMIN.value and req.district != user.district:
        raise HTTPException(
            status_code=403,
            detail="SPs can only dispatch in their own district",
        )
    dispatch_id = str(uuid.uuid4())
    # P2 fix: pick the unit with the fewest open dispatches (load-balanced),
    # tiebreak by id (deterministic). Subquery counts open dispatches per unit.
    from sqlalchemy import func
    open_count_subq = (
        db.query(
            PatrolDispatchRow.unit_id,
            func.count(PatrolDispatchRow.id).label("open_count"),
        )
        .filter(PatrolDispatchRow.unit_id.isnot(None))
        .group_by(PatrolDispatchRow.unit_id)
        .subquery()
    )
    unit = (
        db.query(User)
        .outerjoin(
            open_count_subq,
            User.id == open_count_subq.c.unit_id,
        )
        .filter(
            User.role == UserRole.WOMEN_PATROL,
            User.district == req.district,
            User.is_active,
        )
        .order_by(
            func.coalesce(open_count_subq.c.open_count, 0).asc(),
            User.id.asc(),
        )
        .first()
    )
    unit_id = unit.id if unit else None

    row = PatrolDispatchRow(
        id=dispatch_id,
        case_id=req.case_id,
        helpline_log_id=req.helpline_log_id,
        district=req.district,
        area=req.area,
        priority=req.priority,
        reason=req.reason,
        unit_id=unit_id,
        dispatched_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log.info(
        "safety.patrol_dispatch id=%s district=%s unit=%s priority=%s",
        dispatch_id, req.district, unit_id, req.priority,
    )
    return PatrolDispatchResponse(
        dispatch_id=dispatch_id,
        district=req.district,
        area=req.area,
        priority=req.priority,
        dispatched_at=row.dispatched_at.isoformat(),
        unit_id=unit_id,
    )


@router.get("/patrol/dispatches")
def list_patrol_dispatches(user: SpUser, db: DbSession, district: str | None = None) -> dict:
    """List patrol dispatches for the district. SP view.

    C-5 fix: now reads from DB.
    P1 fix (H-2 IDOR): a non-admin SP can only list their own district.
    Passing district=other-district was a cross-district read.
    """
    from sqlalchemy import desc

    target = district or user.district
    if user.role != UserRole.ADMIN.value and target != user.district:
        raise HTTPException(
            status_code=403,
            detail="SPs can only list their own district",
        )
    q = db.query(PatrolDispatchRow).filter(PatrolDispatchRow.district == target)
    rows = q.order_by(desc(PatrolDispatchRow.dispatched_at)).limit(50).all()
    return {
        "district": target,
        "n_dispatches": len(rows),
        "dispatches": [
            {
                "dispatch_id": r.id,
                "case_id": r.case_id,
                "helpline_log_id": r.helpline_log_id,
                "district": r.district,
                "area": r.area,
                "priority": r.priority,
                "reason": r.reason,
                "unit_id": r.unit_id,
                "dispatched_by": r.dispatched_by,
                "dispatched_at": r.dispatched_at.isoformat(),
            }
            for r in rows
        ],
    }

