# ---------------------------------------------------------------------------
# Job marketplace Phase B/C: real job postings + deterministic eligibility.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%job\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Job Verifier", "role": "verifier", "company_id": str(company.id)},
    )
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
        json={"email": email, "password": "Password123", "full_name": "Job Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Job Student {identifier}",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _job_payload(**overrides):
    payload = {
        "title": "Software Engineer",
        "description": "Build real things.",
        "employment_type": "full_time",
        "required_degree": "B.Tech Computer Science",
        "minimum_cgpa": 7.5,
        "graduation_year_requirement": 2026,
        "required_skills": ["Python", "SQL", "Data Structures"],
        "required_documents": ["Resume", "Transcript", "Degree Certificate"],
    }
    payload.update(overrides)
    return payload


def test_company_can_create_publish_edit_close_job(client, db_session):
    verifier = _register_verifier(client, db_session, "job-co-1@test.credchain.dev", "Job Co 1")

    create_resp = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(verifier["token"]))
    assert create_resp.status_code == 201, create_resp.text
    job = create_resp.json()
    assert job["status"] == "draft"

    publish_resp = client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "open"

    edit_resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"title": "Senior Software Engineer"}, headers=_auth_header(verifier["token"]))
    assert edit_resp.status_code == 200
    assert edit_resp.json()["title"] == "Senior Software Engineer"

    close_resp = client.post(f"/api/companies/me/jobs/{job['id']}/close", headers=_auth_header(verifier["token"]))
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "closed"

    # Cannot edit a closed job.
    edit_closed_resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"title": "x"}, headers=_auth_header(verifier["token"]))
    assert edit_closed_resp.status_code == 409


def test_company_cannot_modify_another_companys_job(client, db_session):
    verifier_a = _register_verifier(client, db_session, "job-co-a@test.credchain.dev", "Job Co A")
    verifier_b = _register_verifier(client, db_session, "job-co-b@test.credchain.dev", "Job Co B")

    job = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(verifier_a["token"])).json()

    resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"title": "hijacked"}, headers=_auth_header(verifier_b["token"]))
    assert resp.status_code == 403
    resp2 = client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier_b["token"]))
    assert resp2.status_code == 403


def test_student_only_sees_open_jobs_never_draft_or_default_company(client, db_session):
    verifier = _register_verifier(client, db_session, "job-co-2@test.credchain.dev", "Job Co 2")
    inst = _register_institution(client, db_session, "job-inst-2@test.credchain.dev", "Job University 2")
    student = _register_student(client, inst["institution_id"], "job-stu-2@test.credchain.dev", "JOB-STU-2")

    draft_job = client.post("/api/companies/me/jobs", json=_job_payload(title="Draft Job"), headers=_auth_header(verifier["token"])).json()
    open_job = client.post("/api/companies/me/jobs", json=_job_payload(title="Open Job"), headers=_auth_header(verifier["token"])).json()
    client.post(f"/api/companies/me/jobs/{open_job['id']}/publish", headers=_auth_header(verifier["token"]))

    list_resp = client.get("/api/jobs", headers=_auth_header(student["token"]))
    assert list_resp.status_code == 200
    page = list_resp.json()
    titles = [j["title"] for j in page["items"]]
    assert "Open Job" in titles
    assert "Draft Job" not in titles
    for j in page["items"]:
        assert j["company_name"] != "ABC Technologies"

    detail_resp = client.get(f"/api/jobs/{draft_job['id']}", headers=_auth_header(student["token"]))
    assert detail_resp.status_code == 404


def test_no_jobs_is_an_honest_empty_list(client, db_session):
    inst = _register_institution(client, db_session, "job-inst-empty@test.credchain.dev", "Job University Empty")
    student = _register_student(client, inst["institution_id"], "job-stu-empty@test.credchain.dev", "JOB-STU-EMPTY")
    resp = client.get("/api/jobs", headers=_auth_header(student["token"]))
    assert resp.status_code == 200
    page = resp.json()
    assert page["items"] == []
    assert page["total"] == 0


def test_eligibility_deterministic_mandatory_gate(client, db_session):
    verifier = _register_verifier(client, db_session, "job-co-3@test.credchain.dev", "Job Co 3")
    inst = _register_institution(client, db_session, "job-inst-3@test.credchain.dev", "Job University 3")
    student = _register_student(client, inst["institution_id"], "job-stu-3@test.credchain.dev", "JOB-STU-3")

    job = client.post(
        "/api/companies/me/jobs",
        json=_job_payload(minimum_cgpa=7.5, graduation_year_requirement=2026, required_degree="B.Tech Computer Science"),
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    # Before any credential: not eligible (mandatory gate fails).
    detail_before = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail_before["eligibility"]["is_eligible"] is False

    # Issue a real matching degree credential.
    files = {"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    client.post(
        "/api/institutions/me/credentials",
        data={
            "student_id": student["student_id"],
            "credential_type": "degree",
            "title": "B.Tech Degree",
            "degree": "B.Tech Computer Science",
            "graduation_year": "2026",
            "cgpa": "8.7",
        },
        files=files,
        headers=_auth_header(inst["token"]),
    )

    detail_after = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail_after["eligibility"]["is_eligible"] is True
    labels = {c["label"]: c["met"] for c in detail_after["eligibility"]["checks"]}
    assert labels["B.Tech Computer Science"] is True


def test_eligibility_low_cgpa_fails_mandatory_gate(client, db_session):
    verifier = _register_verifier(client, db_session, "job-co-4@test.credchain.dev", "Job Co 4")
    inst = _register_institution(client, db_session, "job-inst-4@test.credchain.dev", "Job University 4")
    student = _register_student(client, inst["institution_id"], "job-stu-4@test.credchain.dev", "JOB-STU-4")

    job = client.post(
        "/api/companies/me/jobs", json=_job_payload(minimum_cgpa=9.0, required_degree=None, graduation_year_requirement=None),
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    files = {"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["student_id"], "credential_type": "transcript", "title": "Transcript", "cgpa": "7.0"},
        files=files,
        headers=_auth_header(inst["token"]),
    )

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is False


def test_eligibility_skills_are_advisory_not_blocking(client, db_session):
    verifier = _register_verifier(client, db_session, "job-co-5@test.credchain.dev", "Job Co 5")
    inst = _register_institution(client, db_session, "job-inst-5@test.credchain.dev", "Job University 5")
    student = _register_student(client, inst["institution_id"], "job-stu-5@test.credchain.dev", "JOB-STU-5")

    job = client.post(
        "/api/companies/me/jobs",
        json=_job_payload(required_degree=None, minimum_cgpa=None, graduation_year_requirement=None, required_skills=["Rust"]),
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    # No mandatory requirements set, student has no "Rust" skill -> still eligible (skills are advisory).
    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is True
    labels = {c["label"]: c["met"] for c in detail["eligibility"]["checks"]}
    assert labels["Rust"] is False
