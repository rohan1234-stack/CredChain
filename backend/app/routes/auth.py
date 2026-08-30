from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..security import login_rate_limit
from ..security.jwt import create_access_token
from ..security.permissions import get_current_user
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _to_user_response(user: User) -> UserResponse:
    org_name = None
    if user.institution is not None:
        org_name = user.institution.name
    elif user.company is not None:
        org_name = user.company.name

    student_institution_id = None
    student_institution_name = None
    if user.student is not None and user.student.institution is not None:
        student_institution_id = user.student.institution.id
        student_institution_name = user.student.institution.name

    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        student_id=user.student.id if user.student else None,
        institution_id=user.institution.id if user.institution else None,
        company_id=user.company.id if user.company else None,
        org_name=org_name,
        student_institution_id=student_institution_id,
        student_institution_name=student_institution_name,
        # Phase A: lets the institution/company portal show its own trust status (pending/
        # verified/rejected) without a dedicated endpoint — None for every other role.
        institution_verification_status=user.institution.verification_status.value if user.institution else None,
        institution_rejection_reason=user.institution.rejection_reason if user.institution else None,
        company_verification_status=user.company.verification_status.value if user.company else None,
        company_rejection_reason=user.company.rejection_reason if user.company else None,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and the matching role profile (student/institution/company)",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = auth_service.register_user(db, payload)
    except auth_service.AdminSelfRegistrationError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This role cannot be self-registered")
    except auth_service.EmailAlreadyRegisteredError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")
    except auth_service.MissingProfileFieldsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except auth_service.InstitutionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected institution was not found")
    except auth_service.CompanyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected company was not found")
    except auth_service.InstitutionAlreadyClaimedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This institution already has a registered account.")
    except auth_service.CompanyAlreadyClaimedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This company already has a registered account.")

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, user=_to_user_response(user))


@router.post("/login", response_model=TokenResponse, summary="Exchange email + password for a JWT access token")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.lower()
    # request.client is None only in contexts with no real client connection (e.g. some test
    # harnesses) — fall back to a fixed key rather than crashing; the per-account counter alone
    # still protects that case.
    client_ip = request.client.host if request.client else "unknown"

    if login_rate_limit.is_locked_out(email=email, ip=client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )

    try:
        user = auth_service.authenticate_user(db, payload.email, payload.password)
    except auth_service.InvalidCredentialsError:
        login_rate_limit.record_failure(email=email, ip=client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    except auth_service.InactiveAccountError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    login_rate_limit.reset_account(email)
    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, user=_to_user_response(user))


@router.get("/me", response_model=UserResponse, summary="Return the authenticated user's profile")
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return _to_user_response(current_user)


@router.post("/logout", summary="Client-side token discard (stateless JWT — see note)")
def logout(current_user: User = Depends(get_current_user)) -> dict:
    """
    This is a stateless-JWT setup: the backend issues a signed token and
    never stores server-side session state, so there is nothing here to
    revoke. This endpoint exists to (a) confirm the caller presented a
    currently-valid token and (b) give the frontend one consistent place to
    call on logout. The actual "logout" is the frontend discarding the
    token — see src/lib/auth.ts. A deployment that needs the ability to
    immediately kill a specific token server-side (e.g. on account
    compromise) would need a token blocklist or a short-lived-token +
    refresh-token scheme; out of scope for this phase.
    """
    return {"detail": "Logged out. Discard the access token client-side."}
