# ---------------------------------------------------------------------------
# PS3 Phase D: student-uploaded existing documents. A StudentDocument is
# deliberately NOT a Credential — it starts UNVERIFIED and stays that way
# until an institution reviews it. The only way it ever becomes a real,
# verifiable credential is approve_document below, which reuses the exact
# same signing core (credential_service.issue_signed_credential) as every
# other issuance path — never a boolean flip on this row.
#
# Structural enforcement of "unverified upload != verified credential": no
# route anywhere lets a student touch this row's status, and a company's
# verification pipeline (verification_service.py) only ever reads Credential
# rows through ShareGrants — it has no code path that reaches StudentDocument
# at all.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.orm import Session

from ..models.activity_log import ActivityLog
from ..models.enums import CredentialType, StudentDocumentStatus
from ..models.institution import Institution
from ..models.student import Student
from ..models.student_document import StudentDocument
from ..schemas.student_document import StudentDocumentResponse
from . import document_service, notification_service


class NotAffiliatedError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class DocumentNotOwnedError(Exception):
    pass


class DocumentAlreadyReviewedError(Exception):
    pass


class DocumentFileMissingError(Exception):
    pass


async def upload_document(
    db: Session,
    student: Student,
    *,
    institution_id: uuid.UUID,
    credential_type: CredentialType,
    custom_credential_name: str | None,
    document: UploadFile,
) -> StudentDocument:
    if student.institution_id is None or student.institution_id != institution_id:
        raise NotAffiliatedError()

    document_bytes = await document_service.read_and_validate_pdf(document)
    content_hash = document_service.compute_sha256(document_bytes)

    document_id = uuid.uuid4()
    storage_path: str | None = None
    try:
        storage_path = document_service.save_student_document(document_id, document_bytes)

        record = StudentDocument(
            id=document_id,
            student_id=student.id,
            institution_id=institution_id,
            credential_type=credential_type,
            custom_credential_name=custom_credential_name,
            original_filename=document.filename or "document.pdf",
            storage_path=storage_path,
            mime_type=document.content_type or "application/pdf",
            file_size=len(document_bytes),
            content_hash=content_hash,
            status=StudentDocumentStatus.UNVERIFIED,
        )
        db.add(record)
        db.flush()

        log = ActivityLog(
            actor_user_id=student.user_id,
            action="STUDENT_DOCUMENT_SUBMITTED",
            entity_type="student_document",
            entity_id=record.id,
            metadata_={"institution_id": str(institution_id)},
        )
        db.add(log)
        db.flush()

        institution = db.get(Institution, institution_id)
        # A directory-only institution (never registered) has no logged-in user to notify.
        if institution is not None and institution.user_id is not None:
            label = custom_credential_name or credential_type.value.replace("_", " ").title()
            notification_service.create_notification(
                db,
                user_id=institution.user_id,
                title="New document submitted",
                message=f"{student.user.full_name} submitted a {label} for review",
                activity_log_id=log.id,
                link_entity_type="student_document",
                link_entity_id=record.id,
            )

        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        if storage_path is not None:
            document_service.delete_document_if_exists(storage_path)
        raise


def list_for_student(db: Session, student: Student) -> list[StudentDocument]:
    return (
        db.query(StudentDocument)
        .filter(StudentDocument.student_id == student.id)
        .order_by(StudentDocument.created_at.desc())
        .all()
    )


def list_for_institution(db: Session, institution: Institution) -> list[StudentDocument]:
    return (
        db.query(StudentDocument)
        .filter(StudentDocument.institution_id == institution.id)
        .order_by(StudentDocument.created_at.desc())
        .all()
    )


def _get_owned_document(db: Session, institution: Institution, document_id: uuid.UUID) -> StudentDocument:
    document = db.get(StudentDocument, document_id)
    if document is None:
        raise DocumentNotFoundError()
    if document.institution_id != institution.id:
        raise DocumentNotOwnedError()
    return document


def get_document_for_view(db: Session, institution: Institution, document_id: uuid.UUID) -> StudentDocument:
    """
    Institution opening the document detail/file — this is also where the
    UNVERIFIED -> UNDER_REVIEW transition happens (the simplification noted
    in the plan: no separate manual "start review" action).
    """
    document = _get_owned_document(db, institution, document_id)
    if document.status == StudentDocumentStatus.UNVERIFIED:
        document.status = StudentDocumentStatus.UNDER_REVIEW
        db.add(document)
        db.commit()
        db.refresh(document)
    return document


def approve_document(
    db: Session,
    institution: Institution,
    document_id: uuid.UUID,
    *,
    degree: str | None = None,
    graduation_year: int | None = None,
    cgpa: float | None = None,
) -> StudentDocument:
    """
    A StudentDocument carries no structured academic fields of its own (it's
    just an uploaded file) — degree/graduation_year/cgpa here are whatever
    the institution reviewer confirms while looking at the actual PDF, e.g.
    "I can see this transcript shows CGPA 9.6." Without these, the resulting
    Credential would be permanently metadata-empty regardless of what the
    document actually contains, which silently broke eligibility checks for
    any student whose only proof of a value came through this path. Reuses
    credential_service's own range validation (_validate_fields), so an
    out-of-range value is rejected exactly as it would be for direct
    issuance.
    """
    document = _get_owned_document(db, institution, document_id)
    if document.status not in (StudentDocumentStatus.UNVERIFIED, StudentDocumentStatus.UNDER_REVIEW):
        raise DocumentAlreadyReviewedError()

    if not document_service.document_exists(document.storage_path):
        raise DocumentFileMissingError()
    document_bytes = document_service.read_document(document.storage_path)

    from . import credential_service  # local import: avoids a service-to-service import cycle at module load time

    title = document.custom_credential_name or document.credential_type.value.replace("_", " ").title()
    credential_service._validate_fields(title, graduation_year, cgpa)  # noqa: SLF001 — same validation every other issuance path uses, not duplicated here

    student = document.student
    credential = credential_service.issue_signed_credential(
        db,
        institution,
        student,
        credential_type=document.credential_type,
        title=title,
        degree=degree,
        graduation_year=graduation_year,
        cgpa=cgpa,
        document_bytes=document_bytes,
        original_filename=document.original_filename,
        content_type=document.mime_type,
    )

    document.status = StudentDocumentStatus.APPROVED
    document.resulting_credential_id = credential.id
    document.reviewed_at = datetime.now(timezone.utc)
    db.add(document)

    # ActivityLog only, deliberately NO Notification here: issue_signed_credential (just called
    # above) already wrote a CREDENTIAL_ISSUED ActivityLog + notified this exact student in the
    # same logical action — a second "your document was approved" notification for the same
    # click would be a duplicate push for one real event (see Phase 9 of the notification design:
    # avoid multiple notifications for the same logical event through multiple paths). The
    # ActivityLog row is still written so the feed/audit trail accurately shows the document was
    # reviewed, not just that a credential appeared.
    db.add(
        ActivityLog(
            actor_user_id=institution.user_id,
            action="STUDENT_DOCUMENT_APPROVED",
            entity_type="student_document",
            entity_id=document.id,
            metadata_={"credential_id": str(credential.id)},
        )
    )

    db.commit()
    db.refresh(document)
    return document


def reject_document(db: Session, institution: Institution, document_id: uuid.UUID, reason: str) -> StudentDocument:
    document = _get_owned_document(db, institution, document_id)
    if document.status not in (StudentDocumentStatus.UNVERIFIED, StudentDocumentStatus.UNDER_REVIEW):
        raise DocumentAlreadyReviewedError()

    document.status = StudentDocumentStatus.REJECTED
    document.rejection_reason = reason
    document.reviewed_at = datetime.now(timezone.utc)
    db.add(document)

    log = ActivityLog(
        actor_user_id=institution.user_id,
        action="STUDENT_DOCUMENT_REJECTED",
        entity_type="student_document",
        entity_id=document.id,
        metadata_={"reason": reason},
    )
    db.add(log)
    db.flush()

    notification_service.create_notification(
        db,
        user_id=document.student.user_id,
        title="Document rejected",
        message=f"{institution.name} rejected your submitted document",
        activity_log_id=log.id,
        link_entity_type="student_document",
        link_entity_id=document.id,
    )

    db.commit()
    db.refresh(document)
    return document


def to_response(document: StudentDocument) -> StudentDocumentResponse:
    return StudentDocumentResponse(
        id=document.id,
        student_id=document.student_id,
        student_name=document.student.user.full_name,
        student_identifier=document.student.student_identifier,
        institution_id=document.institution_id,
        institution_name=document.institution.name,
        credential_type=document.credential_type,
        custom_credential_name=document.custom_credential_name,
        original_filename=document.original_filename,
        status=document.status,
        rejection_reason=document.rejection_reason,
        resulting_credential_id=document.resulting_credential_id,
        created_at=document.created_at,
        reviewed_at=document.reviewed_at,
    )
