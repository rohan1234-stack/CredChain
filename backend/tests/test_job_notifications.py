# ---------------------------------------------------------------------------
# Job marketplace Phase L: company "new applications" count is real and
# self-clears when the company reviews an application.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%notif\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_company_new_application_count_is_real_and_clears_on_review(client, db_session):
    from app.models.company import Company
    from app.models.institution import Institution

    company = Company(name="Notif Job Co")
    institution = Institution(name="Notif Job Uni")
    db_session.add_all([company, institution])
    db_session.commit()
    db_session.refresh(company)
    db_session.refresh(institution)

    verifier = client.post(
        "/api/auth/register",
        json={"email": "notif-job-co@test.credchain.dev", "password": "Password123", "full_name": "X", "role": "verifier", "company_id": str(company.id)},
    ).json()
    inst = client.post(
        "/api/auth/register",
        json={"email": "notif-job-inst@test.credchain.dev", "password": "Password123", "full_name": "X", "role": "institution", "institution_id": str(institution.id)},
    ).json()
    student = client.post(
        "/api/auth/register",
        json={
            "email": "notif-job-stu@test.credchain.dev",
            "password": "Password123",
            "full_name": "X",
            "role": "student",
            "student_identifier": "NOTIF-JOB-STU",
            "institution_id": inst["user"]["institution_id"],
        },
    ).json()

    v_token, i_token, s_token = verifier["access_token"], inst["access_token"], student["access_token"]

    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "X", "description": "Y", "employment_type": "full_time", "required_documents": ["Migration Certificate"]},
        headers=_auth_header(v_token),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(v_token))

    counts_before = client.get("/api/notifications/me/counts", headers=_auth_header(v_token)).json()
    assert counts_before["new_job_applications"] == 0

    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    cred = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["user"]["student_id"], "credential_type": "migration", "title": "Migration Certificate"},
        files=files,
        headers=_auth_header(i_token),
    ).json()

    client.post("/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred["id"]]}, headers=_auth_header(s_token))

    counts_after = client.get("/api/notifications/me/counts", headers=_auth_header(v_token)).json()
    assert counts_after["new_job_applications"] == 1

    app_id = client.get("/api/companies/me/applications", headers=_auth_header(v_token)).json()[0]["id"]
    client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "under_review"}, headers=_auth_header(v_token))

    counts_cleared = client.get("/api/notifications/me/counts", headers=_auth_header(v_token)).json()
    assert counts_cleared["new_job_applications"] == 0
