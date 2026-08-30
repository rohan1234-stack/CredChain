# ---------------------------------------------------------------------------
# Phase B: rejection reasons, application withdrawal, and deadline
# enforcement on job applications. Reuses the exact apply/decision pipeline
# from test_job_applications.py (job_application_service, unmodified apart
# from adding rejection_reason + withdraw + deadline checks).
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%lifecycle\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Lifecycle Verifier", "role": "verifier", "company_id": str(company.id)},
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
        json={"email": email, "password": "Password123", "full_name": "Lifecycle Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Lifecycle Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _issue_credential(client, inst_token, student_id, credential_type, title):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": credential_type, "title": title},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_open_job(client, verifier_token, **overrides):
    payload = {
        "title": "Software Engineer",
        "description": "Real job.",
        "employment_type": "full_time",
        "required_documents": ["Migration Certificate"],
    }
    payload.update(overrides)
    job = client.post("/api/companies/me/jobs", json=payload, headers=_auth_header(verifier_token)).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier_token))
    return job


def _setup(client, db_session, suffix, **job_overrides):
    verifier = _register_verifier(client, db_session, f"lc-co-{suffix}@test.credchain.dev", f"Lifecycle Co {suffix}")
    inst = _register_institution(client, db_session, f"lc-inst-{suffix}@test.credchain.dev", f"Lifecycle Uni {suffix}")
    student = _register_student(client, inst["institution_id"], f"lc-stu-{suffix}@test.credchain.dev", f"LC-STU-{suffix}")
    job = _create_open_job(client, verifier["token"], **job_overrides)
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")
    return {"verifier": verifier, "inst": inst, "student": student, "job": job, "cred_id": cred_id}


def _apply(client, ctx):
    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": ctx["job"]["id"], "credential_ids": [ctx["cred_id"]]},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =====================================================================
# REJECTION REASON
# =====================================================================


def test_rejecting_an_application_without_a_reason_is_rejected(client, db_session):
    ctx = _setup(client, db_session, "1a")
    app = _apply(client, ctx)
    resp = client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "rejected"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 422


def test_rejecting_an_application_with_a_reason_stores_and_returns_it(client, db_session):
    ctx = _setup(client, db_session, "1b")
    app = _apply(client, ctx)
    resp = client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "rejected", "reason": "Required Migration Certificate was not provided."},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
    assert resp.json()["rejection_reason"] == "Required Migration Certificate was not provided."


def test_student_sees_rejection_reason_on_their_own_application(client, db_session):
    ctx = _setup(client, db_session, "1c")
    app = _apply(client, ctx)
    client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "rejected", "reason": "CGPA requirement not met."},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    listed = client.get("/api/students/me/applications", headers=_auth_header(ctx["student"]["token"])).json()
    mine = next(a for a in listed if a["id"] == app["id"])
    assert mine["status"] == "rejected"
    assert mine["rejection_reason"] == "CGPA requirement not met."


def test_rejection_reason_is_never_fabricated_when_still_pending(client, db_session):
    ctx = _setup(client, db_session, "1d")
    app = _apply(client, ctx)
    listed = client.get("/api/students/me/applications", headers=_auth_header(ctx["student"]["token"])).json()
    mine = next(a for a in listed if a["id"] == app["id"])
    assert mine["rejection_reason"] is None


def test_shortlisting_does_not_require_or_accept_a_reason_as_mandatory(client, db_session):
    ctx = _setup(client, db_session, "1e")
    app = _apply(client, ctx)
    client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "under_review"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    resp = client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "shortlisted"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "shortlisted"


# =====================================================================
# WITHDRAWAL
# =====================================================================


def test_student_can_withdraw_own_applied_application(client, db_session):
    ctx = _setup(client, db_session, "2a")
    app = _apply(client, ctx)
    resp = client.post(f"/api/students/me/applications/{app['id']}/withdraw", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "withdrawn"


def test_company_sees_withdrawn_status(client, db_session):
    ctx = _setup(client, db_session, "2b")
    app = _apply(client, ctx)
    client.post(f"/api/students/me/applications/{app['id']}/withdraw", headers=_auth_header(ctx["student"]["token"]))
    listed = client.get("/api/companies/me/applications", headers=_auth_header(ctx["verifier"]["token"])).json()
    mine = next(a for a in listed if a["id"] == app["id"])
    assert mine["status"] == "withdrawn"


def test_cannot_withdraw_an_accepted_application(client, db_session):
    ctx = _setup(client, db_session, "2c")
    app = _apply(client, ctx)
    client.post(f"/api/companies/me/applications/{app['id']}/status", json={"status": "under_review"}, headers=_auth_header(ctx["verifier"]["token"]))
    client.post(f"/api/companies/me/applications/{app['id']}/status", json={"status": "shortlisted"}, headers=_auth_header(ctx["verifier"]["token"]))
    client.post(f"/api/companies/me/applications/{app['id']}/status", json={"status": "accepted"}, headers=_auth_header(ctx["verifier"]["token"]))

    resp = client.post(f"/api/students/me/applications/{app['id']}/withdraw", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 409


def test_other_student_cannot_withdraw_someone_elses_application(client, db_session):
    ctx = _setup(client, db_session, "2d")
    app = _apply(client, ctx)
    other = _register_student(client, ctx["inst"]["institution_id"], "lc-other-2d@test.credchain.dev", "LC-OTHER-2d")
    resp = client.post(f"/api/students/me/applications/{app['id']}/withdraw", headers=_auth_header(other["token"]))
    assert resp.status_code == 403


# =====================================================================
# DEADLINE ENFORCEMENT
# =====================================================================


def test_application_after_deadline_is_rejected(client, db_session):
    from app.models.job import Job
    import uuid as uuid_mod

    ctx = _setup(client, db_session, "3a")
    job_row = db_session.get(Job, uuid_mod.UUID(ctx["job"]["id"]))
    job_row.application_deadline = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": ctx["job"]["id"], "credential_ids": [ctx["cred_id"]]},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 409


def test_application_before_deadline_still_succeeds(client, db_session):
    ctx = _setup(client, db_session, "3b", application_deadline=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat())
    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": ctx["job"]["id"], "credential_ids": [ctx["cred_id"]]},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 201, resp.text
