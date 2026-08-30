# ---------------------------------------------------------------------------
# Workflow timeline data layer (Prompt 1): job_application_service.
# get_application_history and the `history` field it feeds on Student/
# CompanyApplicationResponse. Every entry here must trace back to a real
# ActivityLog row already written by apply_to_job/update_status/
# withdraw_application — never a fabricated step, never derived from
# updated_at or a notification timestamp.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%timeline\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Timeline Verifier", "role": "verifier", "company_id": str(company.id)},
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
        json={"email": email, "password": "Password123", "full_name": "Timeline Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Timeline Student",
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
    verifier = _register_verifier(client, db_session, f"tl-co-{suffix}@test.credchain.dev", f"Timeline Co {suffix}")
    inst = _register_institution(client, db_session, f"tl-inst-{suffix}@test.credchain.dev", f"Timeline Uni {suffix}")
    student = _register_student(client, inst["institution_id"], f"tl-stu-{suffix}@test.credchain.dev", f"TL-STU-{suffix}")
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


def _history_statuses(app_json: dict) -> list[str]:
    return [entry["status"] for entry in app_json["history"]]


def test_new_application_history_has_exactly_one_applied_entry(client, db_session):
    ctx = _setup(client, db_session, "1a")
    app = _apply(client, ctx)
    assert _history_statuses(app) == ["applied"]


def test_history_grows_with_each_real_transition_and_stays_chronological(client, db_session):
    ctx = _setup(client, db_session, "1b")
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
    assert resp.status_code == 200, resp.text
    company_view = resp.json()

    assert _history_statuses(company_view) == ["applied", "under_review", "shortlisted"]
    occurred_at = [entry["occurred_at"] for entry in company_view["history"]]
    assert occurred_at == sorted(occurred_at)  # chronological, ascending


def test_applied_directly_to_rejected_does_not_fabricate_under_review(client, db_session):
    ctx = _setup(client, db_session, "1c")
    app = _apply(client, ctx)
    resp = client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "rejected", "reason": "Not a fit"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert _history_statuses(resp.json()) == ["applied", "rejected"]


def test_withdrawn_application_ends_history_at_withdrawn(client, db_session):
    ctx = _setup(client, db_session, "1d")
    app = _apply(client, ctx)
    resp = client.post(f"/api/students/me/applications/{app['id']}/withdraw", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200, resp.text
    history = _history_statuses(resp.json())
    assert history[-1] == "withdrawn"
    assert history == ["applied", "withdrawn"]


def test_student_sees_same_history_as_company_for_the_same_application(client, db_session):
    ctx = _setup(client, db_session, "1e")
    app = _apply(client, ctx)
    client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "under_review"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )

    student_view = next(
        a for a in client.get("/api/students/me/applications", headers=_auth_header(ctx["student"]["token"])).json()
        if a["id"] == app["id"]
    )
    company_view = next(
        a for a in client.get("/api/companies/me/applications", headers=_auth_header(ctx["verifier"]["token"])).json()
        if a["id"] == app["id"]
    )
    assert _history_statuses(student_view) == _history_statuses(company_view) == ["applied", "under_review"]


def test_existing_response_fields_remain_compatible_alongside_history(client, db_session):
    """Adding `history` must not remove or change any pre-existing field on either response shape."""
    ctx = _setup(client, db_session, "1f")
    app = _apply(client, ctx)

    student_view = next(
        a for a in client.get("/api/students/me/applications", headers=_auth_header(ctx["student"]["token"])).json()
        if a["id"] == app["id"]
    )
    for field in ("id", "job_id", "job_title", "company_id", "company_name", "status", "rejection_reason", "created_at"):
        assert field in student_view

    company_view = next(
        a for a in client.get("/api/companies/me/applications", headers=_auth_header(ctx["verifier"]["token"])).json()
        if a["id"] == app["id"]
    )
    for field in ("id", "job_id", "job_title", "student_id", "student_name", "student_identifier", "status", "rejection_reason", "created_at", "credential_request", "eligibility"):
        assert field in company_view


def test_student_cannot_access_another_students_application_history(client, db_session):
    ctx = _setup(client, db_session, "1g")
    app = _apply(client, ctx)
    other_student = _register_student(client, ctx["inst"]["institution_id"], "tl-other-1g@test.credchain.dev", "TL-OTHER-1G")

    listed = client.get("/api/students/me/applications", headers=_auth_header(other_student["token"])).json()
    assert all(a["id"] != app["id"] for a in listed)


def test_company_cannot_access_another_companys_application_history(client, db_session):
    ctx = _setup(client, db_session, "1h")
    app = _apply(client, ctx)
    other_verifier = _register_verifier(client, db_session, "tl-other-co-1h@test.credchain.dev", "Timeline Other Co 1h")

    listed = client.get("/api/companies/me/applications", headers=_auth_header(other_verifier["token"])).json()
    assert all(a["id"] != app["id"] for a in listed)

    # Direct decision attempt on someone else's application is also rejected, before any
    # history could ever be read for it.
    resp = client.post(
        f"/api/companies/me/applications/{app['id']}/status",
        json={"status": "under_review"},
        headers=_auth_header(other_verifier["token"]),
    )
    assert resp.status_code == 403
