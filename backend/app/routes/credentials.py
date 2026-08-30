import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.credential import Credential
from ..models.enums import UserRole
from ..models.user import User
from ..schemas.blockchain import AnchorResponse
from ..schemas.credential import CredentialResponse
from ..security.permissions import get_current_user, require_institution
from ..services import credential_service, document_service
from ..services.blockchain import anchoring_service
from ..services.credential_service import to_credential_response

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _to_anchor_response(credential: Credential) -> AnchorResponse:
    return AnchorResponse(
        credential_id=credential.id,
        status=credential.blockchain_status,
        transaction_hash=credential.blockchain_tx_hash,
        network=credential.blockchain_network,
        contract_address=credential.blockchain_contract_address,
        credential_hash=credential.blockchain_credential_hash,
        anchored_at=credential.blockchain_anchored_at,
    )


def _authorize_access(credential: Credential, user: User) -> None:
    """
    Per-role ownership check, independent of role-gating dependencies (any
    authenticated role can hit these routes; this decides whether THIS
    credential is theirs to see).
    """
    if user.role == UserRole.STUDENT:
        if user.student is None or credential.student_id != user.student.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this credential")
    elif user.role == UserRole.INSTITUTION:
        if user.institution is None or credential.institution_id != user.institution.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this credential")
    else:  # UserRole.VERIFIER
        # No share-based or public verification access exists yet — that's
        # Phase 5+ (authorized sharing) and Phase 6 (public verify). A
        # verifier has no path to any credential through this endpoint yet.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verifier access to a credential requires an authorized share (not yet implemented)",
        )


def _get_credential_or_404(db: Session, credential_id: uuid.UUID) -> Credential:
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return credential


@router.get("/{credential_id}", response_model=CredentialResponse, summary="Get one credential (owner student or issuing institution only)")
def get_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CredentialResponse:
    credential = _get_credential_or_404(db, credential_id)
    _authorize_access(credential, current_user)
    return to_credential_response(credential)


@router.get("/{credential_id}/document", summary="Download the credential's document (owner student or issuing institution only)")
def get_credential_document(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    credential = _get_credential_or_404(db, credential_id)
    _authorize_access(credential, current_user)

    if credential.document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No document on file for this credential")

    # storage_path is an internal DB value, never sent to the client — this
    # response streams file bytes back, it doesn't echo the path.
    try:
        exists = document_service.document_exists(credential.document.storage_path)
    except document_service.StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file is missing on this server")

    data = document_service.read_document(credential.document.storage_path)
    # Download filename is derived from the server-generated credential
    # identifier, not the client-supplied original_filename — avoids any
    # unsanitized user input reaching a response header.
    return Response(
        content=data,
        media_type=credential.document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{credential.credential_identifier}.pdf"'},
    )


@router.post(
    "/{credential_id}/revoke",
    response_model=CredentialResponse,
    summary="Institution revokes a credential it issued — status change only, never deletes the record, document, or signature",
)
def revoke_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> CredentialResponse:
    if current_user.institution is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No institution profile for this account")

    try:
        credential = credential_service.revoke_credential(db, current_user.institution, credential_id)
    except credential_service.CredentialNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    except credential_service.CredentialNotOwnedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This credential was not issued by your institution"
        )
    except credential_service.CredentialAlreadyRevokedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This credential has already been revoked")

    return to_credential_response(credential)


@router.post(
    "/{credential_id}/anchor",
    response_model=AnchorResponse,
    summary=(
        "Institution anchors a credential's hash on-chain (Phase 9A/9B, dev/testing tool). "
        "Idempotent: if already anchored, returns the existing anchor without submitting a new transaction."
    ),
)
def anchor_credential(
    credential_id: uuid.UUID,
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> AnchorResponse:
    if current_user.institution is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No institution profile for this account")

    try:
        credential = anchoring_service.anchor_credential(db, current_user.institution, credential_id)
    except anchoring_service.CredentialNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    except anchoring_service.CredentialNotOwnedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This credential was not issued by your institution"
        )
    except anchoring_service.CredentialRevokedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Revoked credentials cannot be anchored")
    except anchoring_service.BlockchainNotConfiguredForAnchoringError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blockchain anchoring is not configured on this server",
        )
    except anchoring_service.BlockchainAnchoringFailedError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Blockchain transaction failed")

    return _to_anchor_response(credential)
