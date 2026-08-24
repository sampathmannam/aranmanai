"""Auth routes: login, refresh, me."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aranmanai.api.deps import CurrentUser, DbSession
from aranmanai.db.models.user import User, UserRole
from aranmanai.observability import get_logger
from aranmanai.security import AuditAction, AuditLog, generate_token, hash_password, verify_password
from aranmanai.config import get_settings

log = get_logger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    district: str
    username: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    role: UserRole
    district: str
    email: str | None = None
    phone: str | None = None


def _audit() -> AuditLog:
    settings = get_settings()
    return AuditLog(settings.audit_log_path)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: DbSession) -> TokenResponse:
    settings = get_settings()
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.is_active or not verify_password(req.password, user.hashed_password):
        _audit().append(
            AuditAction.LOGIN_FAILED,
            actor_id=req.username,
            subject_id=req.username,
            success=False,
            error="invalid credentials",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user.last_login = __import__("datetime").datetime.utcnow()
    db.commit()
    token = generate_token(user.id, {"role": user.role.value, "district": user.district})
    _audit().append(
        AuditAction.LOGIN,
        actor_id=user.id,
        subject_id=user.id,
        success=True,
    )
    log.info("auth.login", user_id=user.id[:8], role=user.role.value)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        district=user.district,
        username=user.username,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: DbSession) -> TokenResponse:
    """Register a new user. Only admins can register; for v1, the first
    user (bootstrapped via init script) is the SP/Admin who then creates
    others.
    """
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    from aranmanai.security import encrypt_field
    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        name_encrypted=encrypt_field(req.name),
        email_encrypted=encrypt_field(req.email) if req.email else None,
        phone_encrypted=encrypt_field(req.phone) if req.phone else None,
        role=req.role,
        district=req.district,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = generate_token(user.id, {"role": user.role.value, "district": user.district})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        district=user.district,
        username=user.username,
    )


@router.get("/me")
def me(user: CurrentUser, db: DbSession) -> dict:
    from aranmanai.security import decrypt_field
    return {
        "user_id": user.id,
        "username": user.username,
        "name": decrypt_field(user.name_encrypted),
        "role": user.role.value,
        "district": user.district,
        "is_active": user.is_active,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }
