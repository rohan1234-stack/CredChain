# ---------------------------------------------------------------------------
# Phase 8A tests: real credential revocation.
#
# Verification behavior (a revoked credential must return REVOKED, never
# VERIFIED) is tested here too, but only as a consumer of the existing
# Phase 5 verification_service — nothing about verification is changed or
# duplicated by this phase, exactly as instructed.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timedelta, timezone

from app.models.activity_log import ActivityLog
from app.models.credential import Credential
from app.models.enums import CredentialStatus
from app.models.share_grant import ShareGrant, ShareGrantCredential

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


def _register_institution(client, db_session, email="revoke-inst@test.credchain.dev", name="Test University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="revoke-student@test.credchain.dev", identifier="STU-REV-001"):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="revoke-verifier@test.credchain.dev", name="Test Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue(client, institution_token, student_id, **overrides) -> dict:
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


def _setup(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue(client, inst["token"], student["student_id"])
    return {"inst": inst, "student": student, "credential": credential}


def _revoke(client, token, credential_id):
    return client.post(f"/api/credentials/{credential_id}/revoke", headers=_auth_header(token))


# --- 1: institution successfully revokes own credential ------------------------------


def test_institution_revokes_own_credential(client, db_session):
    ctx = _setup(client, db_session)
    resp = _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "revoked"
    assert body["revoked_at"] is not None


# --- 2: institution cannot revoke another institution's credential ---------------------


def test_institution_cannot_revoke_another_institutions_credential(client, db_session):
    ctx = _setup(client, db_session)
    other_inst = _register_institution(client, db_session, email="other-inst@test.credchain.dev", name="Other University")

    resp = _revoke(client, other_inst["token"], ctx["credential"]["id"])
    assert resp.status_code == 403


# --- 3: student cannot revoke credential --------------------------------------------------


def test_student_cannot_revoke_credential(client, db_session):
    ctx = _setup(client, db_session)
    resp = _revoke(client, ctx["student"]["token"], ctx["credential"]["id"])
    assert resp.status_code == 403


# --- 4: company cannot revoke credential --------------------------------------------------


def test_company_cannot_revoke_credential(client, db_session):
    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session)
    resp = _revoke(client, verifier["token"], ctx["credential"]["id"])
    assert resp.status_code == 403


# --- 5: unauthenticated request is rejected -----------------------------------------------


def test_unauthenticated_revoke_rejected(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/revoke")
    assert resp.status_code == 401


# --- 6/7: status + revoked_at persisted in the database -----------------------------------


def test_status_and_revoked_at_persisted(client, db_session):
    ctx = _setup(client, db_session)
    before = datetime.now(timezone.utc)
    _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])

    db_session.expire_all()
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    assert credential.status == CredentialStatus.REVOKED
    assert credential.revoked_at is not None
    assert credential.revoked_at >= before - timedelta(seconds=5)
    # The record itself, its signature, and its document are all preserved — never deleted.
    assert credential.signature is not None
    assert credential.document is not None


# --- 8: revoked credential cannot verify as VERIFIED ----------------------------------------


def test_revoked_credential_cannot_verify_as_verified(client, db_session):
    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session, email="revoke-verify-check@test.credchain.dev")

    grant = ShareGrant(
        student_id=uuid.UUID(ctx["student"]["student_id"]),
        company_id=uuid.UUID(verifier["company_id"]),
        share_token_hash="test-token-hash-" + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(grant)
    db_session.flush()
    db_session.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=uuid.UUID(ctx["credential"]["id"])))
    db_session.commit()

    # Verified while still active.
    pre_revoke = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(verifier["token"]),
    )
    assert pre_revoke.json()["result"] == "VERIFIED"

    _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])

    post_revoke = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(verifier["token"]),
    )
    body = post_revoke.json()
    assert body["result"] == "REVOKED"
    assert body["result"] != "VERIFIED"
    # Signature is still valid — revocation is a status fact, not a corruption of the credential.
    assert body["checks"]["signature"] is True
    assert body["checks"]["status"] is False


# --- 9: revocation creates an ActivityLog entry ---------------------------------------------


def test_revocation_creates_activity_log(client, db_session):
    ctx = _setup(client, db_session)
    _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])

    log = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.action == "CREDENTIAL_REVOKED", ActivityLog.entity_id == uuid.UUID(ctx["credential"]["id"]))
        .first()
    )
    assert log is not None
    assert log.entity_type == "credential"
    assert log.metadata_["credential_identifier"] == ctx["credential"]["credential_identifier"]


# --- 10: revoke is safely handled when already revoked (idempotent, no corruption) ----------


def test_revoke_already_revoked_handled_safely(client, db_session):
    ctx = _setup(client, db_session)
    first = _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])
    assert first.status_code == 200
    first_revoked_at = first.json()["revoked_at"]

    second = _revoke(client, ctx["inst"]["token"], ctx["credential"]["id"])
    assert second.status_code == 409

    # State was not corrupted by the second attempt — revoked_at unchanged, still revoked.
    db_session.expire_all()
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    assert credential.status == CredentialStatus.REVOKED
    first_revoked_dt = datetime.fromisoformat(first_revoked_at.replace("Z", "+00:00"))
    assert credential.revoked_at == first_revoked_dt

    # Only one CREDENTIAL_REVOKED activity log entry was ever created.
    logs = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.action == "CREDENTIAL_REVOKED", ActivityLog.entity_id == uuid.UUID(ctx["credential"]["id"]))
        .all()
    )
    assert len(logs) == 1
