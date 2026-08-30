# ---------------------------------------------------------------------------
# Credential requests + student-controlled selective sharing.
#
# The authorization boundary this feeds is app/services/authorization_service.py
# (Phase 5) — that file is UNCHANGED by this phase. Once approve_request()
# below creates a real ShareGrant + ShareGrantCredential rows, Phase 5's
# is_verifier_authorized() (which already queries exactly those tables)
# starts returning True for real, with zero code changes on that side. This
# is the payoff of keeping that boundary clean in Phase 5.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.company import Company
from ..models.credential import Credential
from ..models.credential_request import CredentialRequest
from ..models.enums import CredentialRequestStatus, SharePermission
from ..models.institution import Institution
from ..models.share_grant import ShareGrant, ShareGrantCredential
from ..models.student import Student
from ..models.user import User
from ..models.verification_event import VerificationEvent
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from ..schemas.sharing import (
    ALLOWED_EXPIRY_DAYS,
    SHARED_CREDENTIAL_STATUS_FILTERS,
    CredentialRequestResponse,
    ShareCredentialPreview,
    ShareGrantResponse,
    SharedCredentialItem,
)
from ..security.tokens import generate_raw_token, hash_token
from . import notification_service


class StudentNotFoundError(Exception):
    pass


class RequestNotFoundError(Exception):
    pass


class RequestNotOwnedError(Exception):
    pass


class RequestAlreadyProcessedError(Exception):
    pass


class InvalidExpiryError(Exception):
    pass


class CredentialSelectionError(Exception):
    pass


class CompanyNotFoundError(Exception):
    pass


class CompanyNotRegisteredError(Exception):
    """
    Raised when a direct share targets a directory-only Company (user_id is
    NULL). Such a row can never have a logged-in verifier — authorization_service
    only ever matches a grant against current_user.company — so a share created
    against it could never be redeemed by anyone. Not an authorization change:
    this only narrows what create_direct_share accepts as input.
    """

    pass


class ShareNotFoundError(Exception):
    pass


class ShareNotOwnedError(Exception):
    pass


class ShareAlreadyRevokedError(Exception):
    pass


class InvalidShareTokenError(Exception):
    pass


class ShareRevokedError(Exception):
    pass


class ShareExpiredError(Exception):
    pass


# ---- credential requests ---------------------------------------------------


def create_credential_request(
    db: Session,
    company: Company,
    *,
    student_id: uuid.UUID | None,
    student_identifier: str | None,
    purpose: str,
    requested_credentials: list[str],
) -> CredentialRequest:
    """
    Creating a request never grants access — it only records "company is
    asking". No ShareGrant is created here.

    Resolves the student by whichever reference was given — internal UUID
    (the original, legacy path) or the human-readable student_identifier a
    company would actually be given by a candidate. Exactly one is present
    by the time this is called (enforced by CreateCredentialRequestBody).
    """
    student = db.get(Student, student_id) if student_id else None
    if student is None and student_identifier:
        normalized = student_identifier.strip()
        student = (
            db.query(Student)
            .filter(func.lower(Student.student_identifier) == normalized.lower())
            .first()
        )
    if student is None:
        raise StudentNotFoundError()

    request = CredentialRequest(
        company_id=company.id,
        student_id=student.id,
        purpose=purpose,
        status=CredentialRequestStatus.PENDING,
        requested_credentials=requested_credentials,
    )
    db.add(request)
    db.flush()

    log = ActivityLog(
        actor_user_id=company.user_id,
        action="CREDENTIAL_REQUEST_CREATED",
        entity_type="credential_request",
        entity_id=request.id,
        metadata_={"student_id": str(student.id), "purpose": purpose},
    )
    db.add(log)
    db.flush()

    notification_service.create_notification(
        db,
        user_id=student.user_id,
        title="New credential request",
        message=f"{company.name} requested your credentials",
        activity_log_id=log.id,
        link_entity_type="credential_request",
        link_entity_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return request


def list_requests_for_company(db: Session, company: Company) -> list[CredentialRequest]:
    return (
        db.query(CredentialRequest)
        .filter(CredentialRequest.company_id == company.id)
        .order_by(CredentialRequest.created_at.desc())
        .all()
    )


def list_requests_for_student(db: Session, student: Student) -> list[CredentialRequest]:
    return (
        db.query(CredentialRequest)
        .filter(CredentialRequest.student_id == student.id)
        .order_by(CredentialRequest.created_at.desc())
        .all()
    )


def _get_owned_pending_request(db: Session, student: Student, request_id: uuid.UUID) -> CredentialRequest:
    request = db.get(CredentialRequest, request_id)
    if request is None:
        raise RequestNotFoundError()
    if request.student_id != student.id:
        raise RequestNotOwnedError()
    if request.status != CredentialRequestStatus.PENDING:
        raise RequestAlreadyProcessedError()
    return request


def decline_request(db: Session, student: Student, request_id: uuid.UUID) -> CredentialRequest:
    request = _get_owned_pending_request(db, student, request_id)
    request.status = CredentialRequestStatus.DECLINED
    request.responded_at = datetime.now(timezone.utc)
    db.add(request)

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="CREDENTIAL_REQUEST_DECLINED",
        entity_type="credential_request",
        entity_id=request.id,
        metadata_={"company_id": str(request.company_id)},
    )
    db.add(log)
    db.flush()

    company = db.get(Company, request.company_id)
    if company is not None and company.user_id is not None:
        notification_service.create_notification(
            db,
            user_id=company.user_id,
            title="Credential request declined",
            message=f"{student.user.full_name} declined your credential request",
            activity_log_id=log.id,
            link_entity_type="credential_request",
            link_entity_id=request.id,
        )

    db.commit()
    db.refresh(request)
    return request


def _resolve_and_validate_credentials(db: Session, student: Student, credential_ids: list[uuid.UUID]) -> list[Credential]:
    unique_ids = set(credential_ids)
    credentials = db.query(Credential).filter(Credential.id.in_(unique_ids)).all()
    if len(credentials) != len(unique_ids):
        raise CredentialSelectionError("One or more selected credentials do not exist")
    for credential in credentials:
        # Never trust that a credential_id belongs to this student just
        # because the frontend sent it — verify every one.
        if credential.student_id != student.id:
            raise CredentialSelectionError("One or more selected credentials do not belong to you")
    return credentials


def _create_share_grant(
    db: Session,
    student: Student,
    *,
    company_id: uuid.UUID,
    credentials: list[Credential],
    expires_in_days: int,
    permission: SharePermission,
    credential_request_id: uuid.UUID | None,
    notify: bool = True,
) -> tuple[ShareGrant, str]:
    """
    The ONE place a ShareGrant + ShareGrantCredential rows + secure token are
    ever created — used by both approve_request (credential_request_id set)
    and create_direct_share (credential_request_id null). Returns (grant,
    raw_token); the raw token is NOT persisted anywhere, the caller (the
    route) must hand it to the client and then let it go.

    notify=False lets job_application_service.apply_to_job suppress this
    grant's own notification: applying to a job already sends the company
    one clear "new application" notification, and also routes through this
    function internally (via approve_request) to create the real share — a
    second "credentials shared with you" notification for that exact same
    click would be a duplicate push for one logical event (see Phase 9 of
    the notification design). Every genuinely standalone caller (a real
    approve_request or create_direct_share invoked by a student acting on
    their own) leaves this True.
    """
    raw_token = generate_raw_token()
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    grant = ShareGrant(
        student_id=student.id,
        company_id=company_id,
        credential_request_id=credential_request_id,
        share_token_hash=token_hash,
        expires_at=expires_at,
        permission=permission,
    )
    db.add(grant)
    db.flush()

    for credential in credentials:
        db.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=credential.id))

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="CREDENTIAL_SHARED",
        entity_type="share_grant",
        entity_id=grant.id,
        metadata_={"company_id": str(company_id), "credential_count": len(credentials)},
    )
    db.add(log)
    db.flush()

    if notify:
        company = db.get(Company, company_id)
        # Sharing already requires an existing, real company row (the recipient search this
        # links from only ever offers registered companies — see ShareFlow.tsx) — a directory-only
        # company can never be a share recipient, but guard anyway since this function has no
        # other way to enforce that invariant itself.
        if company is not None and company.user_id is not None:
            label = credentials[0].title if len(credentials) == 1 else f"{len(credentials)} credentials"
            notification_service.create_notification(
                db,
                user_id=company.user_id,
                title="Credentials shared with you",
                message=f"{student.user.full_name} shared {label} with {company.name}",
                activity_log_id=log.id,
                link_entity_type="share_grant",
                link_entity_id=grant.id,
            )

    return grant, raw_token


def approve_request(
    db: Session,
    student: Student,
    request_id: uuid.UUID,
    *,
    credential_ids: list[uuid.UUID],
    expires_in_days: int,
    permission: SharePermission = SharePermission.VIEW_ONLY,
    notify: bool = True,
) -> tuple[ShareGrant, str]:
    """
    Creates the ShareGrant + ShareGrantCredential rows AND the secure token
    in one transaction. Only the credential_ids explicitly passed in are
    included — a credential the company originally asked for but the
    student didn't select here never becomes part of the grant, regardless
    of what request.requested_credentials says (that field is just the
    company's original ask; _create_share_grant is the only place a
    ShareGrant is actually created, and it only ever grants what's in
    credential_ids).

    notify=False is used by job_application_service.apply_to_job, which
    calls this to fulfil a system-generated request as part of applying to
    a job — that flow sends its own single, more specific "new application"
    notification instead (see _create_share_grant's docstring for the full
    duplicate-notification rationale). Every genuine, student-initiated
    approval (the real /api/credential-requests/{id}/approve route) leaves
    this True.
    """
    if expires_in_days not in ALLOWED_EXPIRY_DAYS:
        raise InvalidExpiryError(f"expires_in_days must be one of {ALLOWED_EXPIRY_DAYS}")
    if not credential_ids:
        raise CredentialSelectionError("Select at least one credential to share")

    request = _get_owned_pending_request(db, student, request_id)
    credentials = _resolve_and_validate_credentials(db, student, credential_ids)

    grant, raw_token = _create_share_grant(
        db,
        student,
        company_id=request.company_id,
        credentials=credentials,
        expires_in_days=expires_in_days,
        permission=permission,
        credential_request_id=request.id,
        notify=notify,
    )

    request.status = CredentialRequestStatus.APPROVED
    request.responded_at = datetime.now(timezone.utc)
    db.add(request)

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="CREDENTIAL_REQUEST_APPROVED",
        entity_type="credential_request",
        entity_id=request.id,
        metadata_={"company_id": str(request.company_id), "credential_count": len(credentials)},
    )
    db.add(log)
    db.flush()

    if notify:
        company = db.get(Company, request.company_id)
        if company is not None and company.user_id is not None:
            notification_service.create_notification(
                db,
                user_id=company.user_id,
                title="Credential request approved",
                message=f"{student.user.full_name} approved your credential request",
                activity_log_id=log.id,
                link_entity_type="credential_request",
                link_entity_id=request.id,
            )

    db.commit()
    db.refresh(grant)
    return grant, raw_token


def create_direct_share(
    db: Session,
    student: Student,
    *,
    company_id: uuid.UUID,
    credential_ids: list[uuid.UUID],
    expires_in_days: int,
    permission: SharePermission = SharePermission.VIEW_ONLY,
) -> tuple[ShareGrant, str]:
    """
    Student-initiated share directly to a real company — no prior
    CredentialRequest exists. Reuses the exact same ShareGrant creation path
    as approve_request; credential_request_id is simply null, which the
    schema already supports (see ShareGrant's docstring). The company must
    be a real, existing Company row — this is not a free-text recipient.
    """
    if expires_in_days not in ALLOWED_EXPIRY_DAYS:
        raise InvalidExpiryError(f"expires_in_days must be one of {ALLOWED_EXPIRY_DAYS}")
    if not credential_ids:
        raise CredentialSelectionError("Select at least one credential to share")

    company = db.get(Company, company_id)
    if company is None:
        raise CompanyNotFoundError()
    if company.user_id is None:
        raise CompanyNotRegisteredError()

    credentials = _resolve_and_validate_credentials(db, student, credential_ids)

    grant, raw_token = _create_share_grant(
        db,
        student,
        company_id=company.id,
        credentials=credentials,
        expires_in_days=expires_in_days,
        permission=permission,
        credential_request_id=None,
    )

    db.commit()
    db.refresh(grant)
    return grant, raw_token


# ---- shares -----------------------------------------------------------------


def list_shares_for_student(db: Session, student: Student) -> list[ShareGrant]:
    return db.query(ShareGrant).filter(ShareGrant.student_id == student.id).order_by(ShareGrant.created_at.desc()).all()


def list_shares_for_company(db: Session, company: Company) -> list[ShareGrant]:
    return db.query(ShareGrant).filter(ShareGrant.company_id == company.id).order_by(ShareGrant.created_at.desc()).all()


class InvalidSharedCredentialStatusFilterError(Exception):
    pass


def list_shared_credentials_for_company(
    db: Session,
    company: Company,
    *,
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[SharedCredentialItem], int]:
    """
    The "Credentials Shared With You" inbox — one row per (share_grant,
    credential) pair, scoped to exactly this company's own canonical
    company_id (the same authorization boundary company_id already
    enforces everywhere else; nothing new here). Backend-paginated and
    backend-searched/filtered so the frontend never has to load more than
    one page, matching the existing institution/company directory pattern
    (see company_service.list_companies).

    status, when given, must be one of SHARED_CREDENTIAL_STATUS_FILTERS and
    filters by the LATEST real VerificationEvent.result this company
    recorded for that credential — never by share/credential status alone,
    since a "VERIFIED" badge must mean an actual cryptographic check
    happened (see SharedCredentialItem's docstring). There is deliberately
    no way to filter for "not yet verified" — that's a display state, not a
    stored event to query against.
    """
    if status is not None and status not in SHARED_CREDENTIAL_STATUS_FILTERS:
        raise InvalidSharedCredentialStatusFilterError(
            f"status must be one of {SHARED_CREDENTIAL_STATUS_FILTERS}, got {status!r}"
        )

    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    # This credential's most recent verification result AS SEEN BY THIS COMPANY specifically
    # (never another company's checks on the same credential) — one windowed subquery, joined
    # once, rather than two independent correlated subqueries, so result/verified_at always come
    # from the exact same event row even if two events somehow share a timestamp.
    latest_event_subq = (
        db.query(
            VerificationEvent.credential_id.label("credential_id"),
            VerificationEvent.result.label("result"),
            VerificationEvent.verified_at.label("verified_at"),
            func.row_number()
            .over(partition_by=VerificationEvent.credential_id, order_by=VerificationEvent.verified_at.desc())
            .label("rn"),
        )
        .filter(VerificationEvent.company_id == company.id)
        .subquery()
    )

    query = (
        db.query(
            Credential,
            Student,
            User,
            Institution,
            ShareGrant,
            latest_event_subq.c.result,
            latest_event_subq.c.verified_at,
        )
        .join(ShareGrantCredential, ShareGrantCredential.credential_id == Credential.id)
        .join(ShareGrant, ShareGrant.id == ShareGrantCredential.share_grant_id)
        .join(Student, Student.id == ShareGrant.student_id)
        .join(User, User.id == Student.user_id)
        .join(Institution, Institution.id == Credential.institution_id)
        .outerjoin(
            latest_event_subq,
            (latest_event_subq.c.credential_id == Credential.id) & (latest_event_subq.c.rn == 1),
        )
        .filter(ShareGrant.company_id == company.id)
    )

    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.full_name.ilike(needle),
                Credential.title.ilike(needle),
                cast(Credential.credential_type, String).ilike(needle),
                Institution.name.ilike(needle),
            )
        )

    if status is not None:
        query = query.filter(latest_event_subq.c.result == status.upper())

    total = query.count()
    rows = (
        query.order_by(ShareGrant.created_at.desc(), Credential.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        SharedCredentialItem(
            id=credential.id,
            share_id=grant.id,
            student_id=student.id,
            student_name=user.full_name,
            credential_type=credential.credential_type,
            title=credential.title,
            degree=credential.degree,
            graduation_year=credential.graduation_year,
            cgpa=float(credential.cgpa) if credential.cgpa is not None else None,
            institution_name=institution.name,
            issued_at=credential.issued_at,
            permission=grant.permission.value,
            share_status=_share_status(grant),
            shared_at=grant.created_at,
            share_expires_at=grant.expires_at,
            latest_verification_result=latest_result.value if latest_result is not None else None,
            latest_verified_at=latest_verified_at,
        )
        for credential, student, user, institution, grant, latest_result, latest_verified_at in rows
    ]
    return items, total


def to_shared_credentials_page_response(
    items: list[SharedCredentialItem], *, total: int, page: int, page_size: int
) -> Page[SharedCredentialItem]:
    return Page.of(items, page=page, page_size=page_size, total=total)


def revoke_share(db: Session, student: Student, share_id: uuid.UUID) -> ShareGrant:
    grant = db.get(ShareGrant, share_id)
    if grant is None:
        raise ShareNotFoundError()
    if grant.student_id != student.id:
        raise ShareNotOwnedError()
    if grant.revoked_at is not None:
        raise ShareAlreadyRevokedError()

    grant.revoked_at = datetime.now(timezone.utc)
    db.add(grant)

    log = ActivityLog(
        actor_user_id=student.user_id,
        action="SHARE_REVOKED",
        entity_type="share_grant",
        entity_id=grant.id,
        metadata_={"company_id": str(grant.company_id)},
    )
    db.add(log)
    db.flush()

    company = grant.company
    # A directory-only company (never registered, no login) can never actually
    # have been a share recipient in the first place — _create_share_grant's
    # own guard already prevents that — but this function has no other way to
    # enforce that invariant itself, so it's checked again here.
    if company is not None and company.user_id is not None:
        credentials = grant.credentials
        label = credentials[0].title if len(credentials) == 1 else f"{len(credentials)} credentials"
        notification_service.create_notification(
            db,
            user_id=company.user_id,
            title="Credential Share Revoked",
            message=f"{student.user.full_name} revoked your access to {label}",
            activity_log_id=log.id,
            link_entity_type="share_grant",
            link_entity_id=grant.id,
        )

    db.commit()
    db.refresh(grant)
    return grant


def access_share_by_token(db: Session, raw_token: str) -> ShareGrant:
    """
    Looks up a ShareGrant by the SHA-256 hash of the supplied raw token —
    never by storing or comparing the raw token itself. Raises a distinct
    typed error for "no such token" vs. "revoked" vs. "expired" so the route
    can return the right status code (401 vs. 410) without ever echoing the
    token or hash back.
    """
    token_hash = hash_token(raw_token)
    grant = db.query(ShareGrant).filter(ShareGrant.share_token_hash == token_hash).first()
    if grant is None:
        raise InvalidShareTokenError()
    if grant.revoked_at is not None:
        raise ShareRevokedError()
    if grant.expires_at <= datetime.now(timezone.utc):
        raise ShareExpiredError()

    db.add(
        ActivityLog(
            actor_user_id=None,  # accessed via link/QR, not an authenticated session — no actor to attribute this to
            action="SHARE_ACCESSED",
            entity_type="share_grant",
            entity_id=grant.id,
            metadata_={"company_id": str(grant.company_id)},
        )
    )
    db.commit()
    return grant


# ---- response builders --------------------------------------------------------


def to_credential_request_response(db: Session, request: CredentialRequest) -> CredentialRequestResponse:
    # The ShareGrant (if any) created when this specific request was
    # approved — see approve_request, which sets credential_request_id.
    grant = db.query(ShareGrant).filter(ShareGrant.credential_request_id == request.id).first()
    shared = [_credential_preview(link.credential) for link in grant.credential_links] if grant else []

    return CredentialRequestResponse(
        id=request.id,
        company_id=request.company_id,
        company_name=request.company.name,
        student_id=request.student_id,
        student_name=request.student.user.full_name,
        purpose=request.purpose,
        requested_credentials=request.requested_credentials,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
        responded_at=request.responded_at,
        shared_credentials=shared,
    )


def _share_status(grant: ShareGrant) -> str:
    if grant.revoked_at is not None:
        return "revoked"
    if grant.expires_at <= datetime.now(timezone.utc):
        return "expired"
    return "active"


def _credential_preview(credential: Credential) -> ShareCredentialPreview:
    return ShareCredentialPreview(
        id=credential.id,
        credential_type=credential.credential_type,
        title=credential.title,
        degree=credential.degree,
        graduation_year=credential.graduation_year,
        cgpa=float(credential.cgpa) if credential.cgpa is not None else None,
        institution_name=credential.institution.name,
    )


def to_share_grant_response(grant: ShareGrant) -> ShareGrantResponse:
    return ShareGrantResponse(
        id=grant.id,
        company_id=grant.company_id,
        company_name=grant.company.name,
        credentials=[_credential_preview(link.credential) for link in grant.credential_links],
        permission=grant.permission.value,
        created_at=grant.created_at,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        status=_share_status(grant),
    )
