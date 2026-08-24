"""User model. SP, IO, PP, Admin."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aranmanai.db.session import Base

if TYPE_CHECKING:
    from aranmanai.db.models.case import Case


class UserRole(str, enum.Enum):
    SP = "sp"          # Superintendent of Police
    IO = "io"          # Investigating Officer
    PP = "pp"          # Public Prosecutor
    ADMIN = "admin"
    AUDITOR = "auditor"


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Encrypted PII
    name_encrypted: Mapped[str] = mapped_column(String(256), nullable=False)
    email_encrypted: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone_encrypted: Mapped[str | None] = mapped_column(String(32), nullable=True)

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), default=UserRole.IO, nullable=False, index=True
    )
    district: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    cases_as_io: Mapped[list["Case"]] = relationship(
        "Case", foreign_keys="Case.io_id", back_populates="io"
    )
    cases_as_pp: Mapped[list["Case"]] = relationship(
        "Case", foreign_keys="Case.pp_id", back_populates="pp"
    )

    def __repr__(self) -> str:
        return f"<User {self.username} role={self.role.value}>"
