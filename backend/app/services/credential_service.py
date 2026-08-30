# ---------------------------------------------------------------------------
# Credential issuance orchestration — the real version of what the
# frontend's mock issueCredential() used to fake with a setTimeout.
#
# Order of operations matters here (see issue_credential): validate first,
# hash the document, sign the canonical payload, THEN write to disk, THEN
# write to the database, and only commit once every DB row is staged. If
# anything fails after the file is written but before commit, the file is
# deleted — no orphaned document without a corresponding credential row.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.credential import Credential
from ..models.credential_document import CredentialDocument
from ..models.enums import CredentialStatus, CredentialType, VerificationStatus
from ..models.institution import Institution
from ..models.student import Student
from ..schemas.credential import CredentialResponse
from . import document_service, notification_service, signing_service
from .credential_payload import build_canonical_credential_payload, canonicalize_credential_payload

MIN_CGPA, MAX_CGPA = 0, 10
MIN_GRADUATION_YEAR, MAX_GRADUATION_YEAR = 1950, 2100


class StudentNotFoundError(Exception):
    pass


class StudentNotAffiliatedError(Exception):
    pass


class CredentialValidationError(Exception):
    pass


class CredentialNotFoundError(Exception):
    pass


class CredentialNotOwnedError(Exception):
    pass


class CredentialAlreadyRevokedError(Exception):
    pass


class InstitutionNotVerifiedError(Exception):
    """
    Raised by issue_signed_credential — the single real chokepoint every issuance path converges
    on (direct issuance, bulk issuance, and student_document_service.approve_document all call
    this function) — when the issuing institution's account is not VERIFIED. Carries the actual
    status so callers can give a specific, honest message (pending vs. rejected) rather than a
    generic "forbidden".
    """

    def __init__(self, status: VerificationStatus) -> None:
        self.status = status
        super().__init__(f"institution verification status is {status.value}, not verified")


def _validate_fields(title: str, graduation_year: int | None, cgpa: float | None) -> None:
    if not title or not title.strip():
        raise CredentialValidationError("title is required")
    if cgpa is not None and not (MIN_CGPA <= cgpa <= MAX_CGPA):
        raise CredentialValidationError(f"cgpa must be between {MIN_CGPA} and {MAX_CGPA}")
    if graduation_year is not None and not (MIN_GRADUATION_YEAR <= graduation_year <= MAX_GRADUATION_YEAR):
        raise CredentialValidationError(
            f"graduation_year must be between {MIN_GRADUATION_YEAR} and {MAX_GRADUATION_YEAR}"
        )


def issue_signed_credential(
    db: Session,
    institution: Institution,
    student: Student,
    *,
    credential_type: CredentialType,
    title: str,
    degree: str | None,
    graduation_year: int | None,
    cgpa: float | None,
    document_bytes: bytes,
    original_filename: str,
    content_type: str,
) -> Credential:
    """
    The actual signing/persist core, shared by every path that ends in a
    real institution-signed Credential row: single issuance, bulk issuance,
    and (Phase D) approving a student-uploaded document. Takes already-read,
    already-validated document bytes — callers are responsible for that
    (see document_service.read_and_validate_pdf) since the source differs
    (a fresh UploadFile vs. bytes already on disk from a prior upload).

    Phase A: refuses to mint anything unless the institution's account is VERIFIED — the one
    real gate every issuance path (single, bulk, document-approval) shares.
    """
    if institution.verification_status != VerificationStatus.VERIFIED:
        raise InstitutionNotVerifiedError(institution.verification_status)

    document_hash = document_service.compute_sha256(document_bytes)

    # Idempotent — no-ops if this institution already has a stable signing identity.
    signing_service.ensure_institution_keypair(db, institution)

    credential_id = uuid.uuid4()
    credential_identifier = f"CRD-{uuid.uuid4()}"
    issued_at = datetime.now(timezone.utc)

    payload = build_canonical_credential_payload(
        credential_identifier=credential_identifier,
        student_identifier=student.student_identifier,
        student_name=student.user.full_name,
        institution_identifier=str(institution.id),
        institution_name=institution.name,
        credential_type=credential_type.value,
        title=title,
        degree=degree,
        graduation_year=graduation_year,
        cgpa=cgpa,
        document_hash=document_hash,
        issued_at=issued_at,
    )
    canonical_bytes = canonicalize_credential_payload(payload)
    signature_b64 = signing_service.sign_credential_payload(institution, canonical_bytes)

    storage_path: str | None = None
    try:
        # File first — if this succeeds but the DB write below fails, the
        # except block below deletes it. If the DB write succeeds but this
        # somehow failed first, we'd never reach the DB write at all, so
        # there's no window where a credential row exists without a file.
        storage_path = document_service.save_document(credential_id, document_bytes)

        credential = Credential(
            id=credential_id,
            credential_identifier=credential_identifier,
            student_id=student.id,
            institution_id=institution.id,
            credential_type=credential_type,
            title=title,
            degree=degree,
            graduation_year=graduation_year,
            cgpa=cgpa,
            status=CredentialStatus.ACTIVE,
            issued_at=issued_at,
            document_hash=document_hash,
            signature=signature_b64,
        )
        db.add(credential)
        db.flush()

        db.add(
            CredentialDocument(
                credential_id=credential.id,
                original_filename=original_filename or "document.pdf",
                storage_path=storage_path,
                mime_type=content_type or "application/pdf",
                file_size=len(document_bytes),
                content_hash=document_hash,
            )
        )

        log = ActivityLog(
            actor_user_id=institution.user_id,
            action="CREDENTIAL_ISSUED",
            entity_type="credential",
            entity_id=credential.id,
            metadata_={"credential_identifier": credential_identifier, "student_id": str(student.id)},
        )
        db.add(log)
        db.flush()

        notification_service.create_notification(
            db,
            user_id=student.user_id,
            title="Credential issued",
            message=f"{institution.name} issued you a credential: {title}",
            activity_log_id=log.id,
            link_entity_type="credential",
            link_entity_id=credential.id,
        )

        db.commit()
        db.refresh(credential)
        return credential

    except Exception:
        db.rollback()
        if storage_path is not None:
            document_service.delete_document_if_exists(storage_path)
        raise


def _get_affiliated_student(db: Session, institution: Institution, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise StudentNotFoundError()
    # The authorization check that actually matters: an institution can only
    # issue to students affiliated with it, regardless of what the frontend
    # sent — never trust student_id -> institution_id ownership implicitly.
    if student.institution_id != institution.id:
        raise StudentNotAffiliatedError()
    return student


async def issue_credential(
    db: Session,
    institution: Institution,
    *,
    student_id: uuid.UUID,
    credential_type: CredentialType,
    title: str,
    degree: str | None,
    graduation_year: int | None,
    cgpa: float | None,
    document: UploadFile,
    fulfills_request_id: uuid.UUID | None = None,
) -> Credential:
    _validate_fields(title, graduation_year, cgpa)
    student = _get_affiliated_student(db, institution, student_id)

    # Resolve BEFORE signing anything — an invalid fulfills_request_id
    # should fail loudly, not silently issue an unlinked credential.
    fulfilled_request = None
    if fulfills_request_id is not None:
        from . import institution_request_service  # local import: avoids a service-to-service import cycle at module load time

        fulfilled_request = institution_request_service.get_approved_request_for_fulfillment(
            db, institution, student.id, fulfills_request_id
        )

    document_bytes = await document_service.read_and_validate_pdf(document)
    credential = issue_signed_credential(
        db,
        institution,
        student,
        credential_type=credential_type,
        title=title,
        degree=degree,
        graduation_year=graduation_year,
        cgpa=cgpa,
        document_bytes=document_bytes,
        original_filename=document.filename or "document.pdf",
        content_type=document.content_type or "application/pdf",
    )

    if fulfilled_request is not None:
        from . import institution_request_service

        institution_request_service.mark_fulfilled(db, fulfilled_request, credential.id)

    return credential


class BulkIssuanceItemResult:
    def __init__(self, *, student_id: uuid.UUID, student_name: str | None, status: str, credential: Credential | None = None, error: str | None = None):
        self.student_id = student_id
        self.student_name = student_name
        self.status = status
        self.credential = credential
        self.error = error


async def bulk_issue_credentials(
    db: Session,
    institution: Institution,
    *,
    student_ids: list[uuid.UUID],
    credential_type: CredentialType,
    title: str,
    degree: str | None,
    graduation_year: int | None,
    cgpa: float | None,
    documents: list[UploadFile],
) -> list[BulkIssuanceItemResult]:
    """
    Issues the same credential type/title/metadata to multiple students in
    one call, each with its OWN uploaded document — student_ids[i] pairs
    with documents[i]. Every item is isolated: one student's failure (bad
    PDF, not affiliated, validation error) never aborts or rolls back
    another student's already-issued credential. Never claims batch-wide
    success — the caller gets a per-item result list.

    Phase A: the verification gate is checked once, upfront, for the whole batch, so an
    unverified institution gets one clear error instead of N identical per-item failures.
    """
    if institution.verification_status != VerificationStatus.VERIFIED:
        raise InstitutionNotVerifiedError(institution.verification_status)
    _validate_fields(title, graduation_year, cgpa)

    results: list[BulkIssuanceItemResult] = []
    for student_id, document in zip(student_ids, documents):
        try:
            student = _get_affiliated_student(db, institution, student_id)
            document_bytes = await document_service.read_and_validate_pdf(document)
            credential = issue_signed_credential(
                db,
                institution,
                student,
                credential_type=credential_type,
                title=title,
                degree=degree,
                graduation_year=graduation_year,
                cgpa=cgpa,
                document_bytes=document_bytes,
                original_filename=document.filename or "document.pdf",
                content_type=document.content_type or "application/pdf",
            )
            results.append(
                BulkIssuanceItemResult(
                    student_id=student_id, student_name=student.user.full_name, status="issued", credential=credential
                )
            )
        except StudentNotFoundError:
            results.append(BulkIssuanceItemResult(student_id=student_id, student_name=None, status="failed", error="Student not found"))
        except StudentNotAffiliatedError:
            results.append(
                BulkIssuanceItemResult(
                    student_id=student_id, student_name=None, status="failed", error="Student is not affiliated with your institution"
                )
            )
        except signing_service.InstitutionKeyMissingError:
            # Not a per-item problem (unlike a bad PDF or an unaffiliated student) — every
            # remaining item in this batch would fail identically, and the honest, non-leaky
            # 503 message belongs at the route level, not stuffed into individual item errors.
            raise
        except document_service.StorageUnavailableError:
            # Same reasoning as InstitutionKeyMissingError above: a storage outage isn't
            # specific to this one student's document — every remaining item would fail
            # identically, so this aborts the whole batch for one honest 503 at the route
            # level instead of N misleading per-item "failed" results.
            raise
        except Exception as exc:  # noqa: BLE001 — deliberately broad: one bad item must never abort the batch
            results.append(BulkIssuanceItemResult(student_id=student_id, student_name=None, status="failed", error=str(exc)))

    return results


def revoke_credential(db: Session, institution: Institution, credential_id: uuid.UUID) -> Credential:
    """
    Revocation is a status change, never a deletion: the credential row,
    its document, and its signature are all preserved exactly as issued —
    only status/revoked_at change. This is what lets Phase 5 verification
    keep working unmodified: it already reads credential.status and treats
    REVOKED as a real result, so nothing there needs to change for this to
    take effect immediately.
    """
    credential = db.get(Credential, credential_id)
    if credential is None:
        raise CredentialNotFoundError()
    if credential.institution_id != institution.id:
        raise CredentialNotOwnedError()
    if credential.status == CredentialStatus.REVOKED:
        raise CredentialAlreadyRevokedError()

    credential.status = CredentialStatus.REVOKED
    credential.revoked_at = datetime.now(timezone.utc)
    db.add(credential)

    log = ActivityLog(
        actor_user_id=institution.user_id,
        action="CREDENTIAL_REVOKED",
        entity_type="credential",
        entity_id=credential.id,
        metadata_={"credential_identifier": credential.credential_identifier},
    )
    db.add(log)
    db.flush()

    notification_service.create_notification(
        db,
        user_id=credential.student.user_id,
        title="Credential revoked",
        message=f"{institution.name} revoked your credential: {credential.title}",
        activity_log_id=log.id,
        link_entity_type="credential",
        link_entity_id=credential.id,
    )

    db.commit()
    db.refresh(credential)
    return credential


def to_credential_response(credential: Credential) -> CredentialResponse:
    return CredentialResponse(
        id=credential.id,
        credential_identifier=credential.credential_identifier,
        student_id=credential.student_id,
        student_name=credential.student.user.full_name,
        institution_id=credential.institution_id,
        institution_name=credential.institution.name,
        credential_type=credential.credential_type,
        title=credential.title,
        degree=credential.degree,
        graduation_year=credential.graduation_year,
        cgpa=float(credential.cgpa) if credential.cgpa is not None else None,
        status=credential.status,
        issued_at=credential.issued_at,
        revoked_at=credential.revoked_at,
        document_hash=credential.document_hash,
        signature=credential.signature,
        has_document=credential.document is not None,
        blockchain_status=credential.blockchain_status,
        blockchain_network=credential.blockchain_network,
        blockchain_contract_address=credential.blockchain_contract_address,
        blockchain_tx_hash=credential.blockchain_tx_hash,
        blockchain_anchored_at=credential.blockchain_anchored_at,
    )
