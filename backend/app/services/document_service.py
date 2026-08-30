# ---------------------------------------------------------------------------
# PDF upload validation + private storage. PDF only, for now.
#
# Validation does NOT trust the filename or the browser-supplied Content-Type
# alone — both are attacker-controlled. The one check that actually proves
# "this is a PDF" is the magic-byte signature at the start of the file.
#
# Storage backend: Supabase Storage (private buckets) when SUPABASE_URL and
# SUPABASE_SERVICE_ROLE_KEY are both configured — the same "disabled until
# configured" pattern already used for ai_enabled/blockchain_enabled. This
# fixes credential/student-document PDFs being silently lost on every Render
# redeploy (local disk there is ephemeral; Postgres is not). When Supabase
# isn't configured (every existing test, and any dev environment that hasn't
# set these two env vars), storage falls back to the original local
# filesystem behavior, completely unchanged — no test in this suite needs
# real Supabase credentials.
#
# storage_path values already in the database from before this migration are
# plain local filesystem paths (e.g. "storage/credentials/<uuid>.pdf") and
# keep working exactly as before via the legacy branch below; only NEW
# uploads (once Supabase is configured) get the new "credentials/<uuid>.pdf"
# / "student-documents/<uuid>.pdf" object-key shape. No database migration,
# no rewriting of existing rows — see document_exists()/read_document()'s
# _is_supabase_key() check, which disambiguates purely from the string shape.
# ---------------------------------------------------------------------------

import hashlib
import logging
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import UploadFile

from ..config import settings

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_CONTENT_TYPES = {"application/pdf"}
PDF_MAGIC = b"%PDF-"

# A legacy local path is always nested one level deeper than these (under
# whatever STORAGE_PATH is, e.g. "storage/credentials/<uuid>.pdf" or an
# absolute path) — only a genuine new Supabase object key starts with
# exactly one of these two prefixes.
_CREDENTIAL_KEY_PREFIX = "credentials/"
_STUDENT_DOCUMENT_KEY_PREFIX = "student-documents/"


class UnsupportedDocumentTypeError(Exception):
    pass


class DocumentTooLargeError(Exception):
    pass


class EmptyDocumentError(Exception):
    pass


class StorageUnavailableError(Exception):
    """
    Raised when the storage backend itself could not be reached, timed out,
    or returned an unexpected error — this is explicitly NOT proof that a
    document is missing or tampered. Callers (verification_service.
    check_document_integrity in particular) must let this propagate rather
    than treating it as a failed integrity/existence check, so a temporary
    Supabase outage can never make an otherwise correctly signed credential
    report INVALID, or a real document look permanently lost.
    """


async def read_and_validate_pdf(upload: UploadFile) -> bytes:
    """
    Reads the full upload into memory and validates it. Raises one of the
    typed errors above on any failure — the caller (route) maps these to
    HTTP 415/413/400. Order matters: cheap header checks first, then read
    the body, then the expensive/authoritative magic-byte check.
    """
    filename = upload.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedDocumentTypeError(f"Unsupported file extension: {extension or '(none)'}. Only .pdf is accepted.")

    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedDocumentTypeError(f"Unsupported content type: {upload.content_type}. Only application/pdf is accepted.")

    data = await upload.read()

    if len(data) == 0:
        raise EmptyDocumentError("Uploaded document is empty")

    if len(data) > settings.max_document_size_bytes:
        raise DocumentTooLargeError(
            f"Document exceeds the maximum size of {settings.max_document_size_bytes} bytes"
        )

    # The authoritative check: filename and Content-Type are both supplied
    # by the client and prove nothing on their own — this does.
    if not data.startswith(PDF_MAGIC):
        raise UnsupportedDocumentTypeError("File content is not a valid PDF (missing %PDF- header)")

    return data


def compute_sha256(data: bytes) -> str:
    """Returns the 64-character lowercase hex SHA-256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def _supabase_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)


@lru_cache
def _supabase_client():
    """
    Lazily constructed, cached singleton — mirrors app.config.get_settings()'s
    own @lru_cache pattern. Imported here, not at module load time, so simply
    importing document_service never requires the `supabase` package to be
    usable in an environment that isn't using Supabase at all (every existing
    test, any local dev setup that hasn't configured it).
    """
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _is_supabase_key(storage_path: str) -> bool:
    return storage_path.startswith(_CREDENTIAL_KEY_PREFIX) or storage_path.startswith(_STUDENT_DOCUMENT_KEY_PREFIX)


def _bucket_name_for_key(object_key: str) -> str:
    if object_key.startswith(_CREDENTIAL_KEY_PREFIX):
        return settings.supabase_credential_bucket
    return settings.supabase_student_document_bucket


def _is_not_found_error(exc: Exception) -> bool:
    """
    True only for a StorageApiError that clearly means "this object does not
    exist" (Supabase Storage's own not-found shape). Any other error —
    wrong status code, unexpected body, or not a StorageApiError at all
    (network failure, timeout, DNS failure, auth failure) — is NOT
    considered proof of absence; see StorageUnavailableError's docstring.
    """
    from storage3.exceptions import StorageApiError

    if not isinstance(exc, StorageApiError):
        return False
    status = str(getattr(exc, "status", ""))
    code = str(getattr(exc, "code", "")).lower()
    message = str(getattr(exc, "message", "")).lower()
    return status in ("404", "400") and ("not_found" in code or "notfound" in code or "not found" in message)


def _log_storage_error(action: str, exc: Exception, *, object_key: str) -> None:
    """
    Logs only structural, non-sensitive diagnostic fields for an unexpected
    Supabase Storage failure: the exception's type, Supabase's own HTTP
    status/error code when available, the target bucket, and the object key.
    Deliberately never logs str(exc) (the raw message could echo back
    request/URL details), settings.supabase_url, settings.
    supabase_service_role_key, or any file content — those must never reach
    application logs.
    """
    from storage3.exceptions import StorageApiError

    status = getattr(exc, "status", None) if isinstance(exc, StorageApiError) else None
    code = getattr(exc, "code", None) if isinstance(exc, StorageApiError) else None
    logger.warning(
        "Supabase Storage %s failed: exc_type=%s status=%s code=%s bucket=%s object_key=%s",
        action,
        type(exc).__name__,
        status,
        code,
        _bucket_name_for_key(object_key),
        object_key,
    )


def _download_from_supabase(object_key: str) -> bytes | None:
    """Returns the object's bytes, or None if it genuinely does not exist. Raises StorageUnavailableError for any other failure."""
    try:
        bucket = _supabase_client().storage.from_(_bucket_name_for_key(object_key))
        return bucket.download(object_key)
    except Exception as exc:
        if _is_not_found_error(exc):
            return None
        _log_storage_error("download", exc, object_key=object_key)
        raise StorageUnavailableError(str(exc)) from exc


def _upload_to_supabase(object_key: str, data: bytes, *, content_type: str) -> None:
    try:
        bucket = _supabase_client().storage.from_(_bucket_name_for_key(object_key))
        # upsert=true matches the local-filesystem fallback's existing behavior
        # (Path.write_bytes always overwrites unconditionally) — credential_id/
        # student_document_id are freshly generated UUIDs per upload either way,
        # so this never actually overwrites a different upload's bytes in practice.
        bucket.upload(object_key, data, {"content-type": content_type, "upsert": "true"})
    except Exception as exc:
        _log_storage_error("upload", exc, object_key=object_key)
        raise StorageUnavailableError(str(exc)) from exc


def _delete_from_supabase(object_key: str) -> None:
    """
    Best-effort — see delete_document_if_exists's docstring for why this
    never raises: a secondary storage error here must never replace/mask
    the real failure the caller is already in the middle of handling.
    """
    try:
        bucket = _supabase_client().storage.from_(_bucket_name_for_key(object_key))
        bucket.remove([object_key])
    except Exception:
        pass


def credential_document_path(credential_id: uuid.UUID) -> Path:
    """Legacy local filesystem path — used only as a fallback when Supabase isn't configured."""
    return Path(settings.storage_path) / "credentials" / f"{credential_id}.pdf"


def student_document_path(document_id: uuid.UUID) -> Path:
    """Legacy local filesystem path — used only as a fallback when Supabase isn't configured."""
    return Path(settings.storage_path) / "student_documents" / f"{document_id}.pdf"


def save_document(credential_id: uuid.UUID, data: bytes) -> str:
    """
    Writes the validated bytes to Supabase Storage (when SUPABASE_URL/
    SUPABASE_SERVICE_ROLE_KEY are configured) or the legacy local filesystem
    (fallback — matches every existing test/dev environment that hasn't set
    those). Returns the value to store in CredentialDocument.storage_path: a
    Supabase object key ("credentials/<uuid>.pdf") or the local path string,
    matching whichever backend was actually used. Never a signed/public URL.
    """
    if _supabase_configured():
        object_key = f"{_CREDENTIAL_KEY_PREFIX}{credential_id}.pdf"
        _upload_to_supabase(object_key, data, content_type="application/pdf")
        return object_key

    path = credential_document_path(credential_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def save_student_document(document_id: uuid.UUID, data: bytes) -> str:
    """Same contract as save_document, for a student-uploaded (not-yet-verified) document — kept in its own bucket/subdirectory."""
    if _supabase_configured():
        object_key = f"{_STUDENT_DOCUMENT_KEY_PREFIX}{document_id}.pdf"
        _upload_to_supabase(object_key, data, content_type="application/pdf")
        return object_key

    path = student_document_path(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def document_exists(storage_path: str) -> bool:
    """
    True if the document is actually present in whichever backend
    storage_path refers to (detected from its shape — see _is_supabase_key).
    Raises StorageUnavailableError if Supabase itself could not be reached
    or queried — that is NOT the same thing as "the document doesn't exist",
    and callers must not treat it that way (see the exception's docstring).
    """
    if _is_supabase_key(storage_path):
        return _download_from_supabase(storage_path) is not None
    return Path(storage_path).exists()


def read_document(storage_path: str) -> bytes:
    """
    Returns the raw bytes for a document callers have already confirmed
    exists (via document_exists(), exactly as every call site already did
    with Path.exists() before this migration). Raises StorageUnavailableError
    on a genuine Supabase connectivity/service failure, or FileNotFoundError
    for a legacy local path that turned out not to exist after all.
    """
    if _is_supabase_key(storage_path):
        data = _download_from_supabase(storage_path)
        if data is None:
            raise FileNotFoundError(storage_path)
        return data
    return Path(storage_path).read_bytes()


def delete_document_if_exists(storage_path: str) -> None:
    """
    Best-effort cleanup for the orphaned-file-on-failed-transaction case (see
    credential_service.issue_signed_credential / student_document_service.
    upload_document). Never raises — this always runs from inside an
    `except:` block that's about to re-raise the REAL failure, and a
    secondary storage error here must never replace or mask that original
    exception. A failed delete simply leaves the orphaned object in place
    (safe: it was never referenced by any committed row, since the
    transaction that would have referenced it was rolled back) rather than
    silently claiming the deletion succeeded.
    """
    if _is_supabase_key(storage_path):
        _delete_from_supabase(storage_path)
        return
    path = Path(storage_path)
    if path.exists():
        path.unlink()
