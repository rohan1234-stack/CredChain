# ---------------------------------------------------------------------------
# Low-level asymmetric signing primitives — Ed25519, via the `cryptography`
# library. This module knows nothing about institutions, credentials, or key
# storage; it only deals in raw key bytes and payload bytes. Institution key
# lifecycle (generate-once, where the private key lives, when to sign) is
# app/services/signing_service.py.
#
# Ed25519 chosen per the spec: modern, fast, small keys/signatures, no
# parameter-choice footguns (unlike RSA's padding scheme or key size, or
# ECDSA's nonce-reuse hazard).
# ---------------------------------------------------------------------------

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair() -> tuple[bytes, bytes]:
    """Returns (private_key_pem, public_key_pem), both PEM-encoded UTF-8 bytes."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def sign(private_key_pem: bytes, payload: bytes) -> bytes:
    """Signs `payload` (already-canonicalized bytes) with a PEM-encoded Ed25519 private key. Returns the raw signature bytes."""
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 private key")
    return private_key.sign(payload)


def derive_public_pem(private_key_pem: bytes) -> bytes:
    """
    Returns the PEM-encoded public key that matches a given PEM-encoded Ed25519
    private key. Used only to VERIFY a candidate private key file actually
    belongs to the institution it's being migrated for (see
    scripts/backfill_encrypted_signing_keys.py) — never to generate a new
    keypair or to accept a private key on trust alone.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 private key")
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def verify(public_key_pem: bytes, payload: bytes, signature: bytes) -> bool:
    """Returns True iff `signature` is a valid Ed25519 signature over `payload` by the holder of the private key matching `public_key_pem`."""
    public_key = serialization.load_pem_public_key(public_key_pem)
    try:
        public_key.verify(signature, payload)
        return True
    except InvalidSignature:
        return False
