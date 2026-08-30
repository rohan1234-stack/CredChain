# ---------------------------------------------------------------------------
# PS3 Phase E: real pending-action counts, computed live from existing
# status columns — no new "unread" tracking table, no fabricated numbers.
# Each count is deliberately scoped to "this needs the viewer's action" (or,
# for the company count, "newly available and not yet verified") so it
# self-clears as a natural side effect of the user acting — approving,
# rejecting, verifying — rather than needing a separate "mark as read" step.
#
# The Notification center below (added later) answers a DIFFERENT question
# — "what new events do I have?" — backed by the real, per-recipient
# app/models/notification.py table. Both mechanisms are real and both stay;
# see each function's docstring for which question it answers.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from sqlalchemy import not_
from sqlalchemy.orm import Session

from ..models.company import Company
from ..models.credential_request import CredentialRequest
from ..models.enums import ApplicationStatus, CredentialRequestStatus, InstitutionRequestStatus, StudentDocumentStatus
from ..models.institution import Institution
from ..models.institution_certificate_request import InstitutionCertificateRequest
from ..models.job_application import JobApplication
from ..models.notification import Notification
from ..models.share_grant import ShareGrant, ShareGrantCredential
from ..models.student import Student
from ..models.student_document import StudentDocument
from ..models.user import User
from ..models.verification_event import VerificationEvent
from ..schemas.notifications import NotificationCounts
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def student_counts(db: Session, student: Student) -> NotificationCounts:
    pending = (
        db.query(CredentialRequest)
        .filter(CredentialRequest.student_id == student.id, CredentialRequest.status == CredentialRequestStatus.PENDING)
        .count()
    )
    return NotificationCounts(pending_company_requests=pending)


def institution_counts(db: Session, institution: Institution) -> NotificationCounts:
    pending_certs = (
        db.query(InstitutionCertificateRequest)
        .filter(
            InstitutionCertificateRequest.institution_id == institution.id,
            InstitutionCertificateRequest.status == InstitutionRequestStatus.PENDING,
        )
        .count()
    )
    pending_docs = (
        db.query(StudentDocument)
        .filter(
            StudentDocument.institution_id == institution.id,
            StudentDocument.status.in_([StudentDocumentStatus.UNVERIFIED, StudentDocumentStatus.UNDER_REVIEW]),
        )
        .count()
    )
    return NotificationCounts(pending_certificate_requests=pending_certs, pending_document_reviews=pending_docs)


def company_counts(db: Session, company: Company) -> NotificationCounts:
    now = datetime.now(timezone.utc)
    verified_credential_ids = db.query(VerificationEvent.credential_id).filter(VerificationEvent.company_id == company.id)
    unverified = (
        db.query(ShareGrantCredential.credential_id)
        .join(ShareGrant, ShareGrant.id == ShareGrantCredential.share_grant_id)
        .filter(
            ShareGrant.company_id == company.id,
            ShareGrant.revoked_at.is_(None),
            ShareGrant.expires_at > now,
            not_(ShareGrantCredential.credential_id.in_(verified_credential_ids)),
        )
        .distinct()
        .count()
    )
    new_applications = (
        db.query(JobApplication)
        .filter(JobApplication.company_id == company.id, JobApplication.status == ApplicationStatus.APPLIED)
        .count()
    )
    return NotificationCounts(unverified_shared_credentials=unverified, new_job_applications=new_applications)


# ---------------------------------------------------------------------------
# Notification center — "what new events do I have?" (as opposed to the
# pending-action counts above, which answer "what currently needs my
# action?"). Backed by the real, per-recipient app/models/notification.py
# table; see that model's docstring for why this is a separate table from
# ActivityLog rather than a column on it.
# ---------------------------------------------------------------------------


class NotificationNotFoundError(Exception):
    pass


class NotificationNotOwnedError(Exception):
    pass


def create_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    title: str,
    message: str,
    activity_log_id: uuid.UUID | None = None,
    link_entity_type: str | None = None,
    link_entity_id: uuid.UUID | None = None,
) -> Notification:
    """
    Called from the SAME domain-service call sites that already write the
    corresponding ActivityLog row (credential_service, sharing_service,
    job_application_service, admin_service, institution_request_service,
    student_document_service) — never from a separate background job,
    poller, or event detector. `user_id` must be the real recipient's own
    User.id, already known to the caller from the domain objects it's
    already holding (e.g. `credential.student.user_id`) — this function
    does not re-derive or re-authorize that decision; the caller's existing
    ownership/ authorization logic is the single source of truth for who
    the recipient is.

    title/message must only ever contain what the recipient is already
    entitled to see (names, titles, statuses) — never document contents,
    tokens, signatures, password hashes, or key material. Callers build
    these the same way activity_service.render_message already does: from
    live entity data, never by echoing raw request/DB internals.

    Does not commit — the caller commits once, in the same transaction as
    the ActivityLog row and the underlying state change, so a notification
    can never be created for a write that itself rolled back.
    """
    notification = Notification(
        user_id=user_id,
        activity_log_id=activity_log_id,
        title=title,
        message=message,
        link_entity_type=link_entity_type,
        link_entity_id=link_entity_id,
    )
    db.add(notification)
    return notification


def list_notifications_for_user(
    db: Session, user: User, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[list[Notification], int]:
    """Newest first, backend-paginated — same (rows, total) contract as every other paginated listing in this app."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    query = db.query(Notification).filter(Notification.user_id == user.id)
    total = query.count()
    rows = query.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def count_unread_notifications(db: Session, user: User) -> int:
    """Backed by the partial index on (user_id) WHERE is_read = false — cheap regardless of read-history size."""
    return db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read.is_(False)).count()


def mark_notification_read(db: Session, user: User, notification_id: uuid.UUID) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise NotificationNotFoundError()
    if notification.user_id != user.id:
        raise NotificationNotOwnedError()

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.add(notification)
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_notifications_read(db: Session, user: User) -> int:
    """Updates only this user's own unread notifications — scoped by user_id, never touches anyone else's. Returns the number of rows actually changed."""
    now = datetime.now(timezone.utc)
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": now}, synchronize_session=False)
    )
    db.commit()
    return updated
