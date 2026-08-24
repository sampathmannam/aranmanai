"""Authentication endpoints: login, whoami.

JWT bearer token. v1 keeps it minimal — username + password. No
password reset flow, no email verification, no 2FA. v2 if needed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import User
from src.aranmanai.schemas import LoginRequest, TokenResponse, UserRead
from src.aranmanai.security import (
    create_access_token,
    get_current_user,
    verify_password,
)

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Verify username + password, return JWT.

    Username is the user's name (display name) for v1. v2 will add
    proper username + email + mobile fields.
    """
    user = db.query(User).filter(User.name == body.username, User.is_active == True).first()
    if not user or not verify_password(body.password, user.password_hash):
        log.warning("auth.login.failed username=%s", body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token, ttl = create_access_token(user.id, user.role, user.district)
    log.info("auth.login.ok user_id=%s role=%s", user.id, user.role)
    return TokenResponse(access_token=token, expires_in_minutes=ttl)


@router.get("/me", response_model=UserRead)
def whoami(current: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current
