from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .common import TimestampMixin, UUIDPrimaryKeyMixin
from .enums import VerificationStatus

if TYPE_CHECKING:
    from .credential_request import CredentialRequest
    from .job import Job
    from .job_application import JobApplication
    from .share_grant import ShareGrant
    from .user import User
    from .verification_event import VerificationEvent


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    The "verifier" role's profile — named Company to match the DB entity list; the frontend/API role value stays 'verifier'.

    user_id is nullable: a row with user_id=None is a directory-only listing
    (seeded from a curated public dataset, see scripts/seed_directory.py) —
    discoverable by a student, but with no CredChain login and therefore
    never able to post jobs or receive applications itself (posting a job
    requires require_verifier, which requires a real logged-in user). A real
    company that registers keeps (or gains) a non-null user_id exactly as
    before; nothing about the existing login-linked path changes.
    """

    __tablename__ = "companies"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # PS3 job-marketplace phase: real company profile fields, all optional —
    # a company that hasn't filled these in yet is still a real company row,
    # never replaced with fabricated placeholder text anywhere in the UI.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Structured location (Phase 2) — see Institution's identical fields for the full rationale.
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Phase A: trust/verification (registered accounts only — see VerificationStatus) ---
    # Same rationale as Institution's identical fields — a directory-only row (user_id IS NULL)
    # carries the 'pending' default too, but it's never surfaced or meaningful for one.
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, values_callable=lambda e: [m.value for m in e], name="verification_status"),
        nullable=False,
        default=VerificationStatus.PENDING,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User | None] = relationship(back_populates="company", foreign_keys=[user_id])
    credential_requests: Mapped[list[CredentialRequest]] = relationship(back_populates="company")
    share_grants: Mapped[list[ShareGrant]] = relationship(back_populates="company")
    verification_events: Mapped[list[VerificationEvent]] = relationship(back_populates="company")
    jobs: Mapped[list[Job]] = relationship(back_populates="company")
    job_applications: Mapped[list[JobApplication]] = relationship(back_populates="company")
