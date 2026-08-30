import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CompanyProfileResponse(BaseModel):
    """
    A real company's public profile — every field here is a genuine database
    column, never fabricated placeholder text.

    is_registered distinguishes a directory listing (discoverable, no
    CredChain login — user_id is NULL, can never post jobs or receive
    applications) from a real registered CredChain employer (user_id is
    set) — computed fresh from the ORM row every time (see
    company_service.to_response), never a stored claim that could drift.
    """

    id: uuid.UUID
    name: str
    industry: str | None
    website: str | None
    description: str | None
    location: str | None
    company_size: str | None
    created_at: datetime
    country: str | None = None
    region: str | None = None
    city: str | None = None
    logo_url: str | None = None
    source: str | None = None
    is_registered: bool = False
    # Phase A: the REGISTERED account's trust state ("pending"|"verified"|"rejected"), only ever
    # non-null when is_registered is True — see InstitutionSummaryResponse's identical field for
    # the full rationale.
    verification_status: str | None = None
    # Not an ORM column — computed per-request (see company_service.to_response)
    # as a real count of this company's OPEN jobs, so the directory card/profile
    # can show it without the frontend fetching every job for every company.
    open_positions_count: int = 0

    model_config = {"from_attributes": True}


class UpdateCompanyProfileBody(BaseModel):
    """All optional — a PATCH-style update. Only the authenticated company's own row is ever touched (see routes/companies.py)."""

    industry: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=255)
    company_size: str | None = Field(default=None, max_length=50)
