# ---------------------------------------------------------------------------
# Phase 4 integration tests: institution -> credential -> student, over real
# HTTP against the test app/DB, with document storage and signing keys
# redirected to temp dirs (see conftest.py's KEYS_PATH/STORAGE_PATH override).
# ---------------------------------------------------------------------------

import hashlib
import uuid

import pytest

from app.models.credential import Credential
from app.models.institution import Institution
from app.models.student import Student

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email="inst1@test.credchain.dev", name="Test University"):
    from app.models.institution import Institution

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


def _register_student(client, db_session, institution_id, email="student1@test.credchain.dev", identifier="STU-001"):
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

    return {"token": body["access_token"], "student_id": student_id, "user_id": body["user"]["id"]}


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
    return client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )


# --- 1/2: happy path -----------------------------------------------------------


def test_institution_can_issue_credential_to_valid_student(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["title"] == "Final Transcript"
    assert body["status"] == "active"
    assert body["cgpa"] == 8.7
    assert body["credential_identifier"].startswith("CRD-")
    assert body["document_hash"] == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()  # test 8
    assert body["signature"]  # test 11
    assert body["has_document"] is True
    assert "password_hash" not in body
    assert "storage_path" not in body


def test_student_receives_credential_after_issuance(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    issued = _issue(client, inst["token"], student["student_id"]).json()

    resp = client.get("/api/students/me/credentials", headers=_auth_header(student["token"]))
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert issued["id"] in ids


# --- 3: cross-student isolation --------------------------------------------------


def test_student_cannot_access_another_students_credential(client, db_session):
    inst = _register_institution(client, db_session)
    student_a = _register_student(client, db_session, inst["institution_id"], email="a@test.credchain.dev", identifier="STU-A")
    student_b = _register_student(client, db_session, inst["institution_id"], email="b@test.credchain.dev", identifier="STU-B")

    issued = _issue(client, inst["token"], student_a["student_id"]).json()

    resp = client.get(f"/api/credentials/{issued['id']}", headers=_auth_header(student_b["token"]))
    assert resp.status_code == 403


# --- 4: institution cannot issue for unaffiliated student ------------------------


def test_institution_cannot_issue_for_unaffiliated_student(client, db_session):
    inst_a = _register_institution(client, db_session, email="insta@test.credchain.dev", name="University A")
    inst_b = _register_institution(client, db_session, email="instb@test.credchain.dev", name="University B")
    # student affiliated with B
    student = _register_student(client, db_session, inst_b["institution_id"], email="crossaff@test.credchain.dev")

    resp = _issue(client, inst_a["token"], student["student_id"])
    assert resp.status_code == 403


def test_issuance_for_nonexistent_student_returns_404(client, db_session):
    inst = _register_institution(client, db_session)
    resp = _issue(client, inst["token"], str(uuid.uuid4()))
    assert resp.status_code == 404


# --- 5: role gating ------------------------------------------------------------------


def test_non_institution_cannot_issue_credentials(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    resp = _issue(client, student["token"], student["student_id"])
    assert resp.status_code == 403


# --- 6/7: document validation -----------------------------------------------------------


def test_non_pdf_upload_is_rejected(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    data = {
        "student_id": student["student_id"],
        "credential_type": "certification",
        "title": "Not a PDF",
    }
    files = {"document": ("notes.txt", b"just some text, not a pdf", "text/plain")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst["token"])
    )
    assert resp.status_code == 415


def test_pdf_extension_with_non_pdf_magic_bytes_is_rejected(client, db_session):
    """Filename/Content-Type alone must not be trusted — the magic-byte check is the real gate."""
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    data = {"student_id": student["student_id"], "credential_type": "certification", "title": "Fake PDF"}
    files = {"document": ("fake.pdf", b"NOT-A-REAL-PDF-HEADER", "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst["token"])
    )
    assert resp.status_code == 415


def test_oversized_upload_is_rejected(client, db_session, monkeypatch):
    from app.services import document_service

    monkeypatch.setattr(document_service.settings, "max_document_size_bytes", 10)  # 10 bytes, trivially exceeded

    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 413


def test_empty_document_is_rejected(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    data = {"student_id": student["student_id"], "credential_type": "certification", "title": "Empty"}
    files = {"document": ("empty.pdf", b"", "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst["token"])
    )
    assert resp.status_code == 400


# --- 9: credential identifier uniqueness ---------------------------------------------------


def test_credential_identifier_is_unique(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    first = _issue(client, inst["token"], student["student_id"]).json()
    second = _issue(client, inst["token"], student["student_id"], title="Second Credential").json()

    assert first["credential_identifier"] != second["credential_identifier"]
    assert first["id"] != second["id"]


# --- 13: institution public key persisted ------------------------------------------------------


def test_institution_public_key_is_persisted(client, db_session):
    inst = _register_institution(client, db_session)
    institution = db_session.query(Institution).filter(Institution.id == uuid.UUID(inst["institution_id"])).first()
    assert institution.public_key is not None
    assert "BEGIN PUBLIC KEY" in institution.public_key


# --- 14: private key never returned by any API response ------------------------------------------


def test_private_key_never_returned_by_api(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    issued = _issue(client, inst["token"], student["student_id"])

    responses_text = "".join(
        [
            client.get("/api/auth/me", headers=_auth_header(inst["token"])).text,
            issued.text,
            client.get("/api/institutions/me/credentials", headers=_auth_header(inst["token"])).text,
        ]
    )
    assert "PRIVATE KEY" not in responses_text
    assert "private_key" not in responses_text


# --- 15/16: persistence (survives a fresh query / "restart") -------------------------------------


def test_credential_persists_across_a_fresh_query(client, db_session):
    """
    Simulates surviving a backend restart: expire the session's identity map
    and re-query by primary key only (no reliance on Python-side object
    identity/cache) — proves the row is really in Postgres, not just held in
    memory by the object we got back from the POST.
    """
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    issued = _issue(client, inst["token"], student["student_id"]).json()

    db_session.expire_all()
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(issued["id"])).first()
    assert credential is not None
    assert credential.credential_identifier == issued["credential_identifier"]
    assert credential.document_hash == issued["document_hash"]

    # And the same holds through the actual read endpoint a second time (mirrors a frontend refresh).
    resp = client.get(f"/api/credentials/{issued['id']}", headers=_auth_header(student["token"]))
    assert resp.status_code == 200
    assert resp.json()["id"] == issued["id"]


# --- 17: activity log ------------------------------------------------------------------------------


def test_issuance_creates_activity_log(client, db_session):
    from app.models.activity_log import ActivityLog

    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    issued = _issue(client, inst["token"], student["student_id"]).json()

    log = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.entity_type == "credential", ActivityLog.entity_id == uuid.UUID(issued["id"]))
        .first()
    )
    assert log is not None
    assert log.action == "CREDENTIAL_ISSUED"
    assert log.metadata_["credential_identifier"] == issued["credential_identifier"]


# --- 18: failed issuance does not leave an orphaned document ---------------------------------------


def test_failed_issuance_does_not_leave_orphaned_document(client, db_session, monkeypatch):
    """
    Simulates a DB failure that happens AFTER the document is already written
    to disk (by making ActivityLog construction blow up, which in
    issue_credential happens after save_document but before commit) and
    proves the file is cleaned up rather than left orphaned.
    """
    from app.services import credential_service

    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])

    saved_paths: list[str] = []
    original_save = credential_service.document_service.save_document

    def _save_and_record(credential_id, data):
        path = original_save(credential_id, data)
        saved_paths.append(path)
        return path

    monkeypatch.setattr(credential_service.document_service, "save_document", _save_and_record)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure after file save")

    monkeypatch.setattr(credential_service, "ActivityLog", _boom)

    # The route only catches specific, expected exceptions — this
    # RuntimeError is deliberately not one of them, so it propagates all the
    # way up through TestClient rather than becoming an HTTP response.
    with pytest.raises(RuntimeError, match="simulated DB failure"):
        _issue(client, inst["token"], student["student_id"])

    assert len(saved_paths) == 1
    from pathlib import Path

    assert not Path(saved_paths[0]).exists(), "orphaned document file was not cleaned up after a failed transaction"
