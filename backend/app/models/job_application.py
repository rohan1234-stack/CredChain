from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .common import TimestampMixin, UUIDPrimaryKeyMixin
from .enums import ApplicationStatus

if TYPE_CHECKING:
    from .company import Company
    from .credential_request import CredentialRequest
    from .job import Job
    from .student import Student


class JobApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Tracks only the application's own lifecycle (status). The actual
    credential sharing/verification for an application is NOT owned here —
    applying creates a real CredentialRequest (company asking for
    job.required_documents) and immediately approves it via the existing
    sharing_service.approve_request, exactly as if the company had sent
    that request directly. credential_request_id just points at that row so
    the company dashboard can show requested-vs-shared and drive Verify
    through the existing, unmodified verification pipeline. No second
    sharing or verification system.
    """

    __tablename__ = "job_applications"
    __table_args__ = (
        Index("ix_job_applications_student_status", "student_id", "status"),
        Index("ix_job_applications_company_status", "company_id", "status"),
        # Application-layer duplicate check (apply_to_job) already rejects a second
        # application before this is ever reached in normal sequential use — this is
        # the final concurrency safety boundary for two requests racing each other.
        UniqueConstraint("job_id", "student_id", name="uq_job_applications_job_id_student_id"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized, mirroring Credential's existing student_id+institution_id
    # pattern — lets the company-scoped ownership query filter directly
    # without joining through Job every time.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, values_callable=lambda e: [m.value for m in e], name="application_status"),
        nullable=False,
        default=ApplicationStatus.APPLIED,
        index=True,
    )

    credential_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("credential_requests.id", ondelete="SET NULL"), nullable=True
    )

    # Only ever set when status is transitioned to REJECTED — a real,
    # company-supplied reason, never fabricated by the frontend. Shown to
    # the student on their own application.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship()
    job: Mapped[Job] = relationship(back_populates="applications")
    company: Mapped[Company] = relationship(back_populates="job_applications")
    credential_request: Mapped[CredentialRequest | None] = relationship()
