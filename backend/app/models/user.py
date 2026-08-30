from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .common import TimestampMixin, UUIDPrimaryKeyMixin
from .enums import UserRole

if TYPE_CHECKING:
    from .activity_log import ActivityLog
    from .company import Company
    from .institution import Institution
    from .student import Student


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Login identity shared by all three roles. The role-specific profile
    (Student / Institution / Company) is a separate 1:1 table so role-specific
    fields don't pollute this table and a user is unambiguously exactly one
    role in practice, even though nothing here hard-enforces that pairing —
    the auth service (Phase 3) is responsible for creating the matching
    profile row at registration time.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=lambda e: [m.value for m in e], name="user_role"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    student: Mapped[Student | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    # Phase A added a second FK from institutions/companies to users (verified_by, the admin who
    # reviewed the account) alongside the existing user_id (the registered account's own login).
    # With two FK paths between the same table pair, SQLAlchemy can no longer infer which column
    # this relationship should join on and raises AmbiguousForeignKeysError at mapper-configure
    # time unless told explicitly — foreign_keys here is scoped to user_id only; verified_by is
    # never navigated as a relationship anywhere (admin_service.py only ever assigns the raw
    # UUID), so it needs no relationship object of its own.
    institution: Mapped[Institution | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", foreign_keys="Institution.user_id"
    )
    company: Mapped[Company | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", foreign_keys="Company.user_id"
    )
    activity_logs: Mapped[list[ActivityLog]] = relationship(
        back_populates="actor_user", foreign_keys="ActivityLog.actor_user_id"
    )
