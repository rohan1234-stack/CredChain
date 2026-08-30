# ---------------------------------------------------------------------------
# Job applications. Deliberately owns ONLY the application's status
# lifecycle — the actual credential sharing is delegated entirely to the
# existing CredentialRequest + sharing_service.approve_request pipeline
# (Phase 6/PS3-F from prior phases), unmodified. Applying to a job creates a
# real CredentialRequest exactly as if the company had asked for
# job.required_documents directly, then immediately approves it with the
# student's chosen credential_ids via the EXISTING approve_request function
# — same ownership checks, same ShareGrant creation, same
# credential_request_id link that verification_service.check_type_mismatch
# already knows how to read. No second sharing or verification system.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.credential_request import CredentialRequest
from ..models.enums import ApplicationStatus, CredentialRequestStatus, JobStatus, SharePermission
from ..models.job import Job
from ..models.job_application import JobApplication
from ..models.student import Student
from ..schemas.job import EligibilityResult
from ..schemas.job_application import ApplicationHistoryEntry, CompanyApplicationResponse, StudentApplicationResponse
from . import eligibility_service, notification_service, sharing_service

APPLICATION_SHARE_EXPIRY_DAYS = 30

# Only these ActivityLog actions unambiguously represent a real status transition on THIS
# application — each is written exactly once, at the moment that exact status was reached (see
# apply_to_job, update_status, withdraw_application below). Never derived from updated_at or a
# notification's created_at, and never includes a status this application didn't actually pass
# through.
_HISTORY_ACTION_TO_STATUS: dict[str, ApplicationStatus] = {
    "APPLICATION_SUBMITTED": ApplicationStatus.APPLIED,
    "APPLICATION_UNDER_REVIEW": ApplicationStatus.UNDER_REVIEW,
    "APPLICATION_SHORTLISTED": ApplicationStatus.SHORTLISTED,
    "APPLICATION_REJECTED": ApplicationStatus.REJECTED,
    "APPLICATION_ACCEPTED": ApplicationStatus.ACCEPTED,
    "APPLICATION_WITHDRAWN": ApplicationStatus.WITHDRAWN,
}


class JobNotFoundError(Exception):
    pass


class JobNotOpenError(Exception):
    pass


class ApplicationDeadlinePassedError(Exception):
    pass


class AlreadyAppliedError(Exception):
    pass


class ApplicationNotFoundError(Exception):
    pass


class ApplicationNotOwnedError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    pass


class RejectionReasonRequiredError(Exception):
    pass


class WithdrawalNotAllowedError(Exception):
    pass


_ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.REJECTED},
    ApplicationStatus.UNDER_REVIEW: {ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED},
    ApplicationStatus.SHORTLISTED: {ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED},
}


def apply_to_job(
    db: Session,
    student: Student,
    *,
    job_id: uuid.UUID,
    credential_ids: list[uuid.UUID],
) -> JobApplication:
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError()
    if job.status != JobStatus.OPEN:
        raise JobNotOpenError()
    if job.application_deadline is not None and datetime.now(timezone.utc) > job.application_deadline:
        raise ApplicationDeadlinePassedError()

    existing = (
        db.query(JobApplication)
        .filter(JobApplication.job_id == job.id, JobApplication.student_id == student.id)
        .first()
    )
    if existing is not None:
        raise AlreadyAppliedError()

    # Same shape a company's own direct request takes — this IS that
    # pipeline, not a lookalike of it.
    request = CredentialRequest(
        company_id=job.company_id,
        student_id=student.id,
        purpose=f"Application: {job.title}",
        status=CredentialRequestStatus.PENDING,
        requested_credentials=job.required_documents,
    )
    db.add(request)
    db.flush()

    # Reuses the existing, unmodified approve_request — same ownership
    # checks on credential_ids, same ShareGrant + credential_request_id
    # link that the mismatch/verification pipeline already understands.
    # notify=False: this call's own CREDENTIAL_REQUEST_APPROVED/CREDENTIAL_SHARED
    # notifications would duplicate the single, more specific APPLICATION_SUBMITTED
    # notification created below for this exact same click (see approve_request's
    # and _create_share_grant's docstrings).
    grant, _raw_token = sharing_service.approve_request(
        db,
        student,
        request.id,
        credential_ids=credential_ids,
        expires_in_days=APPLICATION_SHARE_EXPIRY_DAYS,
        permission=SharePermission.VIEW_ONLY,
        notify=False,
    )

    application = JobApplication(
        student_id=student.id,
        job_id=job.id,
        company_id=job.company_id,
        status=ApplicationStatus.APPLIED,
        credential_request_id=request.id,
    )
    db.add(application)
    try:
        db.flush()
    except IntegrityError as exc:
        # A second concurrent request for the same (job_id, student_id) can pass the
        # existing duplicate check above and still lose the race to this database-level
        # constraint — converted to the same friendly error the sequential check raises,
        # rather than surfacing a raw 500. Any other IntegrityError (unrelated to this
        # specific constraint) is re-raised unchanged rather than masked.
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_job_applications_job_id_student_id":
            raise AlreadyAppliedError() from exc
        raise

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="APPLICATION_SUBMITTED",
        entity_type="job_application",
        entity_id=application.id,
        metadata_={"job_id": str(job.id)},
    )
    db.add(log)
    db.flush()

    # A Job's owning company is normally a registered, verified account — publish_job (the
    # only way a job becomes visible enough to apply to) requires that. But directory-only
    # rows (user_id IS NULL) can still end up with an OPEN job seeded directly outside that
    # path (see scripts/seed_directory.py) — same guard as sharing_service's equivalent calls,
    # so the application itself still succeeds even when there's no real recipient to notify.
    if grant.company is not None and grant.company.user_id is not None:
        notification_service.create_notification(
            db,
            user_id=grant.company.user_id,
            title="New job application",
            message=f"{student.user.full_name} applied to {job.title}",
            activity_log_id=log.id,
            link_entity_type="job_application",
            link_entity_id=application.id,
        )

    db.commit()
    db.refresh(application)
    return application


def list_for_student(db: Session, student: Student) -> list[JobApplication]:
    return db.query(JobApplication).filter(JobApplication.student_id == student.id).order_by(JobApplication.created_at.desc()).all()


def list_for_company(db: Session, company_id: uuid.UUID) -> list[JobApplication]:
    return db.query(JobApplication).filter(JobApplication.company_id == company_id).order_by(JobApplication.created_at.desc()).all()


def _get_owned_application(db: Session, company_id: uuid.UUID, application_id: uuid.UUID) -> JobApplication:
    application = db.get(JobApplication, application_id)
    if application is None:
        raise ApplicationNotFoundError()
    if application.company_id != company_id:
        raise ApplicationNotOwnedError()
    return application


def update_status(
    db: Session,
    company_id: uuid.UUID,
    application_id: uuid.UUID,
    new_status: ApplicationStatus,
    *,
    reason: str | None = None,
) -> JobApplication:
    application = _get_owned_application(db, company_id, application_id)
    allowed = _ALLOWED_TRANSITIONS.get(application.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransitionError()
    if new_status == ApplicationStatus.REJECTED and not (reason and reason.strip()):
        raise RejectionReasonRequiredError()

    application.status = new_status
    application.rejection_reason = reason.strip() if new_status == ApplicationStatus.REJECTED else application.rejection_reason
    db.add(application)

    log = ActivityLog(
        actor_user_id=application.company.user_id,
        action=f"APPLICATION_{new_status.value.upper()}",
        entity_type="job_application",
        entity_id=application.id,
        metadata_={"job_id": str(application.job_id), "student_id": str(application.student_id)}
        | ({"reason": application.rejection_reason} if new_status == ApplicationStatus.REJECTED else {}),
    )
    db.add(log)
    db.flush()

    status_label = new_status.value.replace("_", " ")
    notification_service.create_notification(
        db,
        user_id=application.student.user_id,
        title="Application status updated",
        message=f"Your application for {application.job.title} at {application.company.name} is now {status_label}",
        activity_log_id=log.id,
        link_entity_type="job_application",
        link_entity_id=application.id,
    )

    db.commit()
    db.refresh(application)
    return application


def withdraw_application(db: Session, student: Student, application_id: uuid.UUID) -> JobApplication:
    """Only the owning student may withdraw, and only from a state where the outcome isn't already final — an ACCEPTED offer can't be silently pulled back through this path."""
    application = db.get(JobApplication, application_id)
    if application is None:
        raise ApplicationNotFoundError()
    if application.student_id != student.id:
        raise ApplicationNotOwnedError()
    if application.status not in {ApplicationStatus.APPLIED, ApplicationStatus.UNDER_REVIEW, ApplicationStatus.SHORTLISTED}:
        raise WithdrawalNotAllowedError()

    application.status = ApplicationStatus.WITHDRAWN
    db.add(application)

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="APPLICATION_WITHDRAWN",
        entity_type="job_application",
        entity_id=application.id,
        metadata_={"job_id": str(application.job_id)},
    )
    db.add(log)
    db.flush()

    notification_service.create_notification(
        db,
        user_id=application.company.user_id,
        title="Application withdrawn",
        message=f"{student.user.full_name} withdrew their application for {application.job.title}",
        activity_log_id=log.id,
        link_entity_type="job_application",
        link_entity_id=application.id,
    )

    db.commit()
    db.refresh(application)
    return application


def get_application_history(db: Session, application: JobApplication) -> list[ApplicationHistoryEntry]:
    """
    This application's real status-transition history, built entirely from
    ActivityLog rows apply_to_job/update_status/withdraw_application already
    write — never a fabricated step, never updated_at, never a notification
    timestamp.

    `application` must already be an ownership-verified row — exactly the
    same trust boundary to_student_response/to_company_response themselves
    rely on (see _get_owned_application for the company path, and the
    student_id-filtered queries / direct ownership checks in
    list_for_student/apply_to_job/withdraw_application for the student path).
    This function does not re-authorize; it must never be called with an
    application the current caller has not already been proven to own.
    """
    rows = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.entity_type == "job_application",
            ActivityLog.entity_id == application.id,
            ActivityLog.action.in_(_HISTORY_ACTION_TO_STATUS),
        )
        .order_by(ActivityLog.created_at.asc())
        .all()
    )
    return [
        ApplicationHistoryEntry(status=_HISTORY_ACTION_TO_STATUS[row.action], occurred_at=row.created_at)
        for row in rows
    ]


def to_student_response(db: Session, application: JobApplication) -> StudentApplicationResponse:
    return StudentApplicationResponse(
        id=application.id,
        job_id=application.job_id,
        job_title=application.job.title,
        company_id=application.company_id,
        company_name=application.company.name,
        status=application.status,
        rejection_reason=application.rejection_reason,
        created_at=application.created_at,
        history=get_application_history(db, application),
    )


def to_company_response(db: Session, application: JobApplication) -> CompanyApplicationResponse:
    credential_request = None
    if application.credential_request is not None:
        credential_request = sharing_service.to_credential_request_response(db, application.credential_request)

    eligibility = EligibilityResult(**eligibility_service.evaluate(db, application.job, application.student))

    return CompanyApplicationResponse(
        id=application.id,
        job_id=application.job_id,
        job_title=application.job.title,
        student_id=application.student_id,
        student_name=application.student.user.full_name,
        student_identifier=application.student.student_identifier,
        status=application.status,
        rejection_reason=application.rejection_reason,
        created_at=application.created_at,
        credential_request=credential_request,
        eligibility=eligibility,
        history=get_application_history(db, application),
    )
