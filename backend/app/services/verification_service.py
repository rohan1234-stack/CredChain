# ---------------------------------------------------------------------------
# Real credential verification. Every check here is computed from scratch on
# every call — nothing is read from a request body, nothing is cached from a
# previous verification, nothing is a hardcoded True.
#
# Reuses Phase 4's credential_payload.py UNCHANGED — the canonical payload
# reconstructed here for signature verification is built by the exact same
# build_canonical_credential_payload()/canonicalize_credential_payload()
# functions Phase 4 used to produce the signature in the first place. If
# these two phases ever used different serialization logic, a perfectly
# legitimate credential could fail verification — this is the single most
# important invariant in this file.
# ---------------------------------------------------------------------------

import base64
import hmac
import uuid

from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.company import Company
from ..models.credential import Credential
from ..models.credential_request import CredentialRequest
from ..models.enums import CredentialStatus, CredentialType, VerificationResultStatus
from ..models.institution import Institution
from ..models.verification_event import VerificationEvent
from ..security import signatures
from . import authorization_service, document_service
from .blockchain.anchor_verification import check_blockchain_anchor
from .blockchain.client import BlockchainClient
from .credential_payload import build_canonical_credential_payload, canonicalize_credential_payload

# Maps the free-text labels the existing RequestCredentials.tsx checkboxes
# send (see CredentialRequest.requested_credentials) to real CredentialType
# values, case-insensitively. A label that doesn't match anything here
# (e.g. a genuinely custom ask) falls back to a substring match against the
# credential's own title in _requested_types_match — never a hard failure
# just because the vocabulary doesn't line up exactly.
_REQUEST_LABEL_TO_TYPE: dict[str, CredentialType] = {
    "degree": CredentialType.DEGREE,
    "transcript": CredentialType.TRANSCRIPT,
    "migration certificate": CredentialType.MIGRATION,
    "migration": CredentialType.MIGRATION,
    "internship certificate": CredentialType.INTERNSHIP,
    "internship": CredentialType.INTERNSHIP,
    "certification": CredentialType.CERTIFICATION,
    "course completion": CredentialType.COURSE,
    "course": CredentialType.COURSE,
}


def lookup_credential(db: Session, credential_id: uuid.UUID) -> Credential | None:
    return db.get(Credential, credential_id)


def lookup_issuer(credential: Credential) -> Institution:
    return credential.institution


def check_issuer_valid(institution: Institution | None) -> bool:
    """An issuer is 'valid' if it's a real institution record with a signing identity on file — without a public key there is nothing to verify a signature against."""
    return institution is not None and institution.public_key is not None


def reconstruct_canonical_payload(credential: Credential, *, cgpa_override: float | None = None) -> bytes:
    """
    Rebuilds the exact canonical payload that should have been signed at
    issuance, from the credential's CURRENT stored field values — this is
    what makes signature verification meaningful: if any signed field has
    changed since issuance, this payload no longer matches what the stored
    signature was computed over.

    cgpa_override exists ONLY for the tamper-demonstration path (see
    verify_credential's demo_cgpa_override) — it substitutes a different
    CGPA when reconstructing the payload, WITHOUT touching credential.cgpa
    or anything else in the database. Every other real verification call
    leaves this as None and uses the credential's real stored CGPA.
    """
    institution = credential.institution
    student = credential.student
    payload = build_canonical_credential_payload(
        credential_identifier=credential.credential_identifier,
        student_identifier=student.student_identifier,
        student_name=student.user.full_name,
        institution_identifier=str(institution.id),
        institution_name=institution.name,
        credential_type=credential.credential_type.value,
        title=credential.title,
        degree=credential.degree,
        graduation_year=credential.graduation_year,
        cgpa=cgpa_override if cgpa_override is not None else credential.cgpa,
        document_hash=credential.document_hash,
        issued_at=credential.issued_at,
    )
    return canonicalize_credential_payload(payload)


def check_signature(institution: Institution | None, credential: Credential, canonical_payload: bytes) -> bool:
    """Verifies credential.signature against canonical_payload using the institution's stored public key. Never regenerates a signature — only checks the one already on file."""
    if institution is None or institution.public_key is None or not credential.signature:
        return False
    try:
        signature_bytes = base64.b64decode(credential.signature)
    except (ValueError, TypeError):
        return False
    public_pem = institution.public_key.encode("utf-8")
    return signatures.verify(public_pem, canonical_payload, signature_bytes)


def check_document_integrity(credential: Credential) -> bool:
    """
    Re-reads the actual document bytes from private storage and compares a
    freshly-computed SHA-256 against credential.document_hash, using a
    constant-time comparison. This catches a DIFFERENT tamper vector than
    check_signature: someone replacing/corrupting the file in storage
    directly, without touching the database row at all (document_hash itself
    is part of the signed payload, so a change to the DB column is instead
    caught by check_signature — this function is specifically about the
    file's actual bytes vs. what the database and signature both claim they
    hash to).

    A credential with no document on file has nothing to contradict, so
    there's nothing to fail here (True) — Phase 4's issuance flow always
    attaches a document, so this is a defensive default for a case the
    current system can't actually produce, not an exploitable gap.

    Deliberately does NOT catch document_service.StorageUnavailableError —
    that means the storage backend itself couldn't be reached/queried, which
    is not evidence the document is missing or tampered. It propagates
    through verify_credential to the /verify route, which maps it to a
    distinct "try again" response rather than ever reaching this function's
    normal True/False result (see routes/verification.py) — a temporary
    Supabase outage must never make an otherwise correctly signed credential
    report INVALID.
    """
    document = credential.document
    if document is None or credential.document_hash is None:
        return True

    if not document_service.document_exists(document.storage_path):
        return False

    actual_hash = document_service.compute_sha256(document_service.read_document(document.storage_path))
    return hmac.compare_digest(actual_hash, credential.document_hash)


def check_status(credential: Credential) -> bool:
    return credential.status == CredentialStatus.ACTIVE


def _requested_types_match(requested_credentials: list[str], credential: Credential) -> bool:
    """True if the credential being verified is (or plausibly is) one of what was actually requested."""
    title_lower = credential.title.lower()
    for label in requested_credentials:
        normalized = label.strip().lower()
        mapped = _REQUEST_LABEL_TO_TYPE.get(normalized)
        if mapped is not None:
            if mapped == credential.credential_type:
                return True
        elif normalized in title_lower or title_lower in normalized:
            # Unmapped/custom label — fall back to a title match rather than
            # silently failing to recognize a legitimate custom request.
            return True
    return False


def check_type_mismatch(db: Session, company: Company, credential: Credential) -> bool:
    """
    True only when this credential was accessed through a ShareGrant tied to
    a specific company CredentialRequest, and the credential's type doesn't
    match anything that was actually requested. A grant with no linked
    request (nothing to mismatch against) or a grant whose request's labels
    do match never trips this.
    """
    grant = authorization_service.get_active_share_grant(db, company, credential)
    if grant is None or grant.credential_request_id is None:
        return False
    request = db.get(CredentialRequest, grant.credential_request_id)
    if request is None:
        return False
    return not _requested_types_match(request.requested_credentials, credential)


def get_requested_credentials_for_access(db: Session, company: Company, credential: Credential) -> list[str] | None:
    """The original request's requested_credentials labels, if this credential was accessed via a request-linked share — else None."""
    grant = authorization_service.get_active_share_grant(db, company, credential)
    if grant is None or grant.credential_request_id is None:
        return None
    request = db.get(CredentialRequest, grant.credential_request_id)
    return request.requested_credentials if request is not None else None


def determine_result(
    *,
    issuer_valid: bool,
    signature_valid: bool,
    integrity_valid: bool,
    credential_status: CredentialStatus,
    blockchain_status: str = "NOT_ANCHORED",
    type_mismatch: bool = False,
) -> VerificationResultStatus:
    """
    Called only once access has already been confirmed (UNAUTHORIZED and
    NOT_FOUND are decided earlier and never reach this function). Tampering
    (signature/integrity/issuer) is checked before status, since a forged or
    corrupted credential is INVALID regardless of what its status field
    claims — status only matters once the credential is proven authentic.

    blockchain_status only affects the result on MISMATCH (another tamper
    signal, checked alongside signature/integrity) — NOT_ANCHORED and
    UNAVAILABLE never downgrade an otherwise-valid credential, per Phase
    9C: the absence of a blockchain anchor (or a transient inability to
    check one) is not evidence of anything wrong. Defaults to
    "NOT_ANCHORED" so this function's behavior for every existing caller
    that doesn't pass blockchain_status is completely unchanged.

    type_mismatch (PS3 Phase F) only ever downgrades what would otherwise be
    VERIFIED — a revoked or expired credential still reports REVOKED/EXPIRED
    even if it also doesn't match what was requested, since that's the more
    specific and more important fact. Defaults to False, so every existing
    caller that doesn't pass it is unaffected.
    """
    if not issuer_valid or not signature_valid or not integrity_valid:
        return VerificationResultStatus.INVALID
    if blockchain_status == "MISMATCH":
        return VerificationResultStatus.INVALID
    if credential_status == CredentialStatus.REVOKED:
        return VerificationResultStatus.REVOKED
    if credential_status == CredentialStatus.EXPIRED:
        return VerificationResultStatus.EXPIRED
    if type_mismatch:
        return VerificationResultStatus.TYPE_MISMATCH
    return VerificationResultStatus.VERIFIED


def _all_false_checks() -> dict:
    return {"issuer": False, "signature": False, "integrity": False, "status": False, "access": False}


def _minimal_credential_view(credential: Credential) -> dict:
    """Only what a verifier UI needs to display — no student PII beyond what's on the credential itself, no internal IDs, no storage paths."""
    return {
        "credential_identifier": credential.credential_identifier,
        "credential_type": credential.credential_type,
        "title": credential.title,
        "degree": credential.degree,
        "graduation_year": credential.graduation_year,
        "cgpa": float(credential.cgpa) if credential.cgpa is not None else None,
        "institution_name": credential.institution.name,
    }


def _record_event(db: Session, credential: Credential, company: Company, result: VerificationResultStatus, checks: dict) -> None:
    db.add(
        VerificationEvent(
            credential_id=credential.id,
            company_id=company.id,
            result=result,
            issuer_valid=checks["issuer"],
            signature_valid=checks["signature"],
            integrity_valid=checks["integrity"],
            status_valid=checks["status"],
            access_valid=checks["access"],
        )
    )
    db.commit()


def _log_activity(db: Session, company: Company, *, entity_id: uuid.UUID | None, metadata: dict) -> None:
    db.add(
        ActivityLog(
            actor_user_id=company.user_id,
            action="CREDENTIAL_VERIFIED",
            entity_type="credential",
            entity_id=entity_id,
            metadata_=metadata,
        )
    )
    db.commit()


def verify_credential(
    db: Session,
    company: Company,
    credential_id: uuid.UUID,
    *,
    demo_cgpa_override: float | None = None,
    blockchain_client: BlockchainClient | None = None,
) -> dict:
    """
    The single entry point Phase 5's route calls. Returns the structured
    {result, checks, credential} dict; persists a VerificationEvent (for
    every outcome where a real credential was found — UNAUTHORIZED included)
    and an ActivityLog entry (for every attempt, NOT_FOUND included) as a
    side effect.

    NOT_FOUND gets no VerificationEvent: that table's credential_id is a
    NOT NULL foreign key, so there is no valid row to attach one to for an
    id that doesn't exist. An ActivityLog entry is still written (its
    entity_id column is a bare UUID, not FK-constrained) so the attempt
    itself is auditable.
    """
    credential = lookup_credential(db, credential_id)
    if credential is None:
        _log_activity(db, company, entity_id=credential_id, metadata={"result": "NOT_FOUND"})
        return {"result": "NOT_FOUND", "checks": _all_false_checks(), "credential": None, "blockchain": None}

    access_valid = authorization_service.is_verifier_authorized(db, company, credential)
    if not access_valid:
        checks = _all_false_checks()
        _record_event(db, credential, company, VerificationResultStatus.UNAUTHORIZED, checks)
        _log_activity(db, company, entity_id=credential.id, metadata={"result": "UNAUTHORIZED"})
        return {"result": "UNAUTHORIZED", "checks": checks, "credential": None, "blockchain": None}

    institution = lookup_issuer(credential)
    issuer_valid = check_issuer_valid(institution)

    canonical_payload = reconstruct_canonical_payload(credential, cgpa_override=demo_cgpa_override)
    signature_valid = check_signature(institution, credential, canonical_payload)

    integrity_valid = check_document_integrity(credential)
    status_valid = check_status(credential)

    # Phase 9C: an additional, independent check — never a transaction,
    # never able to bypass anything above. See
    # blockchain/anchor_verification.py for exactly what ANCHORED /
    # NOT_ANCHORED / MISMATCH / UNAVAILABLE each mean.
    blockchain = check_blockchain_anchor(credential, client=blockchain_client)

    type_mismatch = check_type_mismatch(db, company, credential)
    requested_credentials = get_requested_credentials_for_access(db, company, credential)

    result = determine_result(
        issuer_valid=issuer_valid,
        signature_valid=signature_valid,
        integrity_valid=integrity_valid,
        credential_status=credential.status,
        blockchain_status=blockchain["status"],
        type_mismatch=type_mismatch,
    )

    checks = {
        "issuer": issuer_valid,
        "signature": signature_valid,
        "integrity": integrity_valid,
        "status": status_valid,
        "access": access_valid,
    }

    _record_event(db, credential, company, result, checks)
    _log_activity(
        db,
        company,
        entity_id=credential.id,
        metadata={
            "result": result.value,
            "demo_override": demo_cgpa_override is not None,
            "blockchain_status": blockchain["status"],
            "type_mismatch": type_mismatch,
        },
    )

    return {
        "result": result.value,
        "checks": checks,
        "credential": _minimal_credential_view(credential),
        "blockchain": blockchain,
        "requested_credentials": requested_credentials,
    }
