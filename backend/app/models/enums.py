# ---------------------------------------------------------------------------
# Enums for role/status columns. Values (not Python member names) are what's
# stored in Postgres native enum types and are what the API/frontend see —
# kept as lowercase snake_case / the exact vocabulary the frontend already
# uses (types.ts) except where this phase's spec explicitly overrides it
# (Credential.status uses active/revoked/expired here, not the frontend's
# verified/pending/revoked — reconciled in the API layer in a later phase).
# ---------------------------------------------------------------------------

import enum


class UserRole(str, enum.Enum):
    STUDENT = "student"
    INSTITUTION = "institution"
    VERIFIER = "verifier"
    ADMIN = "admin"


class VerificationStatus(str, enum.Enum):
    """
    Trust status of a REGISTERED institution/company account (Phase A). Meaningless for a
    directory-only row (user_id IS NULL) — those never log in, never issue credentials, and
    never publish jobs, so they simply carry the column's default and it's never surfaced to
    anyone (see institution_service.to_response / company_service.to_response, which only
    expose this field when is_registered is True).
    """

    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class CredentialType(str, enum.Enum):
    DEGREE = "degree"
    TRANSCRIPT = "transcript"
    MIGRATION = "migration"
    INTERNSHIP = "internship"
    CERTIFICATION = "certification"
    COURSE = "course"
    OTHER = "other"


class CredentialStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CredentialRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"


class SharePermission(str, enum.Enum):
    VIEW_ONLY = "view_only"
    VIEW_DOWNLOAD = "view_download"


class InstitutionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"


class StudentDocumentStatus(str, enum.Enum):
    UNVERIFIED = "unverified"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class BlockchainAnchorStatus(str, enum.Enum):
    PENDING = "pending"
    ANCHORED = "anchored"
    FAILED = "failed"


class VerificationResultStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    UNAUTHORIZED = "UNAUTHORIZED"
    TYPE_MISMATCH = "TYPE_MISMATCH"


class JobEmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    CONTRACT = "contract"


class JobStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class ApplicationStatus(str, enum.Enum):
    APPLIED = "applied"
    UNDER_REVIEW = "under_review"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"
