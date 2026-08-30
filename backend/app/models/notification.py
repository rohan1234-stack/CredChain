from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .common import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from .activity_log import ActivityLog
    from .user import User


class Notification(UUIDPrimaryKeyMixin, Base):
    """
    Per-recipient notification state — deliberately a SEPARATE table from
    ActivityLog, not a read/unread column bolted onto it. ActivityLog stays
    the shared, append-only audit trail (one row per event, no per-viewer
    state, no update path); a Notification row is one recipient's personal
    copy of "this event is relevant to you," which is the only place
    read/unread can correctly live, since a single event can be relevant to
    several different users, each with their own independent read state.

    activity_log_id is nullable with SET NULL: a Notification must survive
    even if the ActivityLog row it was generated from is (hypothetically)
    ever removed — the notification's own title/message are a self-contained
    snapshot at creation time, not a live join back to ActivityLog.

    link_entity_type/link_entity_id mirror ActivityLog's own generic,
    non-FK-constrained entity reference (same rationale: a notification can
    point at a credential, a job application, an institution, etc. — one
    column pair can't be a real FK to multiple tables). Never store a raw
    URL here — the frontend maps (link_entity_type, link_entity_id) to a
    real, existing route; this table only ever holds safe identifiers.

    Only ever holds display-safe text — never document contents, tokens,
    signatures, password hashes, or key material (see notification_service.
    create_notification's docstring for the same rule stated at the write
    boundary).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # The two access patterns this table actually serves: "my notifications, newest
        # first" (paginated list, ORDER BY created_at DESC) and "how many of mine are
        # unread" (badge count). The second is a partial index — only unread rows are
        # ever indexed there — so that count stays cheap no matter how large a user's
        # read history grows.
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", postgresql_where=text("is_read = false")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_log_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activity_logs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)

    link_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    link_entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship()
    activity_log: Mapped[ActivityLog | None] = relationship()
