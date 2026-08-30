# ---------------------------------------------------------------------------
# Job marketplace Phase E: AI job analysis is driven ONLY by a real job_id —
# never client-supplied company/job text — and reuses the existing analyzer
# functions unchanged.
# ---------------------------------------------------------------------------

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
        json={"email": email, "password": "Password123", "full_name": "AI Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    return {"token": resp.json()["access_token"]}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "AI Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    return {"token": resp.json()["access_token"], "institution_id": resp.json()["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "AI Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    return {"token": resp.json()["access_token"]}


def test_analyze_real_job_returns_real_company_and_job_data(client, db_session):
    verifier = _register_verifier(client, db_session, "ai-co-1@test.credchain.dev", "AI Analysis Co 1")
    inst = _register_institution(client, db_session, "ai-inst-1@test.credchain.dev", "AI University 1")
    student = _register_student(client, inst["institution_id"], "ai-stu-1@test.credchain.dev", "AI-STU-1")

    job = client.post(
        "/api/companies/me/jobs",
        json={
            "title": "Backend Engineer",
            "description": "Work on real backend systems using Python and SQL.",
            "employment_type": "full_time",
            "required_skills": ["Python", "SQL"],
            "required_documents": ["Resume", "Transcript"],
        },
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    resp = client.post(f"/api/ai/analyze-job/{job['id']}", headers=_auth_header(student["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company_name"] == "AI Analysis Co 1"
    assert body["job_title"] == "Backend Engineer"
    assert body["company_name"] != "ABC Technologies"
    assert "eligibility" in body
    assert "document_requirements" in body
    assert "credential_match" in body
    # Fallback mode (no AI key configured in tests) must be clearly labeled, never disguised as real AI output.
    assert body["credential_match"]["analysis_mode"] in ("ai", "fallback")


def test_analyze_nonexistent_job_404(client, db_session):
    import uuid

    inst = _register_institution(client, db_session, "ai-inst-2@test.credchain.dev", "AI University 2")
    student = _register_student(client, inst["institution_id"], "ai-stu-2@test.credchain.dev", "AI-STU-2")
    resp = client.post(f"/api/ai/analyze-job/{uuid.uuid4()}", headers=_auth_header(student["token"]))
    assert resp.status_code == 404


def test_analyze_job_requires_student_role(client, db_session):
    verifier = _register_verifier(client, db_session, "ai-co-3@test.credchain.dev", "AI Analysis Co 3")
    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "X", "description": "Y", "employment_type": "internship"},
        headers=_auth_header(verifier["token"]),
    ).json()
    resp = client.post(f"/api/ai/analyze-job/{job['id']}", headers=_auth_header(verifier["token"]))
    assert resp.status_code == 403
