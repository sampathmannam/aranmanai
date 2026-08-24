"""FastAPI dependency-injection helpers: get current user, audit, etc."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from aranmanai.config import Settings, get_settings
from aranmanai.db import SessionLocal
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger
from aranmanai.security import verify_token

log = get_logger(__name__)


def get_db() -> Session:
    """FastAPI dependency: yield a session."""
    return SessionLocal()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Verify JWT and return the user. 401 if invalid/missing."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    claims = verify_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_role(*roles: UserRole):
    """Dependency factory: require the user to have one of the given roles."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role(s): {[r.value for r in roles]}",
            )
        return user
    return _dep


def get_settings_dep() -> Settings:
    """FastAPI dependency: return the Settings singleton."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SpUser = Annotated[User, Depends(require_role(UserRole.SP, UserRole.ADMIN))]
IoUser = Annotated[User, Depends(require_role(UserRole.IO, UserRole.SP, UserRole.ADMIN))]
PpUser = Annotated[User, Depends(require_role(UserRole.PP, UserRole.SP, UserRole.ADMIN))]
DspUser = Annotated[User, Depends(require_role(UserRole.DSP, UserRole.SP, UserRole.ADMIN))]
CourtConstableUser = Annotated[User, Depends(require_role(UserRole.COURT_CONSTABLE, UserRole.SP, UserRole.ADMIN))]
WomenPatrolUser = Annotated[User, Depends(require_role(UserRole.WOMEN_PATROL, UserRole.SP, UserRole.ADMIN))]
AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
