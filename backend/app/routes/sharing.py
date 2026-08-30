import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..config import settings
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from ..schemas.sharing import (
    SHARED_CREDENTIAL_STATUS_FILTERS,
    CreateDirectShareBody,
    ShareCreatedResponse,
    ShareGrantResponse,
    SharedCredentialItem,
    ShareTokenAccessResponse,
)
from ..security.permissions import require_student, require_verifier
from ..services import sharing_service

router = APIRouter(prefix="/api/shares", tags=["sharing"])
# Separate router: /api/students/me/shares and /api/companies/me/shares don't
# fit the /api/shares/* prefix shape, but belong in this module conceptually.
me_router = APIRouter(tags=["sharing"])


@router.get(
    "/verify/{token}",
    response_model=ShareTokenAccessResponse,
    summary="Preview what a share link grants — the token itself is the authorization, no login required",
)
def access_share(token: str, db: Session = Depends(get_db)) -> ShareTokenAccessResponse:
    """
    Deliberately unauthenticated: this mirrors a normal "anyone with the
    link can view" share-link/QR pattern — the 256-bit token is what makes
    it safe, not a login wall. This endpoint is READ-ONLY and minimal; it
    does not perform or claim cryptographic verification. Proving a
    credential is authentic is still POST /api/verification/verify (Phase
    5), which additionally requires the caller to be authenticated as the
    exact company the share was created for (see authorization_service.py,
    unchanged by this phase).
    """
    try:
        grant = sharing_service.access_share_by_token(db, token)
    except sharing_service.InvalidShareTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid share token")
    except sharing_service.ShareRevokedError:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This share has been revoked")
    except sharing_service.ShareExpiredError:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This share has expired")

    share_response = sharing_service.to_share_grant_response(grant)
    return ShareTokenAccessResponse(
        company_name=share_response.company_name,
        expires_at=share_response.expires_at,
        credentials=share_response.credentials,
        permission=share_response.permission,
    )


@router.post("/{share_id}/revoke", response_model=ShareGrantResponse, summary="Student revokes an active share — audit history is preserved, not deleted")
def revoke_share(
    share_id: uuid.UUID, current_user: User = Depends(require_student), db: Session = Depends(get_db)
) -> ShareGrantResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    try:
        grant = sharing_service.revoke_share(db, current_user.student, share_id)
    except sharing_service.ShareNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    except sharing_service.ShareNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This share does not belong to you")
    except sharing_service.ShareAlreadyRevokedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This share has already been revoked")
    return sharing_service.to_share_grant_response(grant)


@me_router.post(
    "/api/students/me/shares",
    response_model=ShareCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Student shares credentials directly with a real company — no prior request required. Same ShareGrant architecture as approving a request.",
)
def create_direct_share(
    payload: CreateDirectShareBody,
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> ShareCreatedResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    try:
        grant, raw_token = sharing_service.create_direct_share(
            db,
            current_user.student,
            company_id=payload.company_id,
            credential_ids=payload.credential_ids,
            expires_in_days=payload.expires_in_days,
            permission=payload.permission,
        )
    except sharing_service.CompanyNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    except sharing_service.CompanyNotRegisteredError:
        raise HTTPException(
            status_code=422,
            detail="This company is a directory listing only and has no CredChain account to receive a share. Choose a registered company instead.",
        )
    except sharing_service.InvalidExpiryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except sharing_service.CredentialSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    share_response = sharing_service.to_share_grant_response(grant)
    share_url = f"{settings.frontend_base_url}/share/verify/{raw_token}"
    return ShareCreatedResponse(share=share_response, share_token=raw_token, share_url=share_url)


@me_router.get("/api/students/me/shares", response_model=list[ShareGrantResponse])
def list_my_shares_as_student(
    current_user: User = Depends(require_student), db: Session = Depends(get_db)
) -> list[ShareGrantResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    return [sharing_service.to_share_grant_response(g) for g in sharing_service.list_shares_for_student(db, current_user.student)]


@me_router.get("/api/companies/me/shares", response_model=list[ShareGrantResponse])
def list_my_shares_as_company(
    current_user: User = Depends(require_verifier), db: Session = Depends(get_db)
) -> list[ShareGrantResponse]:
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    return [sharing_service.to_share_grant_response(g) for g in sharing_service.list_shares_for_company(db, current_user.company)]


@me_router.get(
    "/api/companies/me/shared-credentials",
    response_model=Page[SharedCredentialItem],
    summary=(
        "The company's paginated, searchable 'Credentials Shared With You' inbox — one row per "
        "(share, credential), scoped to this company's own canonical company_id only. Never "
        "loads more than one page; never includes another company's shares."
    ),
)
def list_my_shared_credentials(
    search: str | None = Query(default=None, description="Matches student name, credential title/type, or institution name"),
    status_filter: str | None = Query(default=None, alias="status", description=f"One of {SHARED_CREDENTIAL_STATUS_FILTERS}"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(require_verifier),
    db: Session = Depends(get_db),
) -> Page[SharedCredentialItem]:
    if current_user.company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company profile for this account")
    try:
        items, total = sharing_service.list_shared_credentials_for_company(
            db, current_user.company, search=search, status=status_filter, page=page, page_size=page_size
        )
    except sharing_service.InvalidSharedCredentialStatusFilterError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return sharing_service.to_shared_credentials_page_response(items, total=total, page=page, page_size=page_size)
