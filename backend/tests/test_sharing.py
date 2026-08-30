# ---------------------------------------------------------------------------
# Phase 6 tests: credential requests, student-controlled selective sharing,
# secure tokens, expiry, revocation, and the full integration into Phase 5
# verification. No manual ShareGrant DB insertion here (unlike Phase 5's
# tests) — every share in this file is created through the real approve
# workflow, exactly as a real student would trigger it.
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timedelta, timezone

from app.models.credential_request import CredentialRequest
from app.models.share_grant import ShareGrant

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


def _register_institution(client, db_session, email="inst@test.credchain.dev", name="Test University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="student@test.credchain.dev", identifier="STU-001"):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="verifier@test.credchain.dev", name="Test Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue_credential(client, institution_token, student_id, **overrides) -> dict:
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


def _issue_credential_no_cgpa(client, institution_token, student_id) -> dict:
    data = {
        "student_id": student_id,
        "credential_type": "degree",
        "title": "B.Tech Degree",
        "degree": "B.Tech Computer Science",
        "graduation_year": "2026",
    }
    files = {"document": ("degree.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _full_setup(client, db_session):
    """Institution + student with TWO credentials (degree, transcript) + verifier, no request/share yet."""
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    degree = _issue_credential_no_cgpa(client, inst["token"], student["student_id"])
    transcript = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session)
    return {"inst": inst, "student": student, "degree": degree, "transcript": transcript, "verifier": verifier}


def _create_request(client, verifier_token, student_id, requested=("Degree", "Final Transcript"), purpose="Software Engineer Application"):
    resp = client.post(
        "/api/credential-requests",
        json={"student_id": student_id, "purpose": purpose, "requested_credentials": list(requested)},
        headers=_auth_header(verifier_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve(client, student_token, request_id, credential_ids, expires_in_days=7):
    return client.post(
        f"/api/credential-requests/{request_id}/approve",
        json={"credential_ids": credential_ids, "expires_in_days": expires_in_days},
        headers=_auth_header(student_token),
    )


# =====================================================================
# REQUESTS
# =====================================================================


def test_company_can_create_request(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    assert req["status"] == "pending"
    assert req["purpose"] == "Software Engineer Application"
    assert req["requested_credentials"] == ["Degree", "Final Transcript"]


def test_company_can_create_request_by_student_identifier(client, db_session):
    """Final-polish fix: a company only ever knows a candidate's human-readable student_identifier, never their internal UUID."""
    ctx = _full_setup(client, db_session)
    resp = client.post(
        "/api/credential-requests",
        json={
            "student_identifier": "STU-001",
            "purpose": "Software Engineer Application",
            "requested_credentials": ["Degree"],
        },
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["student_id"] == ctx["student"]["student_id"]


def test_create_request_with_unknown_student_identifier_is_404(client, db_session):
    ctx = _full_setup(client, db_session)
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "NO-SUCH-STUDENT", "purpose": "Test", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 404


def test_create_request_with_neither_student_reference_is_rejected(client, db_session):
    ctx = _full_setup(client, db_session)
    resp = client.post(
        "/api/credential-requests",
        json={"purpose": "Test", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 422


def test_student_sees_request(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    resp = client.get("/api/students/me/requests", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert req["id"] in ids


def test_other_student_cannot_see_request(client, db_session):
    ctx = _full_setup(client, db_session)
    _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    other_student = _register_student(
        client, db_session, ctx["inst"]["institution_id"], email="other@test.credchain.dev", identifier="STU-OTHER"
    )
    resp = client.get("/api/students/me/requests", headers=_auth_header(other_student["token"]))
    assert resp.status_code == 200
    assert resp.json() == []


def test_student_can_approve_request(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "share_token" in body
    assert body["share"]["status"] == "active"
    assert len(body["share"]["credentials"]) == 1


def test_student_can_decline_request(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    resp = client.post(f"/api/credential-requests/{req['id']}/decline", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"


def test_company_cannot_approve_request(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    resp = _approve(client, ctx["verifier"]["token"], req["id"], [ctx["degree"]["id"]])
    assert resp.status_code == 403


def test_already_processed_request_cannot_be_approved_again(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["transcript"]["id"]])
    assert resp.status_code == 409


# =====================================================================
# SELECTIVE SHARING / PRIVACY (the most important guarantee)
# =====================================================================


def test_student_selects_only_degree(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])
    body = resp.json()
    assert len(body["share"]["credentials"]) == 1
    assert body["share"]["credentials"][0]["title"] == "B.Tech Degree"


def test_share_grant_contains_only_selected_credential(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])
    share_id = resp.json()["share"]["id"]

    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share_id)).first()
    shared_credential_ids = {str(link.credential_id) for link in grant.credential_links}
    assert shared_credential_ids == {ctx["degree"]["id"]}
    assert ctx["transcript"]["id"] not in shared_credential_ids


def test_unselected_transcript_is_not_verifiable_by_company(client, db_session):
    """The critical privacy test: company only gets what was selected — verification of the unselected credential must be UNAUTHORIZED."""
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["transcript"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["result"] == "UNAUTHORIZED"


def test_student_cannot_share_another_students_credential(client, db_session):
    ctx = _full_setup(client, db_session)
    other_student = _register_student(
        client, db_session, ctx["inst"]["institution_id"], email="other2@test.credchain.dev", identifier="STU-OTHER2"
    )
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])

    # ctx["student"] tries to approve using a credential that belongs to other_student
    other_credential = _issue_credential_no_cgpa(client, ctx["inst"]["token"], other_student["student_id"])
    resp = _approve(client, ctx["student"]["token"], req["id"], [other_credential["id"]])
    assert resp.status_code == 422


# =====================================================================
# TOKEN
# =====================================================================


def test_share_token_is_unpredictable(client, db_session):
    ctx = _full_setup(client, db_session)
    req1 = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share1 = _approve(client, ctx["student"]["token"], req1["id"], [ctx["degree"]["id"]]).json()

    req2 = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share2 = _approve(client, ctx["student"]["token"], req2["id"], [ctx["degree"]["id"]]).json()

    token1, token2 = share1["share_token"], share2["share_token"]
    assert token1 != token2
    assert len(token1) >= 32
    # not derived from any obvious id
    assert ctx["student"]["student_id"] not in token1
    assert ctx["degree"]["id"] not in token1


def test_raw_token_is_not_stored_in_db(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()
    raw_token = share["share_token"]

    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share["share"]["id"])).first()
    assert grant.share_token_hash != raw_token
    assert raw_token not in grant.share_token_hash


def test_valid_token_grants_access(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    resp = client.get(f"/api/shares/verify/{share['share_token']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company_name"] == "Test Company"
    assert len(body["credentials"]) == 1
    assert body["credentials"][0]["title"] == "B.Tech Degree"


def test_invalid_token_denied(client, db_session):
    resp = client.get("/api/shares/verify/not-a-real-token-at-all")
    assert resp.status_code == 401


# =====================================================================
# EXPIRY
# =====================================================================


def test_active_share_works(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]], expires_in_days=30).json()

    resp = client.get(f"/api/shares/verify/{share['share_token']}")
    assert resp.status_code == 200


def test_expired_share_denied(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share["share"]["id"])).first()
    grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    resp = client.get(f"/api/shares/verify/{share['share_token']}")
    assert resp.status_code == 410


def test_expired_share_cannot_be_verified(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share["share"]["id"])).first()
    grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    body = resp.json()
    assert body["result"] == "UNAUTHORIZED"  # authorization_service excludes expired grants from access entirely


# =====================================================================
# REVOCATION
# =====================================================================


def test_student_can_revoke_own_share(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    resp = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


def test_other_student_cannot_revoke_share(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    other_student = _register_student(
        client, db_session, ctx["inst"]["institution_id"], email="other3@test.credchain.dev", identifier="STU-OTHER3"
    )
    resp = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(other_student["token"]))
    assert resp.status_code == 403


def test_revoked_share_denied_at_token_endpoint(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()
    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))

    resp = client.get(f"/api/shares/verify/{share['share_token']}")
    assert resp.status_code == 410


def test_revoked_share_cannot_be_verified(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()
    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.json()["result"] == "UNAUTHORIZED"


# =====================================================================
# AUTHORIZATION
# =====================================================================


def test_company_a_cannot_use_company_bs_share(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    company_b = _register_verifier(client, db_session, email="companyb@test.credchain.dev", name="Company B")
    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(company_b["token"]),
    )
    assert resp.json()["result"] == "UNAUTHORIZED"


def test_student_cannot_access_another_students_share(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    other_student = _register_student(
        client, db_session, ctx["inst"]["institution_id"], email="other4@test.credchain.dev", identifier="STU-OTHER4"
    )
    resp = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(other_student["token"]))
    assert resp.status_code == 403


def test_unauthenticated_cannot_revoke_or_list_shares(client, db_session):
    assert client.post(f"/api/shares/{uuid.uuid4()}/revoke").status_code == 401
    assert client.get("/api/students/me/shares").status_code == 401
    assert client.get("/api/companies/me/shares").status_code == 401


# =====================================================================
# INTEGRATION
# =====================================================================


def test_request_approval_creates_share_grant(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])
    share_id = resp.json()["share"]["id"]

    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share_id)).first()
    assert grant is not None
    request = db_session.query(CredentialRequest).filter(CredentialRequest.id == uuid.UUID(req["id"])).first()
    assert request.status.value == "approved"


def test_share_grant_enables_phase5_verification(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.json()["result"] == "VERIFIED"


def test_verified_credential_through_real_share(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["checks"] == {"issuer": True, "signature": True, "integrity": True, "status": True, "access": True}


def test_tampered_credential_still_fails_through_real_share(client, db_session):
    from app.models.credential import Credential

    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["degree"]["id"])).first()
    credential.title = "Forged Title"
    db_session.commit()

    resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    body = resp.json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False
    assert body["checks"]["access"] is True  # access itself is still authorized — the credential is what's forged


def test_activity_events_created_through_full_flow(client, db_session):
    from app.models.activity_log import ActivityLog

    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])

    actions = {log.action for log in db_session.query(ActivityLog).all()}
    assert "CREDENTIAL_REQUEST_CREATED" in actions
    assert "CREDENTIAL_REQUEST_APPROVED" in actions
    assert "CREDENTIAL_SHARED" in actions


# =====================================================================
# CRITICAL END-TO-END TEST (section 26)
# =====================================================================


def test_critical_end_to_end_flow(client, db_session):
    ctx = _full_setup(client, db_session)

    # Company creates request -> student receives -> selects Degree -> approves
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    approve_resp = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]])
    assert approve_resp.status_code == 200
    share = approve_resp.json()
    raw_token = share["share_token"]

    # Company uses the token to preview
    preview = client.get(f"/api/shares/verify/{raw_token}")
    assert preview.status_code == 200

    # Company runs real Phase 5 verification
    verify_resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert verify_resp.json()["result"] == "VERIFIED"

    # Student revokes
    revoke_resp = client.post(
        f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"])
    )
    assert revoke_resp.status_code == 200

    # Company tries the same token again -> denied
    preview_after_revoke = client.get(f"/api/shares/verify/{raw_token}")
    assert preview_after_revoke.status_code == 410

    verify_after_revoke = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["degree"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert verify_after_revoke.json()["result"] == "UNAUTHORIZED"

    # A fresh share with an already-past expiry (simulated via direct mutation, since
    # ALLOWED_EXPIRY_DAYS only offers 1/7/30 — this mirrors "time has passed" for the test)
    req2 = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share2 = _approve(client, ctx["student"]["token"], req2["id"], [ctx["degree"]["id"]]).json()
    grant2 = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share2["share"]["id"])).first()
    grant2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    expired_preview = client.get(f"/api/shares/verify/{share2['share_token']}")
    assert expired_preview.status_code == 410


# =====================================================================
# CRITICAL PRIVACY TEST (section 27)
# =====================================================================


def test_critical_privacy_selective_disclosure(client, db_session):
    inst = _register_institution(client, db_session, email="privacy-inst@test.credchain.dev", name="Privacy University")
    student = _register_student(
        client, db_session, inst["institution_id"], email="privacy-student@test.credchain.dev", identifier="STU-PRIV"
    )
    degree = _issue_credential_no_cgpa(client, inst["token"], student["student_id"])
    transcript = _issue_credential(client, inst["token"], student["student_id"])
    migration = _issue_credential_field_free(client, inst["token"], student["student_id"], "migration", "Migration Certificate")
    internship = _issue_credential_field_free(client, inst["token"], student["student_id"], "internship", "Internship Certificate")

    verifier = _register_verifier(client, db_session, email="privacy-verifier@test.credchain.dev", name="Privacy Corp")

    req = _create_request(
        client, verifier["token"], student["student_id"], requested=("Degree", "Final Transcript"), purpose="Hiring"
    )
    # Student selects ONLY Degree, despite Transcript also being requested.
    approve_resp = _approve(client, student["token"], req["id"], [degree["id"]])
    assert approve_resp.status_code == 200

    # Company can verify Degree.
    degree_check = client.post(
        "/api/verification/verify", json={"credential_id": degree["id"]}, headers=_auth_header(verifier["token"])
    )
    assert degree_check.json()["result"] == "VERIFIED"

    # Company must NOT be able to verify (i.e. must get UNAUTHORIZED for) any of the other three.
    for cred in (transcript, migration, internship):
        resp = client.post(
            "/api/verification/verify", json={"credential_id": cred["id"]}, headers=_auth_header(verifier["token"])
        )
        assert resp.json()["result"] == "UNAUTHORIZED", f"{cred['title']} should not be accessible"


def _issue_credential_field_free(client, institution_token, student_id, credential_type, title):
    data = {"student_id": student_id, "credential_type": credential_type, "title": title}
    files = {"document": (f"{credential_type}.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =====================================================================
# SHARE REVOKE NOTIFICATIONS
# ---------------------------------------------------------------------
# revoke_share() already wrote a SHARE_REVOKED ActivityLog row before this
# fix; it now also creates exactly one Notification for the affected
# registered company, in the same transaction, reusing the notification
# infrastructure already used by CREDENTIAL_SHARED and friends.
# =====================================================================


def _unread_count(client, token):
    resp = client.get("/api/notifications/me/unread-count", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _notifications(client, token):
    resp = client.get("/api/notifications/me", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_revoking_share_notifies_company_a_exactly_once(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    before = _unread_count(client, ctx["verifier"]["token"])
    resp = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200

    after = _unread_count(client, ctx["verifier"]["token"])
    assert after == before + 1

    revoke_notifications = [n for n in _notifications(client, ctx["verifier"]["token"]) if n["title"] == "Credential Share Revoked"]
    assert len(revoke_notifications) == 1
    notif = revoke_notifications[0]
    assert notif["link_entity_type"] == "share_grant"
    assert notif["link_entity_id"] == share["share"]["id"]


def test_revoking_share_does_not_notify_an_unrelated_company(client, db_session):
    ctx = _full_setup(client, db_session)
    other_verifier = _register_verifier(client, db_session, email="unrelated-verifier@test.credchain.dev", name="Unrelated Co")

    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    before = _unread_count(client, other_verifier["token"])
    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))
    after = _unread_count(client, other_verifier["token"])

    assert after == before == 0
    assert _notifications(client, other_verifier["token"]) == []


def test_revoke_notification_belongs_to_company_as_own_user(client, db_session):
    from app.models.notification import Notification

    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()
    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))

    from app.models.user import User

    company_user_id = db_session.query(User).filter(User.email == "verifier@test.credchain.dev").first().id
    row = db_session.query(Notification).filter(Notification.title == "Credential Share Revoked").first()
    assert row is not None
    assert row.user_id == company_user_id


def test_directory_only_company_share_revoke_creates_no_notification(client, db_session):
    import hashlib

    from app.models.company import Company
    from app.models.notification import Notification
    from app.models.share_grant import ShareGrant, ShareGrantCredential

    ctx = _full_setup(client, db_session)

    directory_company = Company(name="Directory Only Co")
    db_session.add(directory_company)
    db_session.commit()
    db_session.refresh(directory_company)
    assert directory_company.user_id is None

    grant = ShareGrant(
        student_id=uuid.UUID(ctx["student"]["student_id"]),
        company_id=directory_company.id,
        share_token_hash=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(grant)
    db_session.commit()
    db_session.refresh(grant)
    db_session.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=uuid.UUID(ctx["degree"]["id"])))
    db_session.commit()

    resp = client.post(f"/api/shares/{grant.id}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200

    assert db_session.query(Notification).filter(Notification.link_entity_id == grant.id).count() == 0


def test_revoke_still_makes_access_unauthorized_and_keeps_activity_log(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))

    verify_resp = client.post(
        "/api/verification/verify", json={"credential_id": ctx["degree"]["id"]}, headers=_auth_header(ctx["verifier"]["token"])
    )
    assert verify_resp.json()["result"] == "UNAUTHORIZED"

    activity = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    assert any(row["action"] == "SHARE_REVOKED" for row in activity)


def test_revoke_notification_contains_no_token_or_hash_material(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()
    raw_token = share["share_token"]

    client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))

    notif = next(n for n in _notifications(client, ctx["verifier"]["token"]) if n["title"] == "Credential Share Revoked")
    assert set(notif.keys()) == {"id", "title", "message", "link_entity_type", "link_entity_id", "is_read", "read_at", "created_at"}
    assert raw_token not in notif["message"]
    assert raw_token not in notif["title"]


def test_duplicate_revoke_attempt_does_not_create_a_second_notification(client, db_session):
    ctx = _full_setup(client, db_session)
    req = _create_request(client, ctx["verifier"]["token"], ctx["student"]["student_id"])
    share = _approve(client, ctx["student"]["token"], req["id"], [ctx["degree"]["id"]]).json()

    first = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert first.status_code == 200
    second = client.post(f"/api/shares/{share['share']['id']}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert second.status_code == 409

    revoke_notifications = [n for n in _notifications(client, ctx["verifier"]["token"]) if n["title"] == "Credential Share Revoked"]
    assert len(revoke_notifications) == 1
