import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.credential import Credential
from ..models.enums import CredentialType
from ..models.institution import Institution
from ..models.student import Student
from ..models.user import User
from ..schemas.credential import BulkIssuanceItemResponse, BulkIssuanceResponse, CredentialResponse, StudentSummaryResponse
from ..schemas.institution import InstitutionSummaryResponse
from ..schemas.institution_request import InstitutionCertificateRequestResponse, RejectInstitutionRequestBody
from ..schemas.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from ..schemas.student_document import ApproveStudentDocumentBody, RejectStudentDocumentBody, StudentDocumentResponse
from ..security.permissions import require_institution
from ..services import credential_service, document_service, institution_request_service, institution_service, signing_service, student_document_service
from ..services.credential_service import (
    CredentialValidationError,
    InstitutionNotVerifiedError,
    StudentNotAffiliatedError,
    StudentNotFoundError,
    to_credential_response,
)
from ..services.document_service import DocumentTooLargeError, EmptyDocumentError, UnsupportedDocumentTypeError

router = APIRouter(prefix="/api/institutions", tags=["institutions"])

# Honest, generic-on-purpose: never reveals which institution, which storage layer, or any
# path/key material — just that signing is unavailable and issuance can't proceed right now.
_SIGNING_KEY_UNAVAILABLE_DETAIL = (
    "This institution's signing key is currently unavailable on the server. "
    "Credential issuance is temporarily disabled — please contact CredChain support."
)


def _signing_key_unavailable_error() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_SIGNING_KEY_UNAVAILABLE_DETAIL)


@router.get(
    "",
    response_model=Page[InstitutionSummaryResponse],
    summary=(
        "Paginated, searchable institution directory — public. Used both to let a student pick a real "
        "institution to link to, and by the student Institution Directory (search/location/country/"
        "region/institution_type filters are additive; never a way to invent an institution). Scales to "
        "a globally-imported dataset (see scripts/import_institutions.py) — never returns the whole table."
    ),
)
def list_institutions(
    search: str | None = Query(default=None, description="Matches institution name, location, or city"),
    location: str | None = Query(default=None),
    country: str | None = Query(default=None, description="Exact match, e.g. 'India'"),
    region: str | None = Query(default=None, description="Substring match against state/province"),
    institution_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> Page[InstitutionSummaryResponse]:
    rows, total = institution_service.list_institutions(
        db, search=search, location=location, country=country, region=region, institution_type=institution_type, page=page, page_size=page_size
    )
    return institution_service.to_page_response(rows, total=total, page=page, page_size=page_size)


@router.get(
    "/{institution_id}",
    response_model=InstitutionSummaryResponse,
    summary="View one institution's public directory profile",
)
def get_institution(institution_id: uuid.UUID, db: Session = Depends(get_db)) -> InstitutionSummaryResponse:
    institution = institution_service.get_institution(db, institution_id)
    if institution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
    return institution_service.to_response(institution)


def _institution_of(current_user: User) -> Institution:
    """The authenticated institution's profile row — never trust an institution_id from the request body."""
    if current_user.institution is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No institution profile for this account")
    return current_user.institution


def _verification_error(exc: InstitutionNotVerifiedError) -> HTTPException:
    if exc.status.value == "rejected":
        detail = "Your institution's verification was rejected. Credentials cannot be issued."
    else:
        detail = "Your institution account is pending verification. Credentials cannot be issued until an administrator approves it."
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.get("/me/students", response_model=list[StudentSummaryResponse], summary="List students affiliated with the authenticated institution")
def list_my_students(
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> list[StudentSummaryResponse]:
    institution = _institution_of(current_user)
    students = db.query(Student).filter(Student.institution_id == institution.id).all()

    results = []
    for student in students:
        credential_count = (
            db.query(Credential)
            .filter(Credential.student_id == student.id, Credential.institution_id == institution.id)
            .count()
        )
        results.append(
            StudentSummaryResponse(
                id=student.id,
                user_id=student.user_id,
                full_name=student.user.full_name,
                student_identifier=student.student_identifier,
                credential_count=credential_count,
            )
        )
    return results


@router.get(
    "/me/students/lookup/{student_identifier}",
    response_model=StudentSummaryResponse,
    summary="Look up one of the institution's own students by their student identifier (manual-entry fallback for credential issuance)",
)
def lookup_my_student(
    student_identifier: str,
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> StudentSummaryResponse:
    """
    Deliberately scoped to this institution: a match on student_identifier
    for a student affiliated with a DIFFERENT institution (or with none at
    all) is reported as 404, identically to no match existing — this never
    becomes a way to discover or issue against a student outside the
    institution's own roster, preserving the same ownership boundary
    issue_credential already enforces.
    """
    institution = _institution_of(current_user)
    normalized = student_identifier.strip()
    student = (
        db.query(Student)
        .filter(func.lower(Student.student_identifier) == normalized.lower(), Student.institution_id == institution.id)
        .first()
    )
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found. The student must create a CredChain account and be affiliated with your institution before a credential can be issued.",
        )

    credential_count = (
        db.query(Credential)
        .filter(Credential.student_id == student.id, Credential.institution_id == institution.id)
        .count()
    )
    return StudentSummaryResponse(
        id=student.id,
        user_id=student.user_id,
        full_name=student.user.full_name,
        student_identifier=student.student_identifier,
        credential_count=credential_count,
    )


@router.get("/me/credentials", response_model=list[CredentialResponse], summary="List credentials issued by the authenticated institution")
def list_my_issued_credentials(
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> list[CredentialResponse]:
    institution = _institution_of(current_user)
    credentials = (
        db.query(Credential)
        .filter(Credential.institution_id == institution.id)
        .order_by(Credential.issued_at.desc())
        .all()
    )
    return [to_credential_response(c) for c in credentials]


@router.post(
    "/me/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new, digitally-signed credential to a student affiliated with this institution",
)
async def issue_credential(
    student_id: uuid.UUID = Form(...),
    credential_type: CredentialType = Form(...),
    title: str = Form(...),
    degree: str | None = Form(None),
    graduation_year: int | None = Form(None),
    cgpa: float | None = Form(None),
    document: UploadFile = File(...),
    fulfills_request_id: uuid.UUID | None = Form(None),
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> CredentialResponse:
    institution = _institution_of(current_user)

    try:
        credential = await credential_service.issue_credential(
            db,
            institution,
            student_id=student_id,
            credential_type=credential_type,
            title=title,
            degree=degree,
            graduation_year=graduation_year,
            cgpa=cgpa,
            document=document,
            fulfills_request_id=fulfills_request_id,
        )
    except StudentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    except StudentNotAffiliatedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This student is not affiliated with your institution"
        )
    except InstitutionNotVerifiedError as exc:
        raise _verification_error(exc)
    except signing_service.InstitutionKeyMissingError:
        raise _signing_key_unavailable_error()
    except CredentialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    except DocumentTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))  # 413 Payload Too Large (installed FastAPI's named constant is deprecated)
    except document_service.StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )
    except institution_request_service.RequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate request not found")
    except institution_request_service.RequestNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This request does not belong to your institution or this student")
    except institution_request_service.RequestAlreadyProcessedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This request is not in an approved, unfulfilled state")

    return to_credential_response(credential)


@router.post(
    "/me/credentials/bulk",
    response_model=BulkIssuanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue the same credential type/title to multiple students in one call — each student's OWN uploaded document, never a shared/reused file",
)
async def bulk_issue_credential(
    student_ids: list[uuid.UUID] = Form(...),
    credential_type: CredentialType = Form(...),
    title: str = Form(...),
    degree: str | None = Form(None),
    graduation_year: int | None = Form(None),
    cgpa: float | None = Form(None),
    documents: list[UploadFile] = File(...),
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> BulkIssuanceResponse:
    institution = _institution_of(current_user)

    if not student_ids:
        raise HTTPException(status_code=422, detail="Select at least one student")
    if len(student_ids) != len(documents):
        raise HTTPException(
            status_code=422,
            detail=f"Got {len(student_ids)} student(s) but {len(documents)} document(s) — each student needs exactly one document",
        )

    try:
        results = await credential_service.bulk_issue_credentials(
            db,
            institution,
            student_ids=student_ids,
            credential_type=credential_type,
            title=title,
            degree=degree,
            graduation_year=graduation_year,
            cgpa=cgpa,
            documents=documents,
        )
    except InstitutionNotVerifiedError as exc:
        raise _verification_error(exc)
    except signing_service.InstitutionKeyMissingError:
        raise _signing_key_unavailable_error()
    except CredentialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except document_service.StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )

    return BulkIssuanceResponse(
        results=[
            BulkIssuanceItemResponse(
                student_id=r.student_id,
                student_name=r.student_name,
                status=r.status,
                credential_id=r.credential.id if r.credential else None,
                error=r.error,
            )
            for r in results
        ]
    )


@router.get(
    "/me/certificate-requests",
    response_model=list[InstitutionCertificateRequestResponse],
    summary="List certificate requests students have sent to this institution",
)
def list_certificate_requests(
    current_user: User = Depends(require_institution), db: Session = Depends(get_db)
) -> list[InstitutionCertificateRequestResponse]:
    institution = _institution_of(current_user)
    requests = institution_request_service.list_for_institution(db, institution)
    return [institution_request_service.to_response(r) for r in requests]


@router.post(
    "/me/certificate-requests/{request_id}/approve",
    response_model=InstitutionCertificateRequestResponse,
    summary="Approve a student's certificate request — does NOT issue anything yet",
)
def approve_certificate_request(
    request_id: uuid.UUID, current_user: User = Depends(require_institution), db: Session = Depends(get_db)
) -> InstitutionCertificateRequestResponse:
    institution = _institution_of(current_user)
    try:
        request = institution_request_service.approve_request(db, institution, request_id)
    except institution_request_service.RequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    except institution_request_service.RequestNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This request was not sent to your institution")
    except institution_request_service.RequestAlreadyProcessedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This request has already been processed")
    return institution_request_service.to_response(request)


@router.post(
    "/me/certificate-requests/{request_id}/reject",
    response_model=InstitutionCertificateRequestResponse,
    summary="Reject a student's certificate request with a reason",
)
def reject_certificate_request(
    request_id: uuid.UUID,
    payload: RejectInstitutionRequestBody,
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> InstitutionCertificateRequestResponse:
    institution = _institution_of(current_user)
    try:
        request = institution_request_service.reject_request(db, institution, request_id, payload.reason)
    except institution_request_service.RequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    except institution_request_service.RequestNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This request was not sent to your institution")
    except institution_request_service.RequestAlreadyProcessedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This request has already been processed")
    return institution_request_service.to_response(request)


@router.get(
    "/me/documents",
    response_model=list[StudentDocumentResponse],
    summary="List documents students have uploaded for this institution to verify",
)
def list_student_documents(current_user: User = Depends(require_institution), db: Session = Depends(get_db)) -> list[StudentDocumentResponse]:
    institution = _institution_of(current_user)
    documents = student_document_service.list_for_institution(db, institution)
    return [student_document_service.to_response(d) for d in documents]


@router.get(
    "/me/documents/{document_id}",
    response_model=StudentDocumentResponse,
    summary="View one student-uploaded document's metadata — also transitions UNVERIFIED to UNDER_REVIEW",
)
def get_student_document(
    document_id: uuid.UUID, current_user: User = Depends(require_institution), db: Session = Depends(get_db)
) -> StudentDocumentResponse:
    institution = _institution_of(current_user)
    try:
        document = student_document_service.get_document_for_view(db, institution, document_id)
    except student_document_service.DocumentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    except student_document_service.DocumentNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This document was not uploaded for your institution")
    return student_document_service.to_response(document)


@router.get(
    "/me/documents/{document_id}/file",
    summary="Download the raw uploaded PDF for review (institution only, ownership-checked)",
)
def get_student_document_file(
    document_id: uuid.UUID, current_user: User = Depends(require_institution), db: Session = Depends(get_db)
) -> Response:
    institution = _institution_of(current_user)
    try:
        document = student_document_service.get_document_for_view(db, institution, document_id)
    except student_document_service.DocumentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    except student_document_service.DocumentNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This document was not uploaded for your institution")

    try:
        exists = document_service.document_exists(document.storage_path)
    except document_service.StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file is missing on this server")

    data = document_service.read_document(document.storage_path)
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.original_filename}"'},
    )


@router.post(
    "/me/documents/{document_id}/approve",
    response_model=StudentDocumentResponse,
    summary="Approve a student-uploaded document — creates a real, signed Credential through the same issuance pipeline as any other credential",
)
def approve_student_document(
    document_id: uuid.UUID,
    payload: ApproveStudentDocumentBody = ApproveStudentDocumentBody(),
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> StudentDocumentResponse:
    institution = _institution_of(current_user)
    try:
        document = student_document_service.approve_document(
            db,
            institution,
            document_id,
            degree=payload.degree,
            graduation_year=payload.graduation_year,
            cgpa=payload.cgpa,
        )
    except student_document_service.DocumentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    except student_document_service.DocumentNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This document was not uploaded for your institution")
    except student_document_service.DocumentAlreadyReviewedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This document has already been reviewed")
    except student_document_service.DocumentFileMissingError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded file is missing on this server")
    except document_service.StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )
    except InstitutionNotVerifiedError as exc:
        raise _verification_error(exc)
    except signing_service.InstitutionKeyMissingError:
        raise _signing_key_unavailable_error()
    except CredentialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return student_document_service.to_response(document)


@router.post(
    "/me/documents/{document_id}/reject",
    response_model=StudentDocumentResponse,
    summary="Reject a student-uploaded document with a reason",
)
def reject_student_document(
    document_id: uuid.UUID,
    payload: RejectStudentDocumentBody,
    current_user: User = Depends(require_institution),
    db: Session = Depends(get_db),
) -> StudentDocumentResponse:
    institution = _institution_of(current_user)
    try:
        document = student_document_service.reject_document(db, institution, document_id, payload.reason)
    except student_document_service.DocumentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    except student_document_service.DocumentNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This document was not uploaded for your institution")
    except student_document_service.DocumentAlreadyReviewedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This document has already been reviewed")
    return student_document_service.to_response(document)
