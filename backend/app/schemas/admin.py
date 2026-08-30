# ---------------------------------------------------------------------------
# Phase A: minimal admin schemas — institution/company verification review
# only (see app/routes/admin.py). Contact email/name are included because an
# admin reviewing a registration genuinely needs them; neither is ever
# exposed on the public directory (InstitutionSummaryResponse/
# CompanyProfileResponse have no such field).
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PendingInstitutionResponse(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    website: str | None
    registration_number: str | None
    verification_status: str
    created_at: datetime
    contact_email: str | None
    contact_full_name: str | None

    model_config = {"from_attributes": True}


class PendingCompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    website: str | None
    industry: str | None
    verification_status: str
    created_at: datetime
    contact_email: str | None
    contact_full_name: str | None

    model_config = {"from_attributes": True}


class RejectVerificationBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
