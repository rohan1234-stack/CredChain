import uuid

from pydantic import BaseModel


class InstitutionSummaryResponse(BaseModel):
    """
    Public-safe institution profile — used both by a student choosing which
    institution to link during registration (name is enough there) and by
    the student Institution Directory/Profile pages (the rest of the
    fields). Deliberately excludes registration_number and public_key:
    neither is sensitive (institution id/name are already visible on every
    credential a student or verifier sees), but there's no reason to expose
    more than the public directory fields below.

    A row with no description/location/website/institution_type is a real
    institution that simply hasn't had those fields filled in yet (or was
    seeded/imported from a source that didn't have that field) — rendered as
    "not available", never fabricated.

    is_registered distinguishes a directory listing (discoverable, no
    CredChain login — user_id is NULL) from a real registered CredChain
    institution (user_id is set) — computed fresh from the ORM row every
    time (see institution_service.to_response), never a stored claim that
    could drift from the truth.

    verification_status (Phase A) is the REGISTERED account's trust state —
    "pending" | "verified" | "rejected" — and is only ever non-null when
    is_registered is True. A directory-only listing has no account to
    verify, so this stays None rather than exposing the column's internal
    'pending' default, which would misleadingly imply it's an account
    awaiting review.
    """

    id: uuid.UUID
    name: str
    description: str | None = None
    location: str | None = None
    website: str | None = None
    institution_type: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    logo_url: str | None = None
    source: str | None = None
    is_registered: bool = False
    verification_status: str | None = None

    model_config = {"from_attributes": True}
