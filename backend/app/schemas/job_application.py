import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from ..models.enums import ApplicationStatus
from .job import EligibilityResult
from .sharing import CredentialRequestResponse


class ApplyToJobBody(BaseModel):
    job_id: uuid.UUID
    # Only credentials the student actually owns — enforced by the existing,
    # unmodified sharing_service.approve_request ownership check.
    credential_ids: list[uuid.UUID] = Field(min_length=1)


class UpdateApplicationStatusBody(BaseModel):
    status: ApplicationStatus
    # Required (non-empty) when status == REJECTED — enforced in the route,
    # not just here, since Pydantic can't see the sibling field's value
    # cheaply. Never used for any other transition.
    reason: str | None = Field(default=None, max_length=1000)


class ApplicationHistoryEntry(BaseModel):
    """
    One real, already-recorded status transition — built entirely from an
    ActivityLog row this application's own service functions already write
    (see job_application_service.get_application_history). Never a fabricated
    step: a status this application never actually passed through (e.g.
    UNDER_REVIEW on a fast APPLIED -> REJECTED) simply has no entry here.
    """

    status: ApplicationStatus
    occurred_at: datetime


class StudentApplicationResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID
    company_name: str
    status: ApplicationStatus
    rejection_reason: str | None
    created_at: datetime
    history: list[ApplicationHistoryEntry]


class CompanyApplicationResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    student_id: uuid.UUID
    student_name: str
    student_identifier: str
    status: ApplicationStatus
    rejection_reason: str | None
    created_at: datetime
    history: list[ApplicationHistoryEntry]
    # Reuses the EXISTING CredentialRequestResponse shape (requested_credentials
    # + shared_credentials) — the same "Requested X / Received Y" data a
    # direct company credential request already surfaces. None only if the
    # underlying request was somehow removed (SET NULL on delete).
    credential_request: CredentialRequestResponse | None
    # The applicant's real deterministic eligibility against THIS job —
    # computed fresh via the same single-source-of-truth eligibility_service
    # the student's own job page uses. Never a second, company-side
    # eligibility computation; never AI. Lets a company see ELIGIBLE /
    # NOT_ELIGIBLE / INCOMPLETE without opening a separate page.
    eligibility: EligibilityResult
