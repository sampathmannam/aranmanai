"""User CRUD (admin-only for create/update/delete; self-read for /me)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.aranmanai.db import get_db
from src.aranmanai.logging_config import get_logger
from src.aranmanai.models import User
from src.aranmanai.schemas import UserCreate, UserRead
from src.aranmanai.security import get_current_user, hash_password, record_audit, require_roles

log = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("Admin", "SP")),
) -> User:
    """Admin or SP creates a new user (IO, PP, or another Admin)."""
    existing = db.query(User).filter(User.name == body.name).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with name '{body.name}' already exists",
        )
    user = User(
        name=body.name,
        role=body.role,
        district=body.district,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"DB integrity error: {e}"
        ) from e
    db.refresh(user)
    record_audit(
        db, actor_id=_admin.id, action="user.create",
        subject_type="user", subject_id=str(user.id),
        fields_used=["name", "role", "district"],
    )
    log.info("user.created user_id=%s role=%s by_admin=%s", user.id, user.role, _admin.id)
    return user


@router.get("", response_model=list[UserRead])
def list_users(
    district: str | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
    _actor: User = Depends(get_current_user),
) -> list[User]:
    """List users. Filter by district + role. SP sees own district; Admin sees all."""
    q = db.query(User)
    if district is not None:
        q = q.filter(User.district == district)
    if role is not None:
        q = q.filter(User.role == role)
    # SP is scoped to own district unless Admin
    if _actor.role == "SP":
        q = q.filter(User.district == _actor.district)
    return q.order_by(User.district, User.role, User.name).all()


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _actor: User = Depends(get_current_user),
) -> User:
    """Get one user. SP can only see users in own district."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if _actor.role == "SP" and user.district != _actor.district:
        raise HTTPException(status_code=403, detail="Cross-district read not allowed")
    return user
