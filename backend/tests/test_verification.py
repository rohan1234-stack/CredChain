# ---------------------------------------------------------------------------
# Phase 5 tests. Since Phase 6 (share creation) doesn't exist yet, tests
# authorize a company for a credential by inserting a ShareGrant row
# directly via the DB session — exactly the "explicitly marked/tested as
# authorized" mechanism the Phase 5 spec calls for. This is also, not
# coincidentally, exactly what Phase 6's real share-creation endpoint will
# do under the hood — the authorization boundary doesn't change.
# ---------------------------------------------------------------------------

import base64
import uuid
from datetime import datetime, timedelta, timezone

from app.models.credential import Credential
from app.models.institution import Institution
from app.models.share_grant import ShareGrant, ShareGrantCredential
from app.models.student import Student
from app.security import signatures

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email="inst@test.credchain.dev", name="Test University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="student@test.credchain.dev", identifier="STU-001"):
    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="verifier@test.credchain.dev", name="Test Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue_credential(client, institution_token, student_id, **overrides) -> dict:
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
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _grant_access(db_session, *, student_id, company_id, credential_id, expires_in_days=7, revoked=False):
    """Test-only equivalent of what Phase 6's share-creation endpoint will do — inserts a ShareGrant directly."""
    grant = ShareGrant(
        student_id=uuid.UUID(student_id),
        company_id=uuid.UUID(company_id),
        share_token_hash="test-token-hash-" + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db_session.add(grant)
    db_session.flush()
    db_session.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=uuid.UUID(credential_id)))
    db_session.commit()
    return grant


def _verify(client, verifier_token, credential_id, demo_cgpa_override=None):
    body = {"credential_id": credential_id}
    if demo_cgpa_override is not None:
        body["demo_cgpa_override"] = demo_cgpa_override
    return client.post("/api/verification/verify", json=body, headers=_auth_header(verifier_token))


def _setup(client, db_session):
    """Common fixture-free setup: institution + student + issued credential + verifier + authorization grant."""
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session)
    _grant_access(
        db_session, student_id=student["student_id"], company_id=verifier["company_id"], credential_id=credential["id"]
    )
    return {"inst": inst, "student": student, "credential": credential, "verifier": verifier}


# --- 1: valid credential -----------------------------------------------------


def test_valid_credential_is_verified(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["checks"] == {"issuer": True, "signature": True, "integrity": True, "status": True, "access": True}
    assert body["credential"]["title"] == "Final Transcript"
    assert body["credential"]["cgpa"] == 8.7
    assert body["credential"]["institution_name"] == "Test University"


# --- 2-5: tampered field via demo override -> INVALID -------------------------


def test_modified_cgpa_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"], demo_cgpa_override=9.7)
    body = resp.json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


def test_modified_title_is_invalid_via_direct_mutation(client, db_session):
    """Simulates a DB-level tamper of a signed field (not through the demo-override path, which only covers cgpa)."""
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.title = "Forged Distinction Transcript"
    db_session.commit()

    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


def test_modified_degree_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.degree = "Forged Degree"
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


def test_modified_graduation_year_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.graduation_year = 1999
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


# --- 6: modified document (actual file bytes, not the DB hash) -> INVALID -------


def test_modified_document_file_is_invalid(client, db_session):
    """
    Tampers with the FILE on disk directly, leaving the DB row (including
    document_hash) untouched — this is what specifically exercises
    check_document_integrity rather than check_signature.
    """
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    from pathlib import Path

    Path(credential.document.storage_path).write_bytes(b"%PDF-1.4\n%tampered-file-bytes\n%%EOF")

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "INVALID"
    assert body["checks"]["integrity"] is False
    assert body["checks"]["signature"] is True  # signature itself is untouched — only the file changed


# --- 7: invalid signature (corrupted signature bytes) -> INVALID -----------------


def test_corrupted_signature_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    # Flip the stored signature to garbage that still base64-decodes.
    credential.signature = base64.b64encode(b"not-a-real-signature-value-0000").decode("ascii")
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


# --- 8: wrong institution public key -> INVALID -----------------------------------


def test_wrong_institution_public_key_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    institution = db_session.query(Institution).filter(Institution.id == uuid.UUID(ctx["inst"]["institution_id"])).first()
    _, unrelated_public_pem = signatures.generate_keypair()
    institution.public_key = unrelated_public_pem.decode("utf-8")
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


# --- 9/10: status -----------------------------------------------------------------


def test_revoked_credential_is_revoked(client, db_session):
    from app.models.enums import CredentialStatus

    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.status = CredentialStatus.REVOKED
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "REVOKED"
    assert body["checks"]["signature"] is True
    assert body["checks"]["status"] is False


def test_expired_credential_is_expired(client, db_session):
    from app.models.enums import CredentialStatus

    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.status = CredentialStatus.EXPIRED
    db_session.commit()

    body = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"]).json()
    assert body["result"] == "EXPIRED"


# --- 11/12/13: authorization / authentication -------------------------------------


def test_unauthorized_verifier_gets_unauthorized_result(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session, email="no-access@test.credchain.dev")
    # deliberately no _grant_access call

    resp = _verify(client, verifier["token"], credential["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "UNAUTHORIZED"
    assert body["checks"] == {"issuer": False, "signature": False, "integrity": False, "status": False, "access": False}
    assert body["credential"] is None


def test_unauthenticated_request_returns_401(client, db_session):
    resp = client.post("/api/verification/verify", json={"credential_id": str(uuid.uuid4())})
    assert resp.status_code == 401


def test_non_verifier_role_returns_403(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["inst"]["token"], ctx["credential"]["id"])
    assert resp.status_code == 403


def test_not_found_credential(client, db_session):
    verifier = _register_verifier(client, db_session, email="nf@test.credchain.dev")
    resp = _verify(client, verifier["token"], str(uuid.uuid4()))
    assert resp.status_code == 200
    assert resp.json()["result"] == "NOT_FOUND"


# --- 14/15: event + activity log ---------------------------------------------------


def test_verification_creates_verification_event(client, db_session):
    from app.models.verification_event import VerificationEvent

    ctx = _setup(client, db_session)
    _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])

    event = (
        db_session.query(VerificationEvent)
        .filter(VerificationEvent.credential_id == uuid.UUID(ctx["credential"]["id"]))
        .first()
    )
    assert event is not None
    assert event.result.value == "VERIFIED"
    assert event.signature_valid is True


def test_verification_creates_activity_log(client, db_session):
    from app.models.activity_log import ActivityLog

    ctx = _setup(client, db_session)
    _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])

    log = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.entity_type == "credential", ActivityLog.entity_id == uuid.UUID(ctx["credential"]["id"]))
        .filter(ActivityLog.action == "CREDENTIAL_VERIFIED")
        .first()
    )
    assert log is not None
    assert log.metadata_["result"] == "VERIFIED"


# --- 16/17: no sensitive data leaked ------------------------------------------------


def test_no_private_key_or_filesystem_path_exposed(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    text = resp.text
    assert "PRIVATE KEY" not in text
    assert "private_key" not in text
    assert "storage_path" not in text
    assert "password_hash" not in text


# --- 18: the critical round-trip test ------------------------------------------------


def test_tamper_demo_does_not_corrupt_stored_credential(client, db_session):
    """
    The exact scenario from the spec: issue with CGPA 8.7, verify -> VERIFIED.
    Verify with a demo override of 9.7 -> INVALID, WITHOUT touching the
    database. Verify again with no override -> VERIFIED again, proving the
    tamper demonstration never corrupted the real stored credential.
    """
    ctx = _setup(client, db_session)
    cred_id = ctx["credential"]["id"]
    token = ctx["verifier"]["token"]

    first = _verify(client, token, cred_id).json()
    assert first["result"] == "VERIFIED"
    assert first["credential"]["cgpa"] == 8.7

    tampered = _verify(client, token, cred_id, demo_cgpa_override=9.7).json()
    assert tampered["result"] == "INVALID"
    assert tampered["checks"]["signature"] is False

    restored = _verify(client, token, cred_id).json()
    assert restored["result"] == "VERIFIED"
    assert restored["credential"]["cgpa"] == 8.7

    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(cred_id)).first()
    assert float(credential.cgpa) == 8.7  # never mutated in the database
