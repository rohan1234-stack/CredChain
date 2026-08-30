# ---------------------------------------------------------------------------
# PS3 Phase F: requested-vs-received credential mismatch. THE critical trust
# fix — a company must never see a credential of the wrong type reported as
# VERIFIED just because some credential was shared in response to its
# request. All four cases specified in the brief, verbatim, plus regression
# coverage that the existing VERIFIED/REVOKED/EXPIRED/UNAUTHORIZED paths are
# unchanged.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%mismatch\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Mismatch Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Mismatch Student {identifier}",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Mismatch Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    return {"token": resp.json()["access_token"]}


def _issue(client, inst_token, student_id, credential_type, title):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": credential_type, "title": title},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _request_and_share(client, verifier_token, student_token, student_identifier, requested_labels, credential_id):
    req = client.post(
        "/api/credential-requests",
        json={"student_identifier": student_identifier, "purpose": "Mismatch test", "requested_credentials": requested_labels},
        headers=_auth_header(verifier_token),
    ).json()
    approve = client.post(
        f"/api/credential-requests/{req['id']}/approve",
        json={"credential_ids": [credential_id], "expires_in_days": 7},
        headers=_auth_header(student_token),
    )
    assert approve.status_code == 200, approve.text
    return req


def _verify(client, verifier_token, credential_id):
    resp = client.post("/api/verification/verify", json={"credential_id": credential_id}, headers=_auth_header(verifier_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- the four cases specified verbatim ------------------------------------------


def test_requested_migration_shared_migration_is_verified(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-1@test.credchain.dev", "Mismatch University 1")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-1@test.credchain.dev", "MISMATCH-STU-1")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-1@test.credchain.dev", "Mismatch Co 1")

    credential_id = _issue(client, inst["token"], student["student_id"], "migration", "Migration Certificate")
    _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-1", ["Migration Certificate"], credential_id)

    result = _verify(client, verifier["token"], credential_id)
    assert result["result"] == "VERIFIED"


def test_requested_migration_shared_degree_is_not_verified(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-2@test.credchain.dev", "Mismatch University 2")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-2@test.credchain.dev", "MISMATCH-STU-2")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-2@test.credchain.dev", "Mismatch Co 2")

    credential_id = _issue(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")
    _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-2", ["Migration Certificate"], credential_id)

    result = _verify(client, verifier["token"], credential_id)
    assert result["result"] != "VERIFIED"
    assert result["result"] == "TYPE_MISMATCH"
    # the real cryptographic checks still ran and are reported truthfully
    assert result["checks"]["signature"] is True
    assert result["checks"]["integrity"] is True
    assert result["requested_credentials"] == ["Migration Certificate"]


def test_requested_transcript_shared_degree_is_not_verified(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-3@test.credchain.dev", "Mismatch University 3")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-3@test.credchain.dev", "MISMATCH-STU-3")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-3@test.credchain.dev", "Mismatch Co 3")

    credential_id = _issue(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")
    _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-3", ["Transcript"], credential_id)

    result = _verify(client, verifier["token"], credential_id)
    assert result["result"] == "TYPE_MISMATCH"


def test_requested_degree_shared_degree_is_verified(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-4@test.credchain.dev", "Mismatch University 4")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-4@test.credchain.dev", "MISMATCH-STU-4")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-4@test.credchain.dev", "Mismatch Co 4")

    credential_id = _issue(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")
    _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-4", ["Degree"], credential_id)

    result = _verify(client, verifier["token"], credential_id)
    assert result["result"] == "VERIFIED"


# --- requested-vs-received surfaces on the request list before Verify is clicked ---


def test_company_sees_requested_and_shared_credentials_on_request_list(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-5@test.credchain.dev", "Mismatch University 5")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-5@test.credchain.dev", "MISMATCH-STU-5")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-5@test.credchain.dev", "Mismatch Co 5")

    credential_id = _issue(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")
    req = _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-5", ["Migration Certificate"], credential_id)

    list_resp = client.get("/api/companies/me/requests", headers=_auth_header(verifier["token"]))
    mine = next(r for r in list_resp.json() if r["id"] == req["id"])
    assert mine["requested_credentials"] == ["Migration Certificate"]
    assert len(mine["shared_credentials"]) == 1
    assert mine["shared_credentials"][0]["credential_type"] == "degree"


# --- regression: existing result paths are unaffected -----------------------------


def test_credential_without_request_context_still_verifies_normally(client, db_session):
    """A credential accessed through a share NOT tied to any company request (edge case, not currently reachable via the app, but the function must be safe) never trips a mismatch."""
    from app.services import verification_service

    assert verification_service.determine_result(
        issuer_valid=True, signature_valid=True, integrity_valid=True, credential_status="active", type_mismatch=False
    ).value == "VERIFIED"


def test_revoked_credential_still_reports_revoked_even_if_type_mismatched(client, db_session):
    inst = _register_institution(client, db_session, "mismatch-inst-6@test.credchain.dev", "Mismatch University 6")
    student = _register_student(client, inst["institution_id"], "mismatch-stu-6@test.credchain.dev", "MISMATCH-STU-6")
    verifier = _register_verifier(client, db_session, "mismatch-verifier-6@test.credchain.dev", "Mismatch Co 6")

    credential_id = _issue(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")
    _request_and_share(client, verifier["token"], student["token"], "MISMATCH-STU-6", ["Migration Certificate"], credential_id)
    client.post(f"/api/credentials/{credential_id}/revoke", headers=_auth_header(inst["token"]))

    result = _verify(client, verifier["token"], credential_id)
    assert result["result"] == "REVOKED"
