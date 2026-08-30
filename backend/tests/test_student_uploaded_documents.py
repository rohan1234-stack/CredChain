# ---------------------------------------------------------------------------
# PS3 Phase D: student-uploaded existing documents. The single most
# important invariant tested here: an uploaded document is UNVERIFIED and
# stays that way until an institution approves it — approval must go
# through the real signing pipeline (not a boolean flip), and a student can
# never self-approve.
# ---------------------------------------------------------------------------

import hashlib

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%stu-doc\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Doc Inst Admin", "role": "institution", "institution_id": str(institution.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Doc Student {identifier}",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return {"token": resp.json()["access_token"], "student_id": resp.json()["user"]["student_id"]}


def _upload(client, token, institution_id, credential_type="migration", **overrides):
    data = {"institution_id": institution_id, "credential_type": credential_type}
    data.update(overrides)
    files = {"document": ("old_migration_cert.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    return client.post("/api/students/me/documents", data=data, files=files, headers=_auth_header(token))


def test_upload_starts_unverified(client, db_session):
    inst = _register_institution(client, db_session, "doc-inst-1@test.credchain.dev", "Doc University 1")
    student = _register_student(client, inst["institution_id"], "doc-stu-1@test.credchain.dev", "DOC-STU-1")

    resp = _upload(client, student["token"], inst["institution_id"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "unverified"
    assert resp.json()["resulting_credential_id"] is None


def test_student_cannot_upload_for_unaffiliated_institution(client, db_session):
    inst_a = _register_institution(client, db_session, "doc-inst-a@test.credchain.dev", "Doc University A")
    inst_b = _register_institution(client, db_session, "doc-inst-b@test.credchain.dev", "Doc University B")
    student = _register_student(client, inst_a["institution_id"], "doc-stu-a@test.credchain.dev", "DOC-STU-A")

    resp = _upload(client, student["token"], inst_b["institution_id"])
    assert resp.status_code == 403


def test_student_has_no_approve_or_reject_endpoint(client, db_session):
    """The structural enforcement: there is no student-facing approve/reject path at all, not just a hidden button."""
    inst = _register_institution(client, db_session, "doc-inst-2@test.credchain.dev", "Doc University 2")
    student = _register_student(client, inst["institution_id"], "doc-stu-2@test.credchain.dev", "DOC-STU-2")
    doc_id = _upload(client, student["token"], inst["institution_id"]).json()["id"]

    # The only approve/reject routes live under /api/institutions/me/documents/*, gated by require_institution.
    approve_resp = client.post(f"/api/institutions/me/documents/{doc_id}/approve", headers=_auth_header(student["token"]))
    assert approve_resp.status_code == 403

    reject_resp = client.post(
        f"/api/institutions/me/documents/{doc_id}/reject", json={"reason": "self-rejecting"}, headers=_auth_header(student["token"])
    )
    assert reject_resp.status_code == 403


def test_institution_approval_creates_real_signed_credential(client, db_session):
    inst = _register_institution(client, db_session, "doc-inst-3@test.credchain.dev", "Doc University 3")
    student = _register_student(client, inst["institution_id"], "doc-stu-3@test.credchain.dev", "DOC-STU-3")
    doc_id = _upload(client, student["token"], inst["institution_id"], credential_type="migration").json()["id"]

    # Opening the document transitions UNVERIFIED -> UNDER_REVIEW.
    view_resp = client.get(f"/api/institutions/me/documents/{doc_id}", headers=_auth_header(inst["token"]))
    assert view_resp.status_code == 200
    assert view_resp.json()["status"] == "under_review"

    approve_resp = client.post(f"/api/institutions/me/documents/{doc_id}/approve", headers=_auth_header(inst["token"]))
    assert approve_resp.status_code == 200, approve_resp.text
    body = approve_resp.json()
    assert body["status"] == "approved"
    credential_id = body["resulting_credential_id"]
    assert credential_id is not None

    # The resulting row is a REAL credential: signed, hashed, independently fetchable and verifiable.
    cred_resp = client.get(f"/api/credentials/{credential_id}", headers=_auth_header(inst["token"]))
    assert cred_resp.status_code == 200
    cred = cred_resp.json()
    assert cred["signature"]
    assert cred["document_hash"] == hashlib.sha256(SAMPLE_PDF_BYTES).hexdigest()
    assert cred["credential_type"] == "migration"
    assert cred["status"] == "active"


def test_rejected_document_never_becomes_a_credential(client, db_session):
    inst = _register_institution(client, db_session, "doc-inst-4@test.credchain.dev", "Doc University 4")
    student = _register_student(client, inst["institution_id"], "doc-stu-4@test.credchain.dev", "DOC-STU-4")
    doc_id = _upload(client, student["token"], inst["institution_id"]).json()["id"]

    reject_resp = client.post(
        f"/api/institutions/me/documents/{doc_id}/reject",
        json={"reason": "Document quality too low to verify"},
        headers=_auth_header(inst["token"]),
    )
    assert reject_resp.status_code == 200
    body = reject_resp.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] == "Document quality too low to verify"
    assert body["resulting_credential_id"] is None

    # Student sees the rejection and reason on their own list.
    list_resp = client.get("/api/students/me/documents", headers=_auth_header(student["token"]))
    mine = next(d for d in list_resp.json() if d["id"] == doc_id)
    assert mine["status"] == "rejected"
    assert mine["rejection_reason"] == "Document quality too low to verify"


def test_company_cannot_treat_unverified_upload_as_a_credential(client, db_session):
    """
    The critical security boundary: an UNVERIFIED student upload is
    structurally invisible to the verification pipeline — there is no
    credential_id for it to be verified against until (and unless) it's
    approved and converted.
    """
    inst = _register_institution(client, db_session, "doc-inst-5@test.credchain.dev", "Doc University 5")
    student = _register_student(client, inst["institution_id"], "doc-stu-5@test.credchain.dev", "DOC-STU-5")
    doc = _upload(client, student["token"], inst["institution_id"]).json()

    from app.models.company import Company

    verify_company = Company(name="Doc Verify Co")
    db_session.add(verify_company)
    db_session.commit()
    db_session.refresh(verify_company)

    verifier_resp = client.post(
        "/api/auth/register",
        json={
            "email": "doc-verifier@test.credchain.dev",
            "password": "Password123",
            "full_name": "Doc Verifier",
            "role": "verifier",
            "company_id": str(verify_company.id),
        },
    )
    verifier_token = verifier_resp.json()["access_token"]

    # Trying to "verify" the document's own id (not a credential id) must not resolve to anything real.
    verify_resp = client.post(
        "/api/verification/verify", json={"credential_id": doc["id"]}, headers=_auth_header(verifier_token)
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["result"] == "NOT_FOUND"


def test_approval_with_academic_metadata_produces_trusted_credential(client, db_session):
    """
    Regression test for the real root cause behind "Minimum CGPA X.XX (no
    data on file)" for a student whose credential came through document
    approval rather than direct issuance: approve_document() used to
    hardcode degree/graduation_year/cgpa to None no matter what the
    institution reviewer could see on the actual PDF, so a document-approval
    credential could NEVER carry real academic metadata. This proves the
    institution can now confirm those values at approval time, that they
    land on the real signed Credential row, and that deterministic
    eligibility (unchanged) correctly reads them — 9.6 vs a 5.0 minimum must
    be ELIGIBLE, sourced entirely from the trusted credential, never from
    the PDF itself.
    """
    inst = _register_institution(client, db_session, "doc-inst-6@test.credchain.dev", "Doc University 6")
    student = _register_student(client, inst["institution_id"], "doc-stu-6@test.credchain.dev", "DOC-STU-6")
    doc_id = _upload(client, student["token"], inst["institution_id"], credential_type="transcript").json()["id"]

    approve_resp = client.post(
        f"/api/institutions/me/documents/{doc_id}/approve",
        json={"degree": "B.Tech Computer Science", "graduation_year": 2026, "cgpa": 9.6},
        headers=_auth_header(inst["token"]),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    credential_id = approve_resp.json()["resulting_credential_id"]
    assert credential_id is not None

    cred = client.get(f"/api/credentials/{credential_id}", headers=_auth_header(inst["token"])).json()
    assert cred["degree"] == "B.Tech Computer Science"
    assert cred["graduation_year"] == 2026
    assert cred["cgpa"] == 9.6

    # Deterministic eligibility (unmodified) reads this trusted metadata correctly.
    from app.models.company import Company

    verify_company_2 = Company(name="Doc Verify Co 2")
    db_session.add(verify_company_2)
    db_session.commit()
    db_session.refresh(verify_company_2)

    verifier_resp = client.post(
        "/api/auth/register",
        json={
            "email": "doc-verifier-2@test.credchain.dev",
            "password": "Password123",
            "full_name": "Doc Verifier 2",
            "role": "verifier",
            "company_id": str(verify_company_2.id),
        },
    )
    verifier_token = verifier_resp.json()["access_token"]
    job = client.post(
        "/api/companies/me/jobs",
        json={
            "title": "Software Engineer",
            "description": "Build real things.",
            "employment_type": "full_time",
            "required_degree": "B.Tech Computer Science",
            "minimum_cgpa": 5.0,
            "graduation_year_requirement": 2026,
        },
        headers=_auth_header(verifier_token),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier_token))

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["status"] == "eligible"
    assert detail["eligibility"]["is_eligible"] is True
    cgpa_check = next(c for c in detail["eligibility"]["checks"] if "CGPA" in c["label"])
    assert cgpa_check["met"] is True
    assert "9.60" in cgpa_check["label"]


def test_approval_without_academic_metadata_stays_empty(client, db_session):
    """The optional fields really are optional — a certification/other document approved with no metadata still produces a valid credential, exactly as before."""
    inst = _register_institution(client, db_session, "doc-inst-7@test.credchain.dev", "Doc University 7")
    student = _register_student(client, inst["institution_id"], "doc-stu-7@test.credchain.dev", "DOC-STU-7")
    doc_id = _upload(client, student["token"], inst["institution_id"], credential_type="certification").json()["id"]

    approve_resp = client.post(f"/api/institutions/me/documents/{doc_id}/approve", headers=_auth_header(inst["token"]))
    assert approve_resp.status_code == 200, approve_resp.text
    credential_id = approve_resp.json()["resulting_credential_id"]

    cred = client.get(f"/api/credentials/{credential_id}", headers=_auth_header(inst["token"])).json()
    assert cred["degree"] is None
    assert cred["graduation_year"] is None
    assert cred["cgpa"] is None


def test_approval_rejects_out_of_range_cgpa(client, db_session):
    """Approval-time metadata goes through the same range validation as direct issuance — not a separate, laxer path."""
    inst = _register_institution(client, db_session, "doc-inst-8@test.credchain.dev", "Doc University 8")
    student = _register_student(client, inst["institution_id"], "doc-stu-8@test.credchain.dev", "DOC-STU-8")
    doc_id = _upload(client, student["token"], inst["institution_id"], credential_type="transcript").json()["id"]

    approve_resp = client.post(
        f"/api/institutions/me/documents/{doc_id}/approve",
        json={"cgpa": 15.0},
        headers=_auth_header(inst["token"]),
    )
    assert approve_resp.status_code == 422


def test_cross_institution_cannot_see_or_review_documents(client, db_session):
    inst_a = _register_institution(client, db_session, "doc-inst-xa@test.credchain.dev", "Doc University XA")
    inst_b = _register_institution(client, db_session, "doc-inst-xb@test.credchain.dev", "Doc University XB")
    student = _register_student(client, inst_a["institution_id"], "doc-stu-xa@test.credchain.dev", "DOC-STU-XA")
    doc_id = _upload(client, student["token"], inst_a["institution_id"]).json()["id"]

    list_resp = client.get("/api/institutions/me/documents", headers=_auth_header(inst_b["token"]))
    assert all(d["id"] != doc_id for d in list_resp.json())

    view_resp = client.get(f"/api/institutions/me/documents/{doc_id}", headers=_auth_header(inst_b["token"]))
    assert view_resp.status_code == 403

    approve_resp = client.post(f"/api/institutions/me/documents/{doc_id}/approve", headers=_auth_header(inst_b["token"]))
    assert approve_resp.status_code == 403
