# ---------------------------------------------------------------------------
# Institution signing-key lifecycle: generate once, store the public half in
# Postgres (institutions.public_key), keep the private half server-side only.
#
# STORAGE MODEL:
# The private key's durable home is now institutions.encrypted_private_key —
# encrypted with a Render-only env var (KEY_ENCRYPTION_SECRET, see
# app/security/key_encryption.py) that never touches the database or source
# control. A new institution's key never touches local disk at all anymore.
#
# LEGACY FALLBACK: an institution whose private key still only exists as a
# plain PEM file under KEYS_PATH (the old, pre-encryption storage — disk that
# does NOT survive a Render redeploy/restart) keeps working via
# legacy_private_key_path() below, purely so this change doesn't break any
# institution mid-migration. This fallback is read-only and best-effort: it
# is NEVER treated as authoritative for regeneration, and
# scripts/backfill_encrypted_signing_keys.py is the one-time, explicit path
# that moves a still-recoverable file into encrypted_private_key. Once every
# institution is backfilled, this fallback becomes dead code but is kept
# rather than removed, since there's no way to be certain every institution
# in every environment has been migrated.
# ---------------------------------------------------------------------------

import base64
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models.institution import Institution
from ..security import key_encryption, signatures


class InstitutionKeyMissingError(Exception):
    """
    No usable private key is available for this institution — neither
    encrypted in the database nor as a legacy on-disk PEM file. This is a
    server-side operational condition, never a signal to silently generate a
    replacement (see ensure_institution_keypair's docstring): an institution
    that already has a public_key on record must never have a new keypair
    generated out from under it, since that would invalidate every
    credential already signed with the original key.
    """

    pass


def legacy_private_key_path(institution_id) -> Path:
    """Where an institution's PEM file would live under the old, pre-encryption disk-based storage — read-only compatibility fallback, see module docstring."""
    return Path(settings.keys_path) / f"{institution_id}.pem"


def ensure_institution_keypair(db: Session, institution: Institution) -> None:
    """
    Idempotent: if this institution already has a public key on record, does
    nothing — a stable signing identity is the whole point; regenerating on
    every call would silently invalidate every credential signed so far.
    Only generates + persists a new keypair when institution.public_key is
    still unset (i.e. this institution has never had one).

    For a brand-new institution, the private key is encrypted and stored
    directly in encrypted_private_key — it is never written to local disk,
    so it can never be lost to a redeploy/restart in the first place.
    """
    if institution.public_key is not None:
        return

    private_pem, public_pem = signatures.generate_keypair()

    institution.encrypted_private_key = key_encryption.encrypt_private_key(private_pem)
    institution.public_key = public_pem.decode("utf-8")
    db.add(institution)
    db.commit()


def _load_private_key_pem(institution: Institution) -> bytes:
    """
    Resolves this institution's private key bytes: encrypted database
    storage first (the durable, current source of truth), then the legacy
    on-disk file as a best-effort compatibility fallback for an institution
    not yet backfilled. Raises InstitutionKeyMissingError if neither source
    has it — never generates a replacement.
    """
    if institution.encrypted_private_key is not None:
        return key_encryption.decrypt_private_key(institution.encrypted_private_key)

    legacy_path = legacy_private_key_path(institution.id)
    if legacy_path.exists():
        return legacy_path.read_bytes()

    raise InstitutionKeyMissingError(
        f"No private signing key available for institution {institution.id} "
        "(checked encrypted database storage and legacy disk storage)"
    )


def sign_credential_payload(institution: Institution, canonical_payload: bytes) -> str:
    """Signs already-canonicalized bytes with this institution's private key. Returns the signature, base64-encoded (safe for DB/API/JSON)."""
    private_pem = _load_private_key_pem(institution)
    signature = signatures.sign(private_pem, canonical_payload)
    return base64.b64encode(signature).decode("ascii")
