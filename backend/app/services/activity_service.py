# ---------------------------------------------------------------------------
# Phase 8B: read-only activity feeds built purely on top of the existing
# ActivityLog table (see app/models/activity_log.py) and the existing writes
# to it in credential_service, sharing_service, verification_service, and
# ai routes. Nothing here writes to ActivityLog or changes any of those
# write paths — this module only queries and renders.
#
# ActivityLog.actor_user_id identifies who performed an action, but most
# events matter to *someone else* too (a student cares that an institution
# issued them a credential, even though the institution is the actor). So
# "this role's activity" is resolved via entity ownership, not just actor
# identity: for each entity_type an event can reference, we first collect
# the ids of that role's own rows (their credentials / requests / grants),
# then match ActivityLog rows either by being the actor or by pointing at
# one of those owned entities.
# ---------------------------------------------------------------------------

import uuid

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.company import Company
from ..models.credential import Credential
from ..models.credential_request import CredentialRequest
from ..models.institution import Institution
from ..models.institution_certificate_request import InstitutionCertificateRequest
from ..models.job_application import JobApplication
from ..models.share_grant import ShareGrant
from ..models.student import Student
from ..models.student_document import StudentDocument

DEFAULT_LIMIT = 50
MAX_LIMIT = 50


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def get_student_activity(db: Session, student: Student, limit: int = DEFAULT_LIMIT) -> list[ActivityLog]:
    credential_ids = [row[0] for row in db.query(Credential.id).filter(Credential.student_id == student.id).all()]
    request_ids = [row[0] for row in db.query(CredentialRequest.id).filter(CredentialRequest.student_id == student.id).all()]
    grant_ids = [row[0] for row in db.query(ShareGrant.id).filter(ShareGrant.student_id == student.id).all()]
    application_ids = [row[0] for row in db.query(JobApplication.id).filter(JobApplication.student_id == student.id).all()]
    cert_request_ids = [
        row[0] for row in db.query(InstitutionCertificateRequest.id).filter(InstitutionCertificateRequest.student_id == student.id).all()
    ]
    document_ids = [row[0] for row in db.query(StudentDocument.id).filter(StudentDocument.student_id == student.id).all()]

    condition = or_(
        ActivityLog.actor_user_id == student.user_id,
        and_(ActivityLog.entity_type == "credential", ActivityLog.entity_id.in_(credential_ids)) if credential_ids else False,
        and_(ActivityLog.entity_type == "credential_request", ActivityLog.entity_id.in_(request_ids)) if request_ids else False,
        and_(ActivityLog.entity_type == "share_grant", ActivityLog.entity_id.in_(grant_ids)) if grant_ids else False,
        and_(ActivityLog.entity_type == "job_application", ActivityLog.entity_id.in_(application_ids)) if application_ids else False,
        and_(ActivityLog.entity_type == "institution_certificate_request", ActivityLog.entity_id.in_(cert_request_ids))
        if cert_request_ids
        else False,
        and_(ActivityLog.entity_type == "student_document", ActivityLog.entity_id.in_(document_ids)) if document_ids else False,
    )
    return (
        db.query(ActivityLog)
        .filter(condition)
        .order_by(ActivityLog.created_at.desc())
        .limit(_clamp_limit(limit))
        .all()
    )


def get_institution_activity(db: Session, institution: Institution, limit: int = DEFAULT_LIMIT) -> list[ActivityLog]:
    credential_ids = [row[0] for row in db.query(Credential.id).filter(Credential.institution_id == institution.id).all()]
    cert_request_ids = [
        row[0]
        for row in db.query(InstitutionCertificateRequest.id)
        .filter(InstitutionCertificateRequest.institution_id == institution.id)
        .all()
    ]
    document_ids = [row[0] for row in db.query(StudentDocument.id).filter(StudentDocument.institution_id == institution.id).all()]

    condition = or_(
        ActivityLog.actor_user_id == institution.user_id,
        and_(ActivityLog.entity_type == "credential", ActivityLog.entity_id.in_(credential_ids)) if credential_ids else False,
        and_(ActivityLog.entity_type == "institution_certificate_request", ActivityLog.entity_id.in_(cert_request_ids))
        if cert_request_ids
        else False,
        and_(ActivityLog.entity_type == "student_document", ActivityLog.entity_id.in_(document_ids)) if document_ids else False,
        # Admin's approve/reject decision about THIS institution — the actor is the admin, not
        # this institution, so this can only ever be found by matching entity_id to itself.
        and_(ActivityLog.entity_type == "institution", ActivityLog.entity_id == institution.id),
    )
    return (
        db.query(ActivityLog)
        .filter(condition)
        .order_by(ActivityLog.created_at.desc())
        .limit(_clamp_limit(limit))
        .all()
    )


def get_company_activity(db: Session, company: Company, limit: int = DEFAULT_LIMIT) -> list[ActivityLog]:
    request_ids = [row[0] for row in db.query(CredentialRequest.id).filter(CredentialRequest.company_id == company.id).all()]
    grant_ids = [row[0] for row in db.query(ShareGrant.id).filter(ShareGrant.company_id == company.id).all()]
    application_ids = [row[0] for row in db.query(JobApplication.id).filter(JobApplication.company_id == company.id).all()]

    condition = or_(
        ActivityLog.actor_user_id == company.user_id,
        and_(ActivityLog.entity_type == "credential_request", ActivityLog.entity_id.in_(request_ids)) if request_ids else False,
        and_(ActivityLog.entity_type == "share_grant", ActivityLog.entity_id.in_(grant_ids)) if grant_ids else False,
        and_(ActivityLog.entity_type == "job_application", ActivityLog.entity_id.in_(application_ids)) if application_ids else False,
        # Admin's approve/reject decision about THIS company — same rationale as the institution case above.
        and_(ActivityLog.entity_type == "company", ActivityLog.entity_id == company.id),
    )
    return (
        db.query(ActivityLog)
        .filter(condition)
        .order_by(ActivityLog.created_at.desc())
        .limit(_clamp_limit(limit))
        .all()
    )


# --- human-readable message rendering ---------------------------------------

_GENERIC_MESSAGES = {
    "CREDENTIAL_ISSUED": "A credential was issued",
    "CREDENTIAL_REVOKED": "A credential was revoked",
    "CREDENTIAL_VERIFIED": "A credential was verified",
    "CREDENTIAL_REQUEST_CREATED": "A credential request was made",
    "CREDENTIAL_REQUEST_APPROVED": "A credential request was approved",
    "CREDENTIAL_REQUEST_DECLINED": "A credential request was declined",
    "CREDENTIAL_SHARED": "Credentials were shared",
    "SHARE_REVOKED": "Share link revoked",
    "SHARE_ACCESSED": "A shared link was accessed",
    "AI_DOCUMENT_ANALYSIS": "AI document analysis completed",
    "AI_COMPANY_ANALYSIS": "AI company analysis completed",
    "AI_JOB_ANALYSIS": "AI job analysis completed",
    "AI_JOB_MATCH": "AI job match analysis completed",
    "APPLICATION_SUBMITTED": "A job application was submitted",
    "APPLICATION_UNDER_REVIEW": "An application moved to under review",
    "APPLICATION_SHORTLISTED": "An application was shortlisted",
    "APPLICATION_ACCEPTED": "An application was accepted",
    "APPLICATION_REJECTED": "An application was rejected",
    "APPLICATION_WITHDRAWN": "An application was withdrawn",
    "ADMIN_APPROVED_INSTITUTION": "An institution was approved",
    "ADMIN_REJECTED_INSTITUTION": "An institution's registration was rejected",
    "ADMIN_APPROVED_COMPANY": "A company was approved",
    "ADMIN_REJECTED_COMPANY": "A company's registration was rejected",
    "CERTIFICATE_REQUEST_CREATED": "A certificate request was submitted",
    "CERTIFICATE_REQUEST_APPROVED": "A certificate request was approved",
    "CERTIFICATE_REQUEST_REJECTED": "A certificate request was rejected",
    "STUDENT_DOCUMENT_SUBMITTED": "A document was submitted for review",
    "STUDENT_DOCUMENT_APPROVED": "A submitted document was approved",
    "STUDENT_DOCUMENT_REJECTED": "A submitted document was rejected",
}

# job_application.status values, for a friendly label rather than the raw enum string.
_APPLICATION_STATUS_LABEL = {
    "under_review": "under review",
    "shortlisted": "shortlisted",
    "accepted": "accepted",
    "rejected": "rejected",
}


def _credential_for(db: Session, entity_id: uuid.UUID | None) -> Credential | None:
    if entity_id is None:
        return None
    return db.get(Credential, entity_id)


def _request_for(db: Session, entity_id: uuid.UUID | None) -> CredentialRequest | None:
    if entity_id is None:
        return None
    return db.get(CredentialRequest, entity_id)


def _grant_for(db: Session, entity_id: uuid.UUID | None) -> ShareGrant | None:
    if entity_id is None:
        return None
    return db.get(ShareGrant, entity_id)


def _application_for(db: Session, entity_id: uuid.UUID | None) -> JobApplication | None:
    if entity_id is None:
        return None
    return db.get(JobApplication, entity_id)


def _institution_for(db: Session, entity_id: uuid.UUID | None) -> Institution | None:
    if entity_id is None:
        return None
    return db.get(Institution, entity_id)


def _company_for(db: Session, entity_id: uuid.UUID | None) -> Company | None:
    if entity_id is None:
        return None
    return db.get(Company, entity_id)


def _certificate_request_for(db: Session, entity_id: uuid.UUID | None) -> InstitutionCertificateRequest | None:
    if entity_id is None:
        return None
    return db.get(InstitutionCertificateRequest, entity_id)


def _student_document_for(db: Session, entity_id: uuid.UUID | None) -> StudentDocument | None:
    if entity_id is None:
        return None
    return db.get(StudentDocument, entity_id)


def render_message(db: Session, log: ActivityLog, *, viewer_role: str) -> str:
    """
    Builds a clean, human-readable message for one ActivityLog row from
    real data already reachable from the row (its resolved entity, or the
    actor's own profile name) — never from fabricated details. Falls back
    to a safe generic message if the referenced entity can no longer be
    resolved (e.g. it was later deleted) or the action isn't recognized.
    """
    action = log.action
    meta = log.metadata_ or {}

    try:
        if action == "CREDENTIAL_ISSUED":
            credential = _credential_for(db, log.entity_id)
            if credential is None:
                return _GENERIC_MESSAGES[action]
            student_name = credential.student.user.full_name
            if viewer_role == "student":
                return f"{credential.institution.name} issued you a credential: {credential.title}"
            return f"Credential issued to {student_name}"

        if action == "CREDENTIAL_REVOKED":
            credential = _credential_for(db, log.entity_id)
            if credential is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"{credential.institution.name} revoked your credential: {credential.title}"
            return f"Revoked credential: {credential.title}"

        if action == "CREDENTIAL_VERIFIED":
            credential = _credential_for(db, log.entity_id)
            company_name = log.actor_user.company.name if log.actor_user and log.actor_user.company else "A company"
            if credential is None:
                return f"{company_name} attempted to verify a credential"
            if viewer_role == "student":
                return f"{company_name} verified your credential: {credential.title}"
            if viewer_role == "institution":
                return f"{company_name} verified a credential you issued: {credential.title}"
            return f"You verified {credential.title} ({credential.student.user.full_name})"

        if action == "CREDENTIAL_REQUEST_CREATED":
            request = _request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"{request.company.name} requested your credentials"
            return f"You requested credentials from {request.student.user.full_name}"

        if action == "CREDENTIAL_REQUEST_APPROVED":
            request = _request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You approved {request.company.name}'s credential request"
            return f"{request.student.user.full_name} approved your credential request"

        if action == "CREDENTIAL_REQUEST_DECLINED":
            request = _request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You declined {request.company.name}'s credential request"
            return f"{request.student.user.full_name} declined your credential request"

        if action == "CREDENTIAL_SHARED":
            grant = _grant_for(db, log.entity_id)
            if grant is None:
                return _GENERIC_MESSAGES[action]
            credentials = grant.credentials
            label = credentials[0].title if len(credentials) == 1 else f"{len(credentials)} credentials"
            if viewer_role == "student":
                return f"You shared {label} with {grant.company.name}"
            return f"{grant.student.user.full_name} shared {label} with you"

        if action == "SHARE_REVOKED":
            grant = _grant_for(db, log.entity_id)
            if grant is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You revoked {grant.company.name}'s access to your credentials"
            return f"{grant.student.user.full_name} revoked your access to their credentials"

        if action == "SHARE_ACCESSED":
            grant = _grant_for(db, log.entity_id)
            if grant is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"{grant.company.name} accessed your shared credentials"
            return f"Your shared link for {grant.student.user.full_name} was accessed"

        if action.startswith("AI_"):
            job_title = meta.get("job_title")
            base = _GENERIC_MESSAGES.get(action, "AI analysis completed")
            return f"{base} for \"{job_title}\"" if job_title else base

        if action == "APPLICATION_SUBMITTED":
            application = _application_for(db, log.entity_id)
            if application is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You applied to {application.job.title} at {application.company.name}"
            return f"{application.student.user.full_name} applied to {application.job.title}"

        if action in ("APPLICATION_UNDER_REVIEW", "APPLICATION_SHORTLISTED", "APPLICATION_ACCEPTED", "APPLICATION_REJECTED"):
            application = _application_for(db, log.entity_id)
            if application is None:
                return _GENERIC_MESSAGES.get(action, "Activity recorded")
            status_label = _APPLICATION_STATUS_LABEL.get(application.status.value, application.status.value)
            if viewer_role == "student":
                return f"Your application for {application.job.title} at {application.company.name} is now {status_label}"
            return f"{application.student.user.full_name}'s application for {application.job.title} is now {status_label}"

        if action == "APPLICATION_WITHDRAWN":
            application = _application_for(db, log.entity_id)
            if application is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You withdrew your application for {application.job.title}"
            return f"{application.student.user.full_name} withdrew their application for {application.job.title}"

        if action == "ADMIN_APPROVED_INSTITUTION":
            institution = _institution_for(db, log.entity_id)
            name = institution.name if institution else "Your institution"
            return f"{name} was approved and can now issue credentials"

        if action == "ADMIN_REJECTED_INSTITUTION":
            institution = _institution_for(db, log.entity_id)
            reason = institution.rejection_reason if institution else None
            base = f"{institution.name if institution else 'Your institution'}'s registration was rejected"
            return f"{base}: {reason}" if reason else base

        if action == "ADMIN_APPROVED_COMPANY":
            company = _company_for(db, log.entity_id)
            name = company.name if company else "Your company"
            return f"{name} was approved and can now publish jobs"

        if action == "ADMIN_REJECTED_COMPANY":
            company = _company_for(db, log.entity_id)
            reason = company.rejection_reason if company else None
            base = f"{company.name if company else 'Your company'}'s registration was rejected"
            return f"{base}: {reason}" if reason else base

        if action == "CERTIFICATE_REQUEST_CREATED":
            request = _certificate_request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            label = request.custom_credential_name or request.credential_type.value.replace("_", " ").title()
            if viewer_role == "student":
                return f"You requested {label} from {request.institution.name}"
            return f"{request.student.user.full_name} requested {label}"

        if action == "CERTIFICATE_REQUEST_APPROVED":
            request = _certificate_request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            label = request.custom_credential_name or request.credential_type.value.replace("_", " ").title()
            if viewer_role == "student":
                return f"{request.institution.name} approved your {label} request"
            return f"You approved {request.student.user.full_name}'s {label} request"

        if action == "CERTIFICATE_REQUEST_REJECTED":
            request = _certificate_request_for(db, log.entity_id)
            if request is None:
                return _GENERIC_MESSAGES[action]
            label = request.custom_credential_name or request.credential_type.value.replace("_", " ").title()
            if viewer_role == "student":
                return f"{request.institution.name} rejected your {label} request"
            return f"You rejected {request.student.user.full_name}'s {label} request"

        if action == "STUDENT_DOCUMENT_SUBMITTED":
            document = _student_document_for(db, log.entity_id)
            if document is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"You submitted a document to {document.institution.name} for review"
            return f"{document.student.user.full_name} submitted a document for review"

        if action == "STUDENT_DOCUMENT_APPROVED":
            document = _student_document_for(db, log.entity_id)
            if document is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"{document.institution.name} approved your submitted document"
            return f"You approved {document.student.user.full_name}'s submitted document"

        if action == "STUDENT_DOCUMENT_REJECTED":
            document = _student_document_for(db, log.entity_id)
            if document is None:
                return _GENERIC_MESSAGES[action]
            if viewer_role == "student":
                return f"{document.institution.name} rejected your submitted document"
            return f"You rejected {document.student.user.full_name}'s submitted document"

        return _GENERIC_MESSAGES.get(action, "Activity recorded")
    except Exception:
        # A resolvable-looking entity that turned out to be in an
        # unexpected state should never break the whole feed — fall back
        # to a safe generic label for this one row instead.
        return _GENERIC_MESSAGES.get(action, "Activity recorded")
