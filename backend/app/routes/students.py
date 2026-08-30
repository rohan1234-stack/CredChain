import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.credential import Credential
from ..models.enums import CredentialType
from ..models.user import User
from ..schemas.credential import CredentialResponse
from ..schemas.institution_request import (
    CreateInstitutionRequestBatchBody,
    CreateInstitutionRequestBody,
    InstitutionCertificateRequestResponse,
)
from ..schemas.job_application import ApplyToJobBody, StudentApplicationResponse
from ..schemas.student_document import StudentDocumentResponse
from ..security.permissions import require_student
from ..services import institution_request_service, job_application_service, sharing_service, student_document_service, student_service
from ..services.credential_service import to_credential_response
from ..services.document_service import DocumentTooLargeError, EmptyDocumentError, StorageUnavailableError, UnsupportedDocumentTypeError

router = APIRouter(prefix="/api/students", tags=["students"])


class LinkInstitutionRequest(BaseModel):
    institution_id: uuid.UUID


class LinkInstitutionResponse(BaseModel):
    institution_id: uuid.UUID
    institution_name: str


@router.post(
    "/me/institution",
    response_model=LinkInstitutionResponse,
    summary="Link (or change) the authenticated student's institution — the id is always validated against real institution rows",
)
def link_institution(
    payload: LinkInstitutionRequest,
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> LinkInstitutionResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    try:
        student = student_service.link_student_to_institution(db, current_user.student, payload.institution_id)
    except student_service.InstitutionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected institution was not found")

    return LinkInstitutionResponse(institution_id=student.institution_id, institution_name=student.institution.name)


@router.get("/me/credentials", response_model=list[CredentialResponse], summary="List the authenticated student's own credentials")
def my_credentials(
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> list[CredentialResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    credentials = (
        db.query(Credential)
        .filter(Credential.student_id == current_user.student.id)
        .order_by(Credential.issued_at.desc())
        .all()
    )
    return [to_credential_response(c) for c in credentials]


@router.post(
    "/me/certificate-requests",
    response_model=InstitutionCertificateRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a certificate from the student's own linked institution",
)
def create_certificate_request(
    payload: CreateInstitutionRequestBody,
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> InstitutionCertificateRequestResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    try:
        request = institution_request_service.create_request(
            db,
            current_user.student,
            institution_id=payload.institution_id,
            credential_type=payload.credential_type,
            custom_credential_name=payload.custom_credential_name,
            reason=payload.reason,
        )
    except institution_request_service.NotAffiliatedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request certificates from the institution you're linked to",
        )

    return institution_request_service.to_response(request)


@router.post(
    "/me/certificate-requests/batch",
    response_model=list[InstitutionCertificateRequestResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Request multiple certificates from the student's own linked institution in one submission",
)
def create_certificate_request_batch(
    payload: CreateInstitutionRequestBatchBody,
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> list[InstitutionCertificateRequestResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    try:
        requests = institution_request_service.create_request_batch(
            db,
            current_user.student,
            institution_id=payload.institution_id,
            items=[(item.credential_type, item.custom_credential_name) for item in payload.items],
            reason=payload.reason,
        )
    except institution_request_service.NotAffiliatedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request certificates from the institution you're linked to",
        )

    return [institution_request_service.to_response(r) for r in requests]


@router.get(
    "/me/certificate-requests",
    response_model=list[InstitutionCertificateRequestResponse],
    summary="List the authenticated student's own certificate requests",
)
def list_my_certificate_requests(
    current_user: User = Depends(require_student), db: Session = Depends(get_db)
) -> list[InstitutionCertificateRequestResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    requests = institution_request_service.list_for_student(db, current_user.student)
    return [institution_request_service.to_response(r) for r in requests]


@router.post(
    "/me/documents",
    response_model=StudentDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document the student already possesses, for the student's own institution to review — starts UNVERIFIED",
)
async def upload_document(
    institution_id: uuid.UUID = Form(...),
    credential_type: CredentialType = Form(...),
    custom_credential_name: str | None = Form(None),
    document: UploadFile = File(...),
    current_user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> StudentDocumentResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    try:
        record = await student_document_service.upload_document(
            db,
            current_user.student,
            institution_id=institution_id,
            credential_type=credential_type,
            custom_credential_name=custom_credential_name,
            document=document,
        )
    except student_document_service.NotAffiliatedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only upload documents for the institution you're linked to",
        )
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    except DocumentTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable. Please try again shortly.",
        )

    return student_document_service.to_response(record)


@router.get(
    "/me/documents",
    response_model=list[StudentDocumentResponse],
    summary="List the authenticated student's own uploaded documents",
)
def list_my_documents(current_user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[StudentDocumentResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    documents = student_document_service.list_for_student(db, current_user.student)
    return [student_document_service.to_response(d) for d in documents]


@router.post(
    "/me/applications",
    response_model=StudentApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply to a real, open job — only with credentials the student actually owns; drives the existing credential-request/share pipeline",
)
def apply_to_job(
    payload: ApplyToJobBody, current_user: User = Depends(require_student), db: Session = Depends(get_db)
) -> StudentApplicationResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")

    try:
        application = job_application_service.apply_to_job(
            db, current_user.student, job_id=payload.job_id, credential_ids=payload.credential_ids
        )
    except job_application_service.JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    except job_application_service.JobNotOpenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This job is not currently open for applications")
    except job_application_service.ApplicationDeadlinePassedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The application deadline for this job has passed")
    except job_application_service.AlreadyAppliedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already applied to this job")
    except sharing_service.CredentialSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return job_application_service.to_student_response(db, application)


@router.get(
    "/me/applications",
    response_model=list[StudentApplicationResponse],
    summary="List the authenticated student's own job applications",
)
def list_my_applications(current_user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[StudentApplicationResponse]:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    applications = job_application_service.list_for_student(db, current_user.student)
    return [job_application_service.to_student_response(db, a) for a in applications]


@router.post(
    "/me/applications/{application_id}/withdraw",
    response_model=StudentApplicationResponse,
    summary="Student withdraws their own application — only from a non-final state; an ACCEPTED offer cannot be silently withdrawn through this path",
)
def withdraw_application(
    application_id: uuid.UUID, current_user: User = Depends(require_student), db: Session = Depends(get_db)
) -> StudentApplicationResponse:
    if current_user.student is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No student profile for this account")
    try:
        application = job_application_service.withdraw_application(db, current_user.student, application_id)
    except job_application_service.ApplicationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    except job_application_service.ApplicationNotOwnedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This application does not belong to you")
    except job_application_service.WithdrawalNotAllowedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This application can no longer be withdrawn")
    return job_application_service.to_student_response(db, application)
