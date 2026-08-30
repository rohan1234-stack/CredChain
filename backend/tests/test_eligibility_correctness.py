# ---------------------------------------------------------------------------
# Phase C: eligibility correctness. The reported bug ("CGPA 9.6 vs required
# 9.0 shows Not eligible") was NOT a comparison-logic bug — reproduced live
# against the real dev DB and found the actual root cause: the specific
# test student's real credentials simply had no cgpa value stored at all,
# so eligibility_service correctly (if unhelpfully) reported the mandatory
# CGPA check as failed, because a missing value was being treated
# identically to a failing value.
#
# This file proves two things with REAL credential data (never hardcoded
# student values, never demo assumptions):
#   1. The comparison itself is and was correct: 9.6 >= 9.0 -> eligible.
#   2. The real fix: a genuinely MISSING value is now reported as
#      status="incomplete", never silently collapsed into "not_met" or
#      "met" — see eligibility_service.py.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%elig\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Elig Verifier", "role": "verifier", "company_id": str(company.id)},
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
        json={"email": email, "password": "Password123", "full_name": "Elig Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Elig Student",
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
    data = {"student_id": student_id, "credential_type": "transcript", "title": "Transcript"}
    data.update({k: str(v) for k, v in overrides.items()})
    resp = client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst_token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _job_payload(**overrides):
    payload = {
        "title": "Software Engineer",
        "description": "Build real things.",
        "employment_type": "full_time",
    }
    payload.update(overrides)
    return payload


def _create_open_job(client, verifier_token, **overrides):
    job = client.post("/api/companies/me/jobs", json=_job_payload(**overrides), headers=_auth_header(verifier_token)).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier_token))
    return job


def test_cgpa_96_vs_required_90_is_eligible(client, db_session):
    """The exact reported scenario: a real 9.6 CGPA against a 9.0 minimum must PASS."""
    verifier = _register_verifier(client, db_session, "elig-co-1@test.credchain.dev", "Elig Co 1")
    inst = _register_institution(client, db_session, "elig-inst-1@test.credchain.dev", "Elig University 1")
    student = _register_student(client, inst["institution_id"], "elig-stu-1@test.credchain.dev", "ELIG-STU-1")
    job = _create_open_job(client, verifier["token"], minimum_cgpa=9.0)

    _issue(client, inst["token"], student["student_id"], cgpa="9.6")

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is True
    assert detail["eligibility"]["status"] == "eligible"
    check = next(c for c in detail["eligibility"]["checks"] if "CGPA" in c["label"])
    assert check["met"] is True
    assert check["status"] == "met"


def test_cgpa_89_vs_required_90_fails(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-2@test.credchain.dev", "Elig Co 2")
    inst = _register_institution(client, db_session, "elig-inst-2@test.credchain.dev", "Elig University 2")
    student = _register_student(client, inst["institution_id"], "elig-stu-2@test.credchain.dev", "ELIG-STU-2")
    job = _create_open_job(client, verifier["token"], minimum_cgpa=9.0)

    _issue(client, inst["token"], student["student_id"], cgpa="8.9")

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is False
    assert detail["eligibility"]["status"] == "not_eligible"
    check = next(c for c in detail["eligibility"]["checks"] if "CGPA" in c["label"])
    assert check["status"] == "not_met"


def test_missing_cgpa_is_incomplete_not_a_silent_pass_or_fail(client, db_session):
    """The real root cause of the reported bug: a genuinely missing value must be its own state, not folded into met/not_met."""
    verifier = _register_verifier(client, db_session, "elig-co-3@test.credchain.dev", "Elig Co 3")
    inst = _register_institution(client, db_session, "elig-inst-3@test.credchain.dev", "Elig University 3")
    student = _register_student(client, inst["institution_id"], "elig-stu-3@test.credchain.dev", "ELIG-STU-3")
    job = _create_open_job(client, verifier["token"], minimum_cgpa=9.0)

    # Issue a credential that carries no cgpa value at all (exactly the real dev-DB scenario found live).
    _issue(client, inst["token"], student["student_id"])

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is False  # never auto-PASS
    assert detail["eligibility"]["status"] == "incomplete"  # and never conflated with a real FAIL
    check = next(c for c in detail["eligibility"]["checks"] if "CGPA" in c["label"])
    assert check["status"] == "incomplete"
    assert check["met"] is False


def test_degree_exact_match_passes(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-4@test.credchain.dev", "Elig Co 4")
    inst = _register_institution(client, db_session, "elig-inst-4@test.credchain.dev", "Elig University 4")
    student = _register_student(client, inst["institution_id"], "elig-stu-4@test.credchain.dev", "ELIG-STU-4")
    job = _create_open_job(client, verifier["token"], required_degree="B.Tech Computer Science")

    _issue(client, inst["token"], student["student_id"], degree="B.Tech Computer Science")

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is True
    check = next(c for c in detail["eligibility"]["checks"] if c["label"] == "B.Tech Computer Science")
    assert check["status"] == "met"


def test_wrong_degree_fails(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-5@test.credchain.dev", "Elig Co 5")
    inst = _register_institution(client, db_session, "elig-inst-5@test.credchain.dev", "Elig University 5")
    student = _register_student(client, inst["institution_id"], "elig-stu-5@test.credchain.dev", "ELIG-STU-5")
    job = _create_open_job(client, verifier["token"], required_degree="B.Tech Computer Science")

    _issue(client, inst["token"], student["student_id"], degree="B.A. History")

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is False
    check = next(c for c in detail["eligibility"]["checks"] if c["label"] == "B.Tech Computer Science")
    assert check["status"] == "not_met"


def test_graduation_year_match_passes_and_mismatch_fails(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-6@test.credchain.dev", "Elig Co 6")
    inst = _register_institution(client, db_session, "elig-inst-6@test.credchain.dev", "Elig University 6")
    student_ok = _register_student(client, inst["institution_id"], "elig-stu-6a@test.credchain.dev", "ELIG-STU-6A")
    student_bad = _register_student(client, inst["institution_id"], "elig-stu-6b@test.credchain.dev", "ELIG-STU-6B")
    job = _create_open_job(client, verifier["token"], graduation_year_requirement=2026)

    _issue(client, inst["token"], student_ok["student_id"], graduation_year="2026")
    _issue(client, inst["token"], student_bad["student_id"], graduation_year="2027")

    ok = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student_ok["token"])).json()
    bad = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student_bad["token"])).json()
    assert ok["eligibility"]["is_eligible"] is True
    assert bad["eligibility"]["is_eligible"] is False


def test_revoked_credential_does_not_count_as_eligibility_evidence(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-7@test.credchain.dev", "Elig Co 7")
    inst = _register_institution(client, db_session, "elig-inst-7@test.credchain.dev", "Elig University 7")
    student = _register_student(client, inst["institution_id"], "elig-stu-7@test.credchain.dev", "ELIG-STU-7")
    job = _create_open_job(client, verifier["token"], minimum_cgpa=9.0)

    cred_id = _issue(client, inst["token"], student["student_id"], cgpa="9.8")
    revoke_resp = client.post(f"/api/credentials/{cred_id}/revoke", headers=_auth_header(inst["token"]))
    assert revoke_resp.status_code == 200, revoke_resp.text

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is False
    assert detail["eligibility"]["status"] == "incomplete"  # no ACTIVE credential carries a cgpa anymore


def test_combined_requirements_all_pass_together(client, db_session):
    verifier = _register_verifier(client, db_session, "elig-co-8@test.credchain.dev", "Elig Co 8")
    inst = _register_institution(client, db_session, "elig-inst-8@test.credchain.dev", "Elig University 8")
    student = _register_student(client, inst["institution_id"], "elig-stu-8@test.credchain.dev", "ELIG-STU-8")
    job = _create_open_job(
        client, verifier["token"], required_degree="B.Tech CSE", minimum_cgpa=9.0, graduation_year_requirement=2026
    )

    _issue(client, inst["token"], student["student_id"], degree="B.Tech CSE", cgpa="9.6", graduation_year="2026")

    detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    assert detail["eligibility"]["is_eligible"] is True
    assert detail["eligibility"]["status"] == "eligible"
    assert all(c["status"] == "met" for c in detail["eligibility"]["checks"] if c["mandatory"])


def test_ai_job_analysis_uses_the_same_deterministic_eligibility(client, db_session):
    """Single source of truth: the AI endpoint's eligibility section must match the job endpoint's, never a second computation."""
    verifier = _register_verifier(client, db_session, "elig-co-9@test.credchain.dev", "Elig Co 9")
    inst = _register_institution(client, db_session, "elig-inst-9@test.credchain.dev", "Elig University 9")
    student = _register_student(client, inst["institution_id"], "elig-stu-9@test.credchain.dev", "ELIG-STU-9")
    job = _create_open_job(client, verifier["token"], minimum_cgpa=9.0)

    _issue(client, inst["token"], student["student_id"], cgpa="9.6")

    job_detail = client.get(f"/api/jobs/{job['id']}", headers=_auth_header(student["token"])).json()
    ai_resp = client.post(f"/api/ai/analyze-job/{job['id']}", headers=_auth_header(student["token"]))
    assert ai_resp.status_code == 200, ai_resp.text
    assert ai_resp.json()["eligibility"]["is_eligible"] == job_detail["eligibility"]["is_eligible"]
    assert ai_resp.json()["eligibility"]["status"] == job_detail["eligibility"]["status"]
