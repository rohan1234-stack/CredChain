# ---------------------------------------------------------------------------
# Phase 8B tests: real activity feeds, read-only over the existing
# ActivityLog table. Nothing here writes to credential issuance,
# verification, sharing, revocation, or AI — those are only exercised as
# fixtures to produce real ActivityLog rows to read back.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timedelta, timezone

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email="activity-inst@test.credchain.dev", name="Activity University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="activity-student@test.credchain.dev", identifier="STU-ACT-001"):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="activity-verifier@test.credchain.dev", name="Activity Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue(client, institution_token, student_id, **overrides) -> dict:
    data = {
        "student_id": student_id,
        "credential_type": "transcript",
        "title": "Final Transcript",
        "degree": "B.Tech Computer Science",
        "graduation_year": "2026",
        "cgpa": "8.7",
    }
    data.update(overrides)
    files = {"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup(client, db_session):
    """Institution issues a credential to a student — produces one CREDENTIAL_ISSUED row."""
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue(client, inst["token"], student["student_id"])
    return {"inst": inst, "student": student, "credential": credential}


def _full_flow(client, db_session):
    """
    Issues a credential, then runs it through the full request -> approve ->
    verify -> revoke-share lifecycle, so every action type in the product
    spec produces a real row to read back.
    """
    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session)

    req_resp = client.post(
        "/api/credential-requests",
        json={
            "student_id": ctx["student"]["student_id"],
            "purpose": "Job application",
            "requested_credentials": ["Final Transcript"],
        },
        headers=_auth_header(verifier["token"]),
    )
    assert req_resp.status_code == 201, req_resp.text
    request_id = req_resp.json()["id"]

    approve_resp = client.post(
        f"/api/credential-requests/{request_id}/approve",
        json={"credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert approve_resp.status_code == 200, approve_resp.text

    verify_resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(verifier["token"]),
    )
    assert verify_resp.status_code == 200, verify_resp.text

    return {**ctx, "verifier": verifier, "request_id": request_id}


# --- 1/2/3: each role can retrieve its own activity ----------------------------------------


def test_student_can_retrieve_own_activity(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(row["action"] == "CREDENTIAL_ISSUED" for row in body)


def test_institution_can_retrieve_own_activity(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(row["action"] == "CREDENTIAL_ISSUED" for row in body)


def test_company_can_retrieve_own_activity(client, db_session):
    ctx = _full_flow(client, db_session)
    resp = client.get("/api/companies/me/activity", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(row["action"] == "CREDENTIAL_REQUEST_CREATED" for row in body)
    assert any(row["action"] == "CREDENTIAL_VERIFIED" for row in body)


# --- 4/5: student cannot access institution/company activity endpoints ---------------------


def test_student_cannot_access_institution_activity(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 403


def test_student_cannot_access_company_activity(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/companies/me/activity", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 403


# --- 6: institution cannot access student activity ------------------------------------------


def test_institution_cannot_access_student_activity(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/students/me/activity", headers=_auth_header(ctx["inst"]["token"]))
    assert resp.status_code == 403


# --- 7: company cannot access student activity ----------------------------------------------


def test_company_cannot_access_student_activity(client, db_session):
    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session)
    resp = client.get("/api/students/me/activity", headers=_auth_header(verifier["token"]))
    assert resp.status_code == 403


# --- 8: unauthenticated activity request is rejected -----------------------------------------


def test_unauthenticated_activity_rejected(client, db_session):
    assert client.get("/api/students/me/activity").status_code == 401
    assert client.get("/api/institutions/me/activity").status_code == 401
    assert client.get("/api/companies/me/activity").status_code == 401


# --- cross-tenant isolation: Student A cannot see Student B's activity, etc. ----------------


def test_student_a_cannot_see_student_b_activity(client, db_session):
    ctx_a = _setup(client, db_session)
    inst_b = _register_institution(client, db_session, email="activity-inst-b@test.credchain.dev", name="Other University")
    student_b = _register_student(
        client, db_session, inst_b["institution_id"], email="activity-student-b@test.credchain.dev", identifier="STU-ACT-002"
    )
    _issue(client, inst_b["token"], student_b["student_id"], title="Other Degree")

    resp = client.get("/api/students/me/activity", headers=_auth_header(ctx_a["student"]["token"]))
    assert resp.status_code == 200
    for row in resp.json():
        assert row["entity_id"] != student_b["student_id"]
    # Student A's feed must not contain the credential issued to Student B.
    b_activity = client.get("/api/students/me/activity", headers=_auth_header(student_b["token"])).json()
    a_activity = resp.json()
    a_ids = {row["id"] for row in a_activity}
    b_ids = {row["id"] for row in b_activity}
    assert a_ids.isdisjoint(b_ids)


def test_institution_a_cannot_see_institution_b_activity(client, db_session):
    ctx_a = _setup(client, db_session)
    inst_b = _register_institution(client, db_session, email="activity-inst-c@test.credchain.dev", name="Third University")
    student_b = _register_student(
        client, db_session, inst_b["institution_id"], email="activity-student-c@test.credchain.dev", identifier="STU-ACT-003"
    )
    _issue(client, inst_b["token"], student_b["student_id"], title="Third Degree")

    a_activity = client.get("/api/institutions/me/activity", headers=_auth_header(ctx_a["inst"]["token"])).json()
    b_activity = client.get("/api/institutions/me/activity", headers=_auth_header(inst_b["token"])).json()
    a_ids = {row["id"] for row in a_activity}
    b_ids = {row["id"] for row in b_activity}
    assert a_ids.isdisjoint(b_ids)


def test_company_a_cannot_see_company_b_activity(client, db_session):
    ctx = _full_flow(client, db_session)
    verifier_b = _register_verifier(client, db_session, email="activity-verifier-b@test.credchain.dev", name="Other Company")

    a_activity = client.get("/api/companies/me/activity", headers=_auth_header(ctx["verifier"]["token"])).json()
    b_activity = client.get("/api/companies/me/activity", headers=_auth_header(verifier_b["token"])).json()
    a_ids = {row["id"] for row in a_activity}
    b_ids = {row["id"] for row in b_activity}
    assert a_ids.isdisjoint(b_ids)
    assert len(b_activity) == 0


# --- 9: activities are newest first ----------------------------------------------------------


def test_activity_newest_first(client, db_session):
    ctx = _setup(client, db_session)
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title="Second Credential")

    resp = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"]))
    body = resp.json()
    timestamps = [datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) for row in body]
    assert timestamps == sorted(timestamps, reverse=True)


# --- 10: activity limit works -----------------------------------------------------------------


def test_activity_limit(client, db_session):
    ctx = _setup(client, db_session)
    for i in range(5):
        _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title=f"Extra Credential {i}")

    resp = client.get("/api/institutions/me/activity?limit=3", headers=_auth_header(ctx["inst"]["token"]))
    assert resp.status_code == 200
    assert len(resp.json()) == 3


# --- 11: real ActivityLog records appear in the API -------------------------------------------


def test_real_activity_log_records_appear(client, db_session):
    from app.models.activity_log import ActivityLog

    ctx = _setup(client, db_session)
    db_row = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.action == "CREDENTIAL_ISSUED", ActivityLog.entity_id == uuid.UUID(ctx["credential"]["id"]))
        .first()
    )
    assert db_row is not None

    resp = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"]))
    body = resp.json()
    assert any(row["id"] == str(db_row.id) for row in body)
    matching = next(row for row in body if row["id"] == str(db_row.id))
    assert matching["message"] == f"Credential issued to Test Student"


# --- 12: sensitive internal fields are not exposed ---------------------------------------------


def test_sensitive_fields_not_exposed(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"]))
    body = resp.json()
    assert len(body) > 0
    for row in body:
        keys = set(row.keys())
        assert "actor_user_id" not in keys
        assert "metadata" not in keys
        assert "metadata_" not in keys
        assert "password" not in keys
        assert "password_hash" not in keys
        assert "storage_path" not in keys
        assert "share_token_hash" not in keys
        assert "signature" not in keys
        assert keys == {"id", "action", "message", "entity_type", "entity_id", "created_at"}


# --- 13: activity survives "page refresh" (fresh request, same server-side state) --------------


def test_activity_survives_refresh(client, db_session):
    ctx = _setup(client, db_session)
    first = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    second = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    assert first == second
    assert len(first) > 0
