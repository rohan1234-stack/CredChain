# ---------------------------------------------------------------------------
# Envelope encryption for institution private signing keys stored in Postgres
# (institutions.encrypted_private_key).
#
# The master secret (KEY_ENCRYPTION_SECRET) lives ONLY in a Render environment
# variable — never in the database, never in source control. This means DB
# access alone can never decrypt a private key, and env-var access alone
# never sees any key material either: both must be compromised together.
#
# Fernet (AES-128-CBC + HMAC-SHA256, from the already-installed `cryptography`
# package) requires a 32-byte urlsafe-base64 key; KEY_ENCRYPTION_SECRET is an
# arbitrary operator-chosen string (same convention as JWT_SECRET_KEY), so it
# is deterministically stretched into a valid Fernet key via SHA-256 — this
# never touches the database or logs, only ever exists in memory.
# ---------------------------------------------------------------------------

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

__all__ = ["EncryptionSecretMissingError", "KeyDecryptionError", "encrypt_private_key", "decrypt_private_key"]


class EncryptionSecretMissingError(Exception):
    """KEY_ENCRYPTION_SECRET is unset — encryption/decryption cannot proceed."""

    pass


class KeyDecryptionError(Exception):
    """
    The stored ciphertext could not be decrypted — either KEY_ENCRYPTION_SECRET
    doesn't match what was used to encrypt it, or the stored value is corrupted.
    Never a signal to regenerate anything automatically.
    """

    pass


def _fernet() -> Fernet:
    secret = settings.key_encryption_secret
    if not secret:
        raise EncryptionSecretMissingError("KEY_ENCRYPTION_SECRET is not configured on this server")
    derived_key = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_private_key(private_key_pem: bytes) -> str:
    """Encrypts raw PEM bytes for storage in institutions.encrypted_private_key. Returns ASCII text safe for a Postgres TEXT column."""
    token = _fernet().encrypt(private_key_pem)
    return token.decode("ascii")


def decrypt_private_key(encrypted: str) -> bytes:
    """Reverses encrypt_private_key. Raises KeyDecryptionError on a wrong secret or corrupted data — never returns partial/garbage key material."""
    try:
        return _fernet().decrypt(encrypted.encode("ascii"))
    except InvalidToken as exc:
        raise KeyDecryptionError("Stored private key could not be decrypted with the configured KEY_ENCRYPTION_SECRET") from exc
