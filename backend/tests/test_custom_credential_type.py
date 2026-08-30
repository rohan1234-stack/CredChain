# ---------------------------------------------------------------------------
# PS3 Phase A: CredentialType.OTHER — a custom credential name is just the
# existing free-text `title` field with credential_type="other". No new
# column, no change anywhere in the signing/verification pipeline — these
# tests exist to prove that's actually true end-to-end, not just on paper.
# ---------------------------------------------------------------------------

import hashlib

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email="custom-inst@test.credchain.dev", name="Custom Type University"):
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
            "full_name": "Custom Inst Admin",
            "role": "institution",
            "institution_id": str(institution.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email="custom-stu@test.credchain.dev", identifier="CUSTOM-STU-001"):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "Custom Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def test_issue_custom_credential_type_persists_custom_name(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, inst["institution_id"])

    files = {"document": ("bonafide.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["student_id"], "credential_type": "other", "title": "Bonafide Certificate"},
        files=files,
        headers=_auth_header(inst["token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["credential_type"] == "other"
    assert body["title"] == "Bonafide Certificate"
    assert body["document_hash"] == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert body["signature"]


def test_custom_credential_type_verifies_like_any_other(client, db_session):
    inst = _register_institution(client, db_session, email="custom-inst-v@test.credchain.dev", name="Custom Verify University")
    student = _register_student(client, inst["institution_id"], email="custom-stu-v@test.credchain.dev", identifier="CUSTOM-STU-V")

    files = {"document": ("transfer.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    issue_resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["student_id"], "credential_type": "other", "title": "Transfer Certificate"},
        files=files,
        headers=_auth_header(inst["token"]),
    )
    assert issue_resp.status_code == 201, issue_resp.text
    credential_id = issue_resp.json()["id"]

    from app.models.company import Company

    verify_company = Company(name="Custom Verify Co")
    db_session.add(verify_company)
    db_session.commit()
    db_session.refresh(verify_company)

    verifier_resp = client.post(
        "/api/auth/register",
        json={
            "email": "custom-verifier@test.credchain.dev",
            "password": "Password123",
            "full_name": "Custom Verifier",
            "role": "verifier",
            "company_id": str(verify_company.id),
        },
    )
    assert verifier_resp.status_code == 201, verifier_resp.text
    verifier_token = verifier_resp.json()["access_token"]

    req_resp = client.post(
        "/api/credential-requests",
        json={
            "student_identifier": "CUSTOM-STU-V",
            "purpose": "Custom type test",
            "requested_credentials": ["Transfer Certificate"],
        },
        headers=_auth_header(verifier_token),
    )
    assert req_resp.status_code == 201, req_resp.text
    request_id = req_resp.json()["id"]

    approve_resp = client.post(
        f"/api/credential-requests/{request_id}/approve",
        json={"credential_ids": [credential_id], "expires_in_days": 7},
        headers=_auth_header(student["token"]),
    )
    assert approve_resp.status_code == 200, approve_resp.text

    verify_resp = client.post(
        "/api/verification/verify",
        json={"credential_id": credential_id},
        headers=_auth_header(verifier_token),
    )
    assert verify_resp.status_code == 200, verify_resp.text
    assert verify_resp.json()["result"] == "VERIFIED"
    assert verify_resp.json()["credential"]["credential_type"] == "other"
    assert verify_resp.json()["credential"]["title"] == "Transfer Certificate"


def test_empty_title_is_rejected(client, db_session):
    inst = _register_institution(client, db_session, email="empty-title-inst@test.credchain.dev", name="Empty Title University")
    student = _register_student(client, inst["institution_id"], email="empty-title-stu@test.credchain.dev", identifier="EMPTY-TITLE-STU")

    files = {"document": ("doc.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["student_id"], "credential_type": "degree", "title": "   "},
        files=files,
        headers=_auth_header(inst["token"]),
    )
    assert resp.status_code == 422, resp.text
