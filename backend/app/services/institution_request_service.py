# ---------------------------------------------------------------------------
# PS3 Phase C: student -> institution certificate requests. The reverse
# direction of sharing_service's company -> student CredentialRequest — kept
# fully separate (see app/models/institution_certificate_request.py for why).
#
# Fulfillment is deliberately NOT wired here: a request becomes FULFILLED
# only from credential_service, at the moment an institution actually issues
# the credential that satisfies it (see institution_request_service.mark_fulfilled,
# called from routes/institutions.py's issue_credential route when a
# fulfills_request_id is passed). Approving a request never issues anything.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.enums import InstitutionRequestStatus
from ..models.institution import Institution
from ..models.institution_certificate_request import InstitutionCertificateRequest
from ..models.student import Student
from ..schemas.institution_request import InstitutionCertificateRequestResponse
from . import notification_service


class NotAffiliatedError(Exception):
    """Raised when a student tries to request from an institution they are not actually linked to."""

    pass


class RequestNotFoundError(Exception):
    pass


class RequestNotOwnedError(Exception):
    pass


class RequestAlreadyProcessedError(Exception):
    pass


def create_request(
    db: Session,
    student: Student,
    *,
    institution_id: uuid.UUID,
    credential_type,
    custom_credential_name: str | None,
    reason: str | None,
) -> InstitutionCertificateRequest:
    # The real, already-validated university<->student relationship is the
    # only legitimate source of "which institution" — never trust a
    # client-supplied institution_id that doesn't match the student's own.
    if student.institution_id is None or student.institution_id != institution_id:
        raise NotAffiliatedError()

    request = InstitutionCertificateRequest(
        student_id=student.id,
        institution_id=institution_id,
        credential_type=credential_type,
        custom_credential_name=custom_credential_name,
        reason=reason,
        status=InstitutionRequestStatus.PENDING,
    )
    db.add(request)
    db.flush()

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="CERTIFICATE_REQUEST_CREATED",
        entity_type="institution_certificate_request",
        entity_id=request.id,
        metadata_={"institution_id": str(institution_id)},
    )
    db.add(log)
    db.flush()

    institution = db.get(Institution, institution_id)
    # A directory-only institution (never registered) has no logged-in user to notify —
    # the request itself is still real and visible in the student's own activity feed.
    if institution is not None and institution.user_id is not None:
        label = custom_credential_name or credential_type.value.replace("_", " ").title()
        notification_service.create_notification(
            db,
            user_id=institution.user_id,
            title="New certificate request",
            message=f"{student.user.full_name} requested {label}",
            activity_log_id=log.id,
            link_entity_type="institution_certificate_request",
            link_entity_id=request.id,
        )

    db.commit()
    db.refresh(request)
    return request


def create_request_batch(
    db: Session,
    student: Student,
    *,
    institution_id: uuid.UUID,
    items: list[tuple],
    reason: str | None,
) -> list[InstitutionCertificateRequest]:
    """
    Creates several InstitutionCertificateRequest rows in one submission —
    e.g. Transcript + Degree + Migration Certificate at once — sharing a
    single new batch_id so the institution and student both see them as one
    request with several items. Each row's own PENDING/APPROVED/REJECTED/
    FULFILLED lifecycle is completely independent from here on: approving,
    rejecting, and fulfilling still go through the existing single-item
    functions below, unchanged. `items` is a list of
    (credential_type, custom_credential_name) tuples.
    """
    if student.institution_id is None or student.institution_id != institution_id:
        raise NotAffiliatedError()

    batch_id = uuid.uuid4()
    requests = [
        InstitutionCertificateRequest(
            student_id=student.id,
            institution_id=institution_id,
            batch_id=batch_id,
            credential_type=credential_type,
            custom_credential_name=custom_credential_name,
            reason=reason,
            status=InstitutionRequestStatus.PENDING,
        )
        for credential_type, custom_credential_name in items
    ]
    db.add_all(requests)
    db.flush()

    # One ActivityLog + one Notification for the WHOLE batch (linked to the first row), not one
    # per item — same "bundle, don't spam" precedent as CREDENTIAL_SHARED bundling several
    # credentials under one ShareGrant-level event (see sharing_service._create_share_grant).
    log = ActivityLog(
        actor_user_id=student.user_id,
        action="CERTIFICATE_REQUEST_CREATED",
        entity_type="institution_certificate_request",
        entity_id=requests[0].id,
        metadata_={"institution_id": str(institution_id), "batch_id": str(batch_id), "count": len(requests)},
    )
    db.add(log)
    db.flush()

    institution = db.get(Institution, institution_id)
    if institution is not None and institution.user_id is not None:
        if len(requests) == 1:
            label = requests[0].custom_credential_name or requests[0].credential_type.value.replace("_", " ").title()
            message = f"{student.user.full_name} requested {label}"
        else:
            message = f"{student.user.full_name} requested {len(requests)} certificates"
        notification_service.create_notification(
            db,
            user_id=institution.user_id,
            title="New certificate request",
            message=message,
            activity_log_id=log.id,
            link_entity_type="institution_certificate_request",
            link_entity_id=requests[0].id,
        )

    db.commit()
    for request in requests:
        db.refresh(request)
    return requests


def list_for_student(db: Session, student: Student) -> list[InstitutionCertificateRequest]:
    return (
        db.query(InstitutionCertificateRequest)
        .filter(InstitutionCertificateRequest.student_id == student.id)
        .order_by(InstitutionCertificateRequest.created_at.desc())
        .all()
    )


def list_for_institution(db: Session, institution: Institution) -> list[InstitutionCertificateRequest]:
    return (
        db.query(InstitutionCertificateRequest)
        .filter(InstitutionCertificateRequest.institution_id == institution.id)
        .order_by(InstitutionCertificateRequest.created_at.desc())
        .all()
    )


def _get_owned_pending_request(db: Session, institution: Institution, request_id: uuid.UUID) -> InstitutionCertificateRequest:
    request = db.get(InstitutionCertificateRequest, request_id)
    if request is None:
        raise RequestNotFoundError()
    if request.institution_id != institution.id:
        raise RequestNotOwnedError()
    if request.status != InstitutionRequestStatus.PENDING:
        raise RequestAlreadyProcessedError()
    return request


def approve_request(db: Session, institution: Institution, request_id: uuid.UUID) -> InstitutionCertificateRequest:
    request = _get_owned_pending_request(db, institution, request_id)
    request.status = InstitutionRequestStatus.APPROVED
    request.responded_at = datetime.now(timezone.utc)
    db.add(request)

    log = ActivityLog(
        actor_user_id=institution.user_id,
        action="CERTIFICATE_REQUEST_APPROVED",
        entity_type="institution_certificate_request",
        entity_id=request.id,
    )
    db.add(log)
    db.flush()

    label = request.custom_credential_name or request.credential_type.value.replace("_", " ").title()
    notification_service.create_notification(
        db,
        user_id=request.student.user_id,
        title="Certificate request approved",
        message=f"{institution.name} approved your {label} request",
        activity_log_id=log.id,
        link_entity_type="institution_certificate_request",
        link_entity_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return request


def reject_request(db: Session, institution: Institution, request_id: uuid.UUID, reason: str) -> InstitutionCertificateRequest:
    request = _get_owned_pending_request(db, institution, request_id)
    request.status = InstitutionRequestStatus.REJECTED
    request.rejection_reason = reason
    request.responded_at = datetime.now(timezone.utc)
    db.add(request)

    log = ActivityLog(
        actor_user_id=institution.user_id,
        action="CERTIFICATE_REQUEST_REJECTED",
        entity_type="institution_certificate_request",
        entity_id=request.id,
        metadata_={"reason": reason},
    )
    db.add(log)
    db.flush()

    label = request.custom_credential_name or request.credential_type.value.replace("_", " ").title()
    notification_service.create_notification(
        db,
        user_id=request.student.user_id,
        title="Certificate request rejected",
        message=f"{institution.name} rejected your {label} request",
        activity_log_id=log.id,
        link_entity_type="institution_certificate_request",
        link_entity_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return request


def get_approved_request_for_fulfillment(
    db: Session, institution: Institution, student_id: uuid.UUID, request_id: uuid.UUID
) -> InstitutionCertificateRequest:
    """
    Looked up by credential_service when issuing a credential with a
    fulfills_request_id — validates the request is this institution's own,
    targets the same student the credential is being issued to, and is
    APPROVED (not still pending, not already fulfilled/rejected).
    """
    request = db.get(InstitutionCertificateRequest, request_id)
    if request is None:
        raise RequestNotFoundError()
    if request.institution_id != institution.id:
        raise RequestNotOwnedError()
    if request.student_id != student_id:
        raise RequestNotOwnedError()
    if request.status != InstitutionRequestStatus.APPROVED:
        raise RequestAlreadyProcessedError()
    return request


def mark_fulfilled(db: Session, request: InstitutionCertificateRequest, credential_id: uuid.UUID) -> None:
    request.status = InstitutionRequestStatus.FULFILLED
    request.fulfilled_credential_id = credential_id
    db.add(request)
    db.commit()


def to_response(request: InstitutionCertificateRequest) -> InstitutionCertificateRequestResponse:
    # Deliberately gated on status rather than just "is fulfilled_credential set" — this is the
    # one place that decides what "fulfilled_at" means, and PENDING/APPROVED/REJECTED must never
    # report a fulfillment time even if the relationship were ever populated some other way.
    fulfilled_at = (
        request.fulfilled_credential.issued_at
        if request.status == InstitutionRequestStatus.FULFILLED and request.fulfilled_credential is not None
        else None
    )
    return InstitutionCertificateRequestResponse(
        id=request.id,
        batch_id=request.batch_id,
        student_id=request.student_id,
        student_name=request.student.user.full_name,
        student_identifier=request.student.student_identifier,
        institution_id=request.institution_id,
        institution_name=request.institution.name,
        credential_type=request.credential_type,
        custom_credential_name=request.custom_credential_name,
        reason=request.reason,
        status=request.status,
        rejection_reason=request.rejection_reason,
        fulfilled_credential_id=request.fulfilled_credential_id,
        created_at=request.created_at,
        responded_at=request.responded_at,
        fulfilled_at=fulfilled_at,
    )
