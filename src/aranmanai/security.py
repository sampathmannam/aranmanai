"""Security: auth (bcrypt + JWT), audit log with hash chain, DPDP helpers.

Single import surface for the API layer. Every endpoint that
mutates state MUST call `record_audit()` so the hash chain stays intact.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from src.aranmanai.config import settings
from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import AuditLog, User

log = get_logger(__name__)

# OAuth2 password flow — token URL is /auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=True)

# --- Password hashing ---

def hash_password(plain: str) -> str:
    """Bcrypt hash. Settings.bcrypt_rounds controls cost (default 12)."""
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt check."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- JWT ---

def create_access_token(user_id: int, role: str, district: str) -> tuple[str, int]:
    """Issue JWT. Returns (token, expires_in_minutes)."""
    expires_minutes = settings.jwt_access_ttl_minutes
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "district": district,
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(tz=timezone.utc).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_minutes


def decode_token(token: str) -> dict:
    """Decode and validate JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# --- Auth dependency ---

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: extract user from JWT, return User or 401."""
    payload = decode_token(token)
    user_id = int(payload["sub"])
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str):
    """Dependency factory: enforce user.role is in the given set."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not in required {list(roles)}",
            )
        return user
    return _dep


# --- Audit log (hash-chained, DPDP §8(3) compliant) ---

def _hash_entry(prev_hash: str, action: str, subject_type: str, subject_id: str | None,
                actor_id: int | None, success: bool, timestamp: int,
                fields_used: list[str], detail: dict | None) -> str:
    """Compute SHA-256 of a canonical audit entry."""
    payload = json.dumps({
        "prev_hash": prev_hash,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id or "",
        "actor_id": actor_id or 0,
        "success": success,
        "timestamp": timestamp,
        "fields_used": sorted(fields_used),
        "detail": detail or {},
    }, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _latest_hash(db: Session) -> str:
    """Get the most recent audit hash (or genesis if empty)."""
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    return last.hash if last else "0" * 64  # Genesis hash: 64 zeros


def record_audit(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    subject_type: str,
    subject_id: str | None = None,
    fields_used: list[str] | None = None,
    success: bool = True,
    detail: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    """Append a hash-chained audit entry. DPDP §8(3) fields included.

    Call this on every state mutation. The hash chain is verified
    periodically by `verify_audit_chain()`.
    """
    fields = fields_used or []
    ts = int(datetime.now(tz=timezone.utc).timestamp())
    prev = _latest_hash(db)
    h = _hash_entry(prev, action, subject_type, subject_id, actor_id, success, ts, fields, detail)
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        fields_used=fields,
        success=success,
        timestamp=ts,
        prev_hash=prev,
        hash=h,
        detail=detail,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def verify_audit_chain(db: Session) -> tuple[bool, int]:
    """Walk the audit log and verify each entry's hash matches prev_hash + content.

    Returns (is_valid, entries_checked). Used by ops + the /health endpoint.
    """
    prev = "0" * 64
    count = 0
    for entry in db.query(AuditLog).order_by(AuditLog.id.asc()).all():
        expected = _hash_entry(
            prev, entry.action, entry.subject_type, entry.subject_id,
            entry.actor_id, entry.success, entry.timestamp, entry.fields_used, entry.detail,
        )
        if entry.prev_hash != prev or entry.hash != expected:
            log.error("audit chain broken at id=%s", entry.id)
            return False, count
        prev = entry.hash
        count += 1
    return True, count
