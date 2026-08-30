# ---------------------------------------------------------------------------
# Phase D: draft job editing. PATCH /companies/me/jobs/{id} already existed
# from an earlier phase; this proves the safety rule requested in the audit
# (Issue 5/20): once a job has real applications, its eligibility-affecting
# fields (degree, CGPA, graduation year, required documents) become locked
# so an existing application is never left inconsistent with requirements
# that changed underneath it. Everything else stays editable until closed.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%draft\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Draft Verifier", "role": "verifier", "company_id": str(company.id)},
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
        json={"email": email, "password": "Password123", "full_name": "Draft Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Draft Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _issue_credential(client, inst_token, student_id):
    files = {"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": "migration", "title": "Migration Certificate"},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_draft_job_is_fully_editable(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-1@test.credchain.dev", "Draft Co 1")
    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time", "minimum_cgpa": 7.0},
        headers=_auth_header(verifier["token"]),
    ).json()

    resp = client.patch(
        f"/api/companies/me/jobs/{job['id']}",
        json={"title": "Senior Engineer", "minimum_cgpa": 8.5, "required_degree": "B.Tech CSE"},
        headers=_auth_header(verifier["token"]),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["title"] == "Senior Engineer"
    assert updated["minimum_cgpa"] == 8.5
    assert updated["required_degree"] == "B.Tech CSE"


def test_draft_job_edit_then_publish_reflects_edits(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-2@test.credchain.dev", "Draft Co 2")
    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time"},
        headers=_auth_header(verifier["token"]),
    ).json()
    client.patch(f"/api/companies/me/jobs/{job['id']}", json={"description": "Updated description."}, headers=_auth_header(verifier["token"]))
    publish_resp = client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))
    assert publish_resp.status_code == 200
    assert publish_resp.json()["description"] == "Updated description."


def test_eligibility_fields_locked_once_a_real_application_exists(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-3@test.credchain.dev", "Draft Co 3")
    inst = _register_institution(client, db_session, "draft-inst-3@test.credchain.dev", "Draft University 3")
    student = _register_student(client, inst["institution_id"], "draft-stu-3@test.credchain.dev", "DRAFT-STU-3")
    cred_id = _issue_credential(client, inst["token"], student["student_id"])

    job = client.post(
        "/api/companies/me/jobs",
        json={
            "title": "Engineer",
            "description": "Real.",
            "employment_type": "full_time",
            "minimum_cgpa": 7.0,
            "required_documents": ["Migration Certificate"],
        },
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    apply_resp = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert apply_resp.status_code == 201, apply_resp.text

    # Now try to raise the CGPA requirement — must be locked.
    resp = client.patch(
        f"/api/companies/me/jobs/{job['id']}", json={"minimum_cgpa": 9.0}, headers=_auth_header(verifier["token"])
    )
    assert resp.status_code == 409


def test_non_eligibility_fields_remain_editable_after_application_exists(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-4@test.credchain.dev", "Draft Co 4")
    inst = _register_institution(client, db_session, "draft-inst-4@test.credchain.dev", "Draft University 4")
    student = _register_student(client, inst["institution_id"], "draft-stu-4@test.credchain.dev", "DRAFT-STU-4")
    cred_id = _issue_credential(client, inst["token"], student["student_id"])

    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time", "required_documents": ["Migration Certificate"]},
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))
    client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )

    resp = client.patch(
        f"/api/companies/me/jobs/{job['id']}",
        json={"description": "Revised description after applications came in.", "location": "Remote"},
        headers=_auth_header(verifier["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Revised description after applications came in."
    assert resp.json()["location"] == "Remote"


def test_resubmitting_unchanged_eligibility_value_is_not_blocked(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-5@test.credchain.dev", "Draft Co 5")
    inst = _register_institution(client, db_session, "draft-inst-5@test.credchain.dev", "Draft University 5")
    student = _register_student(client, inst["institution_id"], "draft-stu-5@test.credchain.dev", "DRAFT-STU-5")
    cred_id = _issue_credential(client, inst["token"], student["student_id"])

    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time", "minimum_cgpa": 7.0, "required_documents": ["Migration Certificate"]},
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))
    client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )

    resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"minimum_cgpa": 7.0}, headers=_auth_header(verifier["token"]))
    assert resp.status_code == 200


def test_closed_job_cannot_be_edited_at_all(client, db_session):
    verifier = _register_verifier(client, db_session, "draft-co-6@test.credchain.dev", "Draft Co 6")
    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time"},
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))
    client.post(f"/api/companies/me/jobs/{job['id']}/close", headers=_auth_header(verifier["token"]))

    resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"title": "New Title"}, headers=_auth_header(verifier["token"]))
    assert resp.status_code == 409


def test_other_company_cannot_edit_a_draft_they_do_not_own(client, db_session):
    verifier_a = _register_verifier(client, db_session, "draft-co-7a@test.credchain.dev", "Draft Co 7A")
    verifier_b = _register_verifier(client, db_session, "draft-co-7b@test.credchain.dev", "Draft Co 7B")
    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Engineer", "description": "Real.", "employment_type": "full_time"},
        headers=_auth_header(verifier_a["token"]),
    ).json()

    resp = client.patch(f"/api/companies/me/jobs/{job['id']}", json={"title": "Hijacked"}, headers=_auth_header(verifier_b["token"]))
    assert resp.status_code == 403
