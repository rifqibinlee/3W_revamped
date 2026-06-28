import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    PLANNER = "planner"
    STAFF = "staff"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Plain VARCHAR rather than a native DB enum: Role already subclasses
    # str, so comparisons/serialization work transparently, and this avoids
    # cross-dialect enum-type quirks (Postgres native enums vs SQLite).
    role: Mapped[str] = mapped_column(String(20), default=Role.STAFF.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    login_history: Mapped[list["LoginHistory"]] = relationship(back_populates="user")


class LoginHistory(Base):
    __tablename__ = "login_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logged_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="login_history")
