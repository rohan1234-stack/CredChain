# ---------------------------------------------------------------------------
# Tests for the durable, encrypted signing-key storage fix (institutions.
# encrypted_private_key, replacing the previous ephemeral on-disk-only PEM
# storage that could be wiped by a Render redeploy/restart — see
# app/security/key_encryption.py and app/services/signing_service.py).
#
# Root incident this closes: an institution could end up with public_key set
# in Postgres but no private key anywhere reachable (its on-disk file lost to
# a restart), and every issuance attempt for it crashed with an unhandled
# InstitutionKeyMissingError — surfaced to the frontend as a generic,
# misleading "Server unavailable" instead of a clear operational error.
# ---------------------------------------------------------------------------

import uuid

import pytest

from app.models.institution import Institution
from app.security import key_encryption, signatures
from app.services import signing_service

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email="signkey-inst@test.credchain.dev", name="Signing Key Test University"):
    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "Test Institution Admin",
            "role": "institution",
            "institution_id": str(institution.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="signkey-stu@test.credchain.dev", identifier="SIGNKEY-STU-1"):
    from app.models.student import Student

    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "Test Student",
            "role": "student",
            "student_identifier": identifier,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    student_id = body["user"]["student_id"]

    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id) if institution_id else None
    db_session.commit()

    return {"token": body["access_token"], "student_id": student_id}


def _issue(client, institution_token, student_id, **overrides):
    data = {
        "student_id": student_id,
        "credential_type": "transcript",
        "title": "Final Transcript",
        "degree": "B.Tech Computer Science",
        "graduation_year": "2026",
        "cgpa": "8.7",
    }
    data.update(overrides)
    files = {"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    return client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token))


# =====================================================================
# Encryption/decryption primitives
# =====================================================================


def test_encrypt_decrypt_round_trip():
    private_pem, _ = signatures.generate_keypair()
    encrypted = key_encryption.encrypt_private_key(private_pem)
    assert isinstance(encrypted, str)
    # Genuinely encrypted, not just base64/passthrough — the raw PEM header must never appear.
    assert "PRIVATE KEY" not in encrypted
    decrypted = key_encryption.decrypt_private_key(encrypted)
    assert decrypted == private_pem


def test_decrypt_with_wrong_secret_fails_cleanly(monkeypatch):
    private_pem, _ = signatures.generate_keypair()
    encrypted = key_encryption.encrypt_private_key(private_pem)

    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "a-completely-different-secret")
    with pytest.raises(key_encryption.KeyDecryptionError):
        key_encryption.decrypt_private_key(encrypted)


def test_missing_encryption_secret_raises_instead_of_using_a_weak_default(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "key_encryption_secret", "")
    with pytest.raises(key_encryption.EncryptionSecretMissingError):
        key_encryption.encrypt_private_key(b"irrelevant")


def test_derived_public_key_matches_generated_public_key():
    """The backfill script's safety check relies on this: a private key's derived public key must exactly match what generate_keypair() produced alongside it."""
    private_pem, public_pem = signatures.generate_keypair()
    assert signatures.derive_public_pem(private_pem) == public_pem


# =====================================================================
# New institutions: encrypted DB storage, never disk
# =====================================================================


def test_new_institution_registration_persists_encrypted_key_never_touches_disk(client, db_session):
    ctx = _register_institution(client, db_session, "signkey-newinst@test.credchain.dev", "New Institution University")
    institution = db_session.get(Institution, uuid.UUID(ctx["institution_id"]))

    assert institution.public_key is not None
    assert institution.encrypted_private_key is not None
    assert "PRIVATE KEY" not in institution.encrypted_private_key

    # The whole point of this fix: a brand-new institution's private key never touches local
    # disk at all, so it can never be lost to a Render restart/redeploy.
    legacy_path = signing_service.legacy_private_key_path(institution.id)
    assert not legacy_path.exists()


def test_issuance_succeeds_using_the_new_encrypted_key(client, db_session):
    inst = _register_institution(client, db_session, "signkey-issue-ok@test.credchain.dev", "Issue OK University")
    student = _register_student(client, db_session, inst["institution_id"], "signkey-issue-ok-stu@test.credchain.dev", "SIGNKEY-OK-1")
    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["signature"] is not None
    assert "PRIVATE KEY" not in resp.text


# =====================================================================
# The exact "public_key present, private key missing" incident state
# =====================================================================


def _make_orphaned_institution(db_session, name="Orphaned Signing Key University"):
    """
    Reproduces the exact Aalto-incident state directly: an institution with a
    real public_key on record but NO way to reach the matching private key —
    no encrypted_private_key in the DB, and (deliberately) no legacy PEM file
    on disk either. Never goes through ensure_institution_keypair, since the
    whole point is to simulate the key having been lost AFTER that function
    already ran successfully once, in the past.
    """
    _, public_pem = signatures.generate_keypair()
    institution = Institution(name=name, public_key=public_pem.decode("utf-8"))
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    return institution


def test_ensure_institution_keypair_does_not_regenerate_when_private_key_is_missing(db_session):
    institution = _make_orphaned_institution(db_session)
    original_public_key = institution.public_key

    signing_service.ensure_institution_keypair(db_session, institution)

    db_session.refresh(institution)
    assert institution.public_key == original_public_key
    assert institution.encrypted_private_key is None


def test_sign_credential_payload_raises_clear_error_when_key_missing(db_session):
    institution = _make_orphaned_institution(db_session)
    with pytest.raises(signing_service.InstitutionKeyMissingError):
        signing_service.sign_credential_payload(institution, b"some canonical payload bytes")


def test_issuance_returns_503_with_honest_message_when_signing_key_missing(client, db_session):
    institution = _make_orphaned_institution(db_session, "Orphaned 503 University")

    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signkey-503-inst@test.credchain.dev",
            "password": "Password123",
            "full_name": "Orphaned Institution Admin",
            "role": "institution",
            "institution_id": str(institution.id),
        },
    )
    assert resp.status_code == 201, resp.text
    inst_token = resp.json()["access_token"]

    student = _register_student(client, db_session, str(institution.id), "signkey-503-stu@test.credchain.dev", "SIGNKEY-503-1")

    resp = _issue(client, inst_token, student["student_id"])

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["detail"] == (
        "This institution's signing key is currently unavailable on the server. "
        "Credential issuance is temporarily disabled — please contact CredChain support."
    )
    # No path, no key material, nothing internal leaked in the response the browser sees.
    raw_text = resp.text
    assert "keys" not in raw_text.lower()
    assert "PRIVATE KEY" not in raw_text
    assert str(institution.id) not in raw_text

    # And the failed attempt left no partial credential/document behind.
    from app.models.credential import Credential

    assert db_session.query(Credential).filter(Credential.institution_id == institution.id).count() == 0


def test_bulk_issuance_also_returns_503_when_signing_key_missing(client, db_session):
    institution = _make_orphaned_institution(db_session, "Orphaned Bulk University")
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signkey-bulk-503-inst@test.credchain.dev",
            "password": "Password123",
            "full_name": "Orphaned Bulk Institution Admin",
            "role": "institution",
            "institution_id": str(institution.id),
        },
    )
    assert resp.status_code == 201, resp.text
    inst_token = resp.json()["access_token"]
    student = _register_student(client, db_session, str(institution.id), "signkey-bulk-503-stu@test.credchain.dev", "SIGNKEY-BULK-503-1")

    resp = client.post(
        "/api/institutions/me/credentials/bulk",
        data={
            "student_ids": [student["student_id"]],
            "credential_type": "transcript",
            "title": "Final Transcript",
            "graduation_year": "2026",
        },
        files=[("documents", ("t.pdf", SAMPLE_PDF_BYTES, "application/pdf"))],
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 503, resp.text
    assert "signing key is currently unavailable" in resp.json()["detail"]


# =====================================================================
# Verification compatibility — the Ed25519 trust model is unchanged
# =====================================================================


def test_signature_produced_via_encrypted_storage_verifies_normally(client, db_session):
    """
    End-to-end proof that switching the private key's storage location did
    NOT change the trust model: a credential issued through the new
    encrypted-DB signing path still produces a signature that
    verification_service's existing, UNCHANGED check_signature() accepts.
    """
    from app.models.credential import Credential
    from app.services import verification_service

    inst = _register_institution(client, db_session, "signkey-verify@test.credchain.dev", "Verify Compat University")
    student = _register_student(client, db_session, inst["institution_id"], "signkey-verify-stu@test.credchain.dev", "SIGNKEY-VERIFY-1")
    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 201, resp.text

    credential = db_session.get(Credential, uuid.UUID(resp.json()["id"]))
    institution = credential.institution
    canonical_payload = verification_service.reconstruct_canonical_payload(credential)
    assert verification_service.check_signature(institution, credential, canonical_payload) is True


# =====================================================================
# No private key material ever appears in an API response
# =====================================================================


def test_institution_public_profile_never_exposes_private_key_material(client, db_session):
    inst = _register_institution(client, db_session, "signkey-profile-leak@test.credchain.dev", "Profile Leak Check University")

    resp = client.get(f"/api/institutions/{inst['institution_id']}")
    assert resp.status_code == 200, resp.text
    assert "encrypted_private_key" not in resp.json()
    assert "PRIVATE KEY" not in resp.text
    assert "BEGIN PRIVATE" not in resp.text
