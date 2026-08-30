# ---------------------------------------------------------------------------
# Auth business logic — routes/auth.py stays thin and only translates these
# exceptions into HTTP responses.
# ---------------------------------------------------------------------------

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models.company import Company
from ..models.enums import UserRole, VerificationStatus
from ..models.institution import Institution
from ..models.student import Student
from ..models.user import User
from ..schemas.auth import RegisterRequest
from ..security.password import hash_password, verify_password
from . import notification_service, signing_service


def _notify_admins_of_pending_review(db: Session, *, entity_type: str, entity_id, org_name: str) -> None:
    """
    One Notification per active admin, generated exactly once at the moment a real
    institution/company registration succeeds (this function is only ever called from
    inside register_user's own commit, which itself only runs once per successful claim
    — the atomic UPDATE ... WHERE user_id IS NULL guard above ensures a given directory
    row can only ever be successfully claimed once). No ActivityLog entry is added for
    this — admin's "awaiting review" queue is already the real, live PENDING-status query
    in admin_service.list_pending_institutions/list_pending_companies; this notification
    is just a heads-up pointing at that same real record, not a second source of truth.
    """
    admin_ids = [row[0] for row in db.query(User.id).filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).all()]
    for admin_id in admin_ids:
        notification_service.create_notification(
            db,
            user_id=admin_id,
            title="New registration awaiting review",
            message=f"{org_name} registered and is awaiting verification",
            link_entity_type=entity_type,
            link_entity_id=entity_id,
        )


class EmailAlreadyRegisteredError(Exception):
    pass


class MissingProfileFieldsError(Exception):
    pass


class InstitutionNotFoundError(Exception):
    pass


class CompanyNotFoundError(Exception):
    pass


class InstitutionAlreadyClaimedError(Exception):
    """Raised when the selected directory Institution already has a registered account (user_id is not NULL)."""


class CompanyAlreadyClaimedError(Exception):
    """Raised when the selected directory Company already has a registered account (user_id is not NULL)."""


class InvalidCredentialsError(Exception):
    pass


class InactiveAccountError(Exception):
    pass


class AdminSelfRegistrationError(Exception):
    """Raised if a registration payload requests role=admin — there is no public admin sign-up path (see backend/scripts/create_admin.py for the only supported provisioning route)."""


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


def register_user(db: Session, payload: RegisterRequest) -> User:
    """
    Creates the User row plus the matching role-specific profile row in one
    transaction (all-or-nothing — a failure partway through rolls back both).

    Institution and verifier(company) registration is open to anyone who
    calls this endpoint (same as student registration) and the account is
    immediately usable for login/browsing — but NOT for the two actions that
    require real trust: credential_service.issue_signed_credential /
    job_service.publish_job both refuse to act until an admin has approved
    the account (see services/admin_service.py, routes/admin.py). role=admin
    can never reach this function — see the AdminSelfRegistrationError check
    above; admin accounts are provisioned only via backend/scripts/create_admin.py.

    Institution/company registration is a CLAIM on an existing canonical
    directory record, never a free-text creation of a new one — this is the
    fix for the bug where an institution account and a student both meaning
    "Aalto University" could end up pointing at two different Institution
    rows. The directory (~10,000+ imported institutions/companies, see
    scripts/import_institutions.py / import_companies.py) is the single
    source of truth for organization identity; registering only ever sets
    user_id on an existing row, exactly like student_service.link_student_to_institution
    already does for students. The verification_status stays whatever the
    row's default already is (PENDING for a fresh directory row) unless the
    Phase A migration's grandfathering already marked it VERIFIED.
    """
    if payload.role == UserRole.ADMIN:
        raise AdminSelfRegistrationError()
    if get_user_by_email(db, payload.email):
        raise EmailAlreadyRegisteredError()

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()  # assigns user.id without committing, so FK rows below can reference it

    if payload.role == UserRole.STUDENT:
        if not payload.student_identifier:
            raise MissingProfileFieldsError("student_identifier is required for student registration")
        institution_id = None
        if payload.institution_id is not None:
            # Same invariant as the manual link endpoint: only a real,
            # existing institution row can ever be linked — never trust the
            # client-supplied id as-is.
            if db.get(Institution, payload.institution_id) is None:
                raise InstitutionNotFoundError()
            institution_id = payload.institution_id
        db.add(Student(user_id=user.id, student_identifier=payload.student_identifier, institution_id=institution_id))

    elif payload.role == UserRole.INSTITUTION:
        if not payload.institution_id:
            raise MissingProfileFieldsError("institution_id is required for institution registration")
        institution = db.get(Institution, payload.institution_id)
        if institution is None:
            raise InstitutionNotFoundError()
        # Atomic conditional claim: a plain Core UPDATE (not an ORM attribute
        # assignment) whose WHERE clause re-checks user_id IS NULL at the moment
        # the database actually applies it. Postgres takes a row lock for this
        # UPDATE, so if two registrations race for the same institution, the
        # second one's UPDATE blocks until the first commits, then re-evaluates
        # the WHERE clause and matches zero rows — rowcount tells us which
        # happened, with no separate SELECT-then-write race window and no
        # extra locking machinery needed.
        result = db.execute(
            update(Institution).where(Institution.id == institution.id, Institution.user_id.is_(None)).values(user_id=user.id)
        )
        if result.rowcount == 0:
            raise InstitutionAlreadyClaimedError()
        db.refresh(institution)
        # Gives every claimed institution a stable signing identity at claim
        # time rather than lazily on first issuance — ensure_institution_keypair
        # is idempotent (a directory row imported with no keypair gets one now;
        # one that already has a public_key, e.g. re-claimed after a rejected
        # account was never re-registered, is left untouched), so this is safe
        # to call unconditionally here.
        signing_service.ensure_institution_keypair(db, institution)
        # Only a genuinely PENDING row needs admin's attention — a grandfathered/already-verified
        # directory row being claimed doesn't belong in the "awaiting review" notification.
        if institution.verification_status == VerificationStatus.PENDING:
            _notify_admins_of_pending_review(db, entity_type="institution", entity_id=institution.id, org_name=institution.name)

    elif payload.role == UserRole.VERIFIER:
        if not payload.company_id:
            raise MissingProfileFieldsError("company_id is required for verifier registration")
        company = db.get(Company, payload.company_id)
        if company is None:
            raise CompanyNotFoundError()
        result = db.execute(
            update(Company).where(Company.id == company.id, Company.user_id.is_(None)).values(user_id=user.id)
        )
        if result.rowcount == 0:
            raise CompanyAlreadyClaimedError()
        db.refresh(company)
        if company.verification_status == VerificationStatus.PENDING:
            _notify_admins_of_pending_review(db, entity_type="company", entity_id=company.id, org_name=company.name)

    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Raises InvalidCredentialsError for both "no such user" and "wrong
    password" — deliberately the same error, so a failed login never reveals
    whether an email is registered. Inactive-account status is only checked
    (and reported distinctly) AFTER the password has already matched, so
    that signal can't be used to enumerate accounts either.
    """
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise InactiveAccountError()
    return user
