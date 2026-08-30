# ---------------------------------------------------------------------------
# PS3 Phase G: view-only vs view+download share permissions. The backend
# must enforce this — a view-only recipient hitting the download endpoint
# gets a real 403, not just a hidden frontend button. All 7 scenarios
# specified in the brief.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%perm\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Perm Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Perm Student {identifier}",
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
        json={"email": email, "password": "Password123", "full_name": "Perm Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    return {"token": resp.json()["access_token"]}


def _issue(client, inst_token, student_id):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": "degree", "title": "Degree"},
        files=files,
        headers=_auth_header(inst_token),
    )
    return resp.json()["id"]


def _request_and_share(client, verifier_token, student_token, student_identifier, credential_id, permission=None, expires_in_days=7):
    req = client.post(
        "/api/credential-requests",
        json={"student_identifier": student_identifier, "purpose": "Permission test", "requested_credentials": ["Degree"]},
        headers=_auth_header(verifier_token),
    ).json()
    body = {"credential_ids": [credential_id], "expires_in_days": expires_in_days}
    if permission:
        body["permission"] = permission
    resp = client.post(f"/api/credential-requests/{req['id']}/approve", json=body, headers=_auth_header(student_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_view_only_recipient_can_view(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-1@test.credchain.dev", "Perm University 1")
    student = _register_student(client, inst["institution_id"], "perm-stu-1@test.credchain.dev", "PERM-STU-1")
    verifier = _register_verifier(client, db_session, "perm-verifier-1@test.credchain.dev", "Perm Co 1")
    credential_id = _issue(client, inst["token"], student["student_id"])
    _request_and_share(client, verifier["token"], student["token"], "PERM-STU-1", credential_id)

    resp = client.get(f"/api/verification/credentials/{credential_id}/view", headers=_auth_header(verifier["token"]))
    assert resp.status_code == 200


def test_view_only_recipient_cannot_download(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-2@test.credchain.dev", "Perm University 2")
    student = _register_student(client, inst["institution_id"], "perm-stu-2@test.credchain.dev", "PERM-STU-2")
    verifier = _register_verifier(client, db_session, "perm-verifier-2@test.credchain.dev", "Perm Co 2")
    credential_id = _issue(client, inst["token"], student["student_id"])
    _request_and_share(client, verifier["token"], student["token"], "PERM-STU-2", credential_id, permission="view_only")

    resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(verifier["token"]))
    assert resp.status_code == 403


def test_view_download_recipient_can_view_and_download(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-3@test.credchain.dev", "Perm University 3")
    student = _register_student(client, inst["institution_id"], "perm-stu-3@test.credchain.dev", "PERM-STU-3")
    verifier = _register_verifier(client, db_session, "perm-verifier-3@test.credchain.dev", "Perm Co 3")
    credential_id = _issue(client, inst["token"], student["student_id"])
    _request_and_share(client, verifier["token"], student["token"], "PERM-STU-3", credential_id, permission="view_download")

    view_resp = client.get(f"/api/verification/credentials/{credential_id}/view", headers=_auth_header(verifier["token"]))
    assert view_resp.status_code == 200
    download_resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(verifier["token"]))
    assert download_resp.status_code == 200


def test_unauthorized_recipient_denied_both(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-4@test.credchain.dev", "Perm University 4")
    student = _register_student(client, inst["institution_id"], "perm-stu-4@test.credchain.dev", "PERM-STU-4")
    _register_verifier(client, db_session, "perm-verifier-4a@test.credchain.dev", "Perm Co 4A")  # shared with
    other_verifier = _register_verifier(client, db_session, "perm-verifier-4b@test.credchain.dev", "Perm Co 4B")  # NOT shared with
    credential_id = _issue(client, inst["token"], student["student_id"])
    _request_and_share(client, _register_verifier(client, db_session, "perm-verifier-4c@test.credchain.dev", "Perm Co 4C")["token"], student["token"], "PERM-STU-4", credential_id, permission="view_download")

    view_resp = client.get(f"/api/verification/credentials/{credential_id}/view", headers=_auth_header(other_verifier["token"]))
    assert view_resp.status_code == 403
    download_resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(other_verifier["token"]))
    assert download_resp.status_code == 403


def test_revoked_share_denies_view_and_download(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-5@test.credchain.dev", "Perm University 5")
    student = _register_student(client, inst["institution_id"], "perm-stu-5@test.credchain.dev", "PERM-STU-5")
    verifier = _register_verifier(client, db_session, "perm-verifier-5@test.credchain.dev", "Perm Co 5")
    credential_id = _issue(client, inst["token"], student["student_id"])
    grant = _request_and_share(client, verifier["token"], student["token"], "PERM-STU-5", credential_id, permission="view_download")

    revoke_resp = client.post(f"/api/shares/{grant['share']['id']}/revoke", headers=_auth_header(student["token"]))
    assert revoke_resp.status_code == 200

    view_resp = client.get(f"/api/verification/credentials/{credential_id}/view", headers=_auth_header(verifier["token"]))
    assert view_resp.status_code == 403
    download_resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(verifier["token"]))
    assert download_resp.status_code == 403


def test_expired_share_denies_view_and_download(client, db_session):
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.models.share_grant import ShareGrant

    inst = _register_institution(client, db_session, "perm-inst-6@test.credchain.dev", "Perm University 6")
    student = _register_student(client, inst["institution_id"], "perm-stu-6@test.credchain.dev", "PERM-STU-6")
    verifier = _register_verifier(client, db_session, "perm-verifier-6@test.credchain.dev", "Perm Co 6")
    credential_id = _issue(client, inst["token"], student["student_id"])
    grant = _request_and_share(client, verifier["token"], student["token"], "PERM-STU-6", credential_id, permission="view_download")

    # Force the grant into the past — no client-facing way to create an
    # already-expired share, so this reaches directly into the DB.
    row = db_session.get(ShareGrant, uuid.UUID(grant["share"]["id"]))
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(row)
    db_session.commit()

    view_resp = client.get(f"/api/verification/credentials/{credential_id}/view", headers=_auth_header(verifier["token"]))
    assert view_resp.status_code == 403
    download_resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(verifier["token"]))
    assert download_resp.status_code == 403


def test_most_recent_grant_wins_when_multiple_active_grants_exist(client, db_session):
    """
    Found during live validation: nothing stops a company being granted the
    same credential twice (e.g. two separate approved requests). Before the
    fix, authorization_service.get_active_share_grant picked whichever row
    the DB happened to return first — meaning a student who re-shares with
    view_download could still be silently stuck on an earlier view_only
    grant. The most recent grant must always win.
    """
    inst = _register_institution(client, db_session, "perm-inst-8@test.credchain.dev", "Perm University 8")
    student = _register_student(client, inst["institution_id"], "perm-stu-8@test.credchain.dev", "PERM-STU-8")
    verifier = _register_verifier(client, db_session, "perm-verifier-8@test.credchain.dev", "Perm Co 8")
    credential_id = _issue(client, inst["token"], student["student_id"])

    # First grant: view_only.
    _request_and_share(client, verifier["token"], student["token"], "PERM-STU-8", credential_id, permission="view_only")
    # Second, independent request+grant for the SAME credential: view_download.
    _request_and_share(client, verifier["token"], student["token"], "PERM-STU-8", credential_id, permission="view_download")

    download_resp = client.get(f"/api/verification/credentials/{credential_id}/download", headers=_auth_header(verifier["token"]))
    assert download_resp.status_code == 200


def test_share_preview_and_grant_response_surface_permission(client, db_session):
    inst = _register_institution(client, db_session, "perm-inst-7@test.credchain.dev", "Perm University 7")
    student = _register_student(client, inst["institution_id"], "perm-stu-7@test.credchain.dev", "PERM-STU-7")
    verifier = _register_verifier(client, db_session, "perm-verifier-7@test.credchain.dev", "Perm Co 7")
    credential_id = _issue(client, inst["token"], student["student_id"])
    grant = _request_and_share(client, verifier["token"], student["token"], "PERM-STU-7", credential_id, permission="view_download")

    assert grant["share"]["permission"] == "view_download"

    preview_resp = client.get(f"/api/shares/verify/{grant['share_token']}")
    assert preview_resp.status_code == 200
    assert preview_resp.json()["permission"] == "view_download"

    my_shares = client.get("/api/students/me/shares", headers=_auth_header(student["token"])).json()
    mine = next(s for s in my_shares if s["id"] == grant["share"]["id"])
    assert mine["permission"] == "view_download"
