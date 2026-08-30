# ---------------------------------------------------------------------------
# Phase E / Issue 21: the company application view must carry the
# applicant's real deterministic eligibility for that job — computed via
# the SAME eligibility_service the student's own job page uses (single
# source of truth, never a second computation, never AI-decided) — so a
# reviewer doesn't have to open a separate page to see it.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%review\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Review Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Review Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Review Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _issue(client, inst_token, student_id, **overrides):
    files = {"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"student_id": student_id, "credential_type": "migration", "title": "Migration Certificate"}
    data.update({k: str(v) for k, v in overrides.items()})
    resp = client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst_token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_company_sees_real_eligibility_on_the_application(client, db_session):
    verifier = _register_verifier(client, db_session, "review-co-1@test.credchain.dev", "Review Co 1")
    inst = _register_institution(client, db_session, "review-inst-1@test.credchain.dev", "Review University 1")
    student = _register_student(client, inst["institution_id"], "review-stu-1@test.credchain.dev", "REVIEW-STU-1")

    job = client.post(
        "/api/companies/me/jobs",
        json={
            "title": "Engineer",
            "description": "Real.",
            "employment_type": "full_time",
            "minimum_cgpa": 9.0,
            "required_documents": ["Migration Certificate"],
        },
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    cred_id = _issue(client, inst["token"], student["student_id"], cgpa="9.6")
    apply_resp = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert apply_resp.status_code == 201, apply_resp.text

    listed = client.get("/api/companies/me/applications", headers=_auth_header(verifier["token"])).json()
    assert len(listed) == 1
    assert listed[0]["eligibility"]["is_eligible"] is True
    assert listed[0]["eligibility"]["status"] == "eligible"


def test_company_sees_not_eligible_applicant_too_never_hides_it(client, db_session):
    """The company must see the real result even when it's unfavorable — never suppressed or fabricated as eligible."""
    verifier = _register_verifier(client, db_session, "review-co-2@test.credchain.dev", "Review Co 2")
    inst = _register_institution(client, db_session, "review-inst-2@test.credchain.dev", "Review University 2")
    student = _register_student(client, inst["institution_id"], "review-stu-2@test.credchain.dev", "REVIEW-STU-2")

    job = client.post(
        "/api/companies/me/jobs",
        json={
            "title": "Engineer",
            "description": "Real.",
            "employment_type": "full_time",
            "minimum_cgpa": 9.0,
            "required_documents": ["Migration Certificate"],
        },
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    cred_id = _issue(client, inst["token"], student["student_id"], cgpa="6.0")
    client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )

    listed = client.get("/api/companies/me/applications", headers=_auth_header(verifier["token"])).json()
    assert listed[0]["eligibility"]["is_eligible"] is False
    assert listed[0]["eligibility"]["status"] == "not_eligible"
