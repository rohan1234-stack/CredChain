import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from ..models.enums import CredentialType, InstitutionRequestStatus


class CreateInstitutionRequestBody(BaseModel):
    institution_id: uuid.UUID
    credential_type: CredentialType
    custom_credential_name: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class CertificateRequestItemInput(BaseModel):
    credential_type: CredentialType
    custom_credential_name: str | None = None


class CreateInstitutionRequestBatchBody(BaseModel):
    institution_id: uuid.UUID
    items: list[CertificateRequestItemInput] = Field(min_length=1, max_length=10)
    reason: str | None = Field(default=None, max_length=1000)


class RejectInstitutionRequestBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class InstitutionCertificateRequestResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID | None
    student_id: uuid.UUID
    student_name: str
    student_identifier: str
    institution_id: uuid.UUID
    institution_name: str
    credential_type: CredentialType
    custom_credential_name: str | None
    reason: str | None
    status: InstitutionRequestStatus
    rejection_reason: str | None
    fulfilled_credential_id: uuid.UUID | None
    created_at: datetime
    responded_at: datetime | None
    # Only set when status == FULFILLED — the moment the institution actually issued the
    # credential that satisfies this request (the linked credential's own issued_at, never a
    # separate/new timestamp). None for PENDING, APPROVED, and REJECTED. See
    # institution_request_service.to_response for exactly how this is derived.
    fulfilled_at: datetime | None
