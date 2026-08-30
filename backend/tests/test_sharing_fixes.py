# ---------------------------------------------------------------------------
# Regression tests for two real, live-reproduced bugs:
#
# Bug 1 — a company entering a student's real student_identifier got
# "Student not found" whenever the case didn't match exactly (e.g. company
# typed "bf-stu-1" for a student stored as "BF-STU-1"). Fixed by making the
# student_identifier lookup in sharing_service.create_credential_request
# (and the analogous institutions.py lookup_my_student route) case-insensitive
# and whitespace-tolerant.
#
# Bug 2 — the student-initiated "Share Credential" button (no prior
# CredentialRequest) called a frontend-only mock createShare() that wrote to
# an in-memory array nothing else read, and ShareConfirmation.tsx rendered a
# fake https://credchain.app/verify/<random> QR/link disconnected from any
# real ShareGrant. Fixed by adding POST /api/students/me/shares — a real
# endpoint that reuses the exact same ShareGrant/ShareGrantCredential/token
# creation path as approve_request (credential_request_id simply null).
# ---------------------------------------------------------------------------

import uuid

from app.models.share_grant import ShareGrant

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%fix\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Fix Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "Fix Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
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
        json={"email": email, "password": "Password123", "full_name": "Fix Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue_credential(client, inst_token, student_id, credential_type="degree", title="B.Tech Degree"):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": credential_type, "title": title, "degree": title, "graduation_year": "2026"},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup(client, db_session, suffix):
    inst = _register_institution(client, db_session, f"fix-inst-{suffix}@test.credchain.dev", f"Fix University {suffix}")
    student = _register_student(client, inst["institution_id"], f"fix-stu-{suffix}@test.credchain.dev", f"FIX-STU-{suffix}")
    verifier = _register_verifier(client, db_session, f"fix-co-{suffix}@test.credchain.dev", f"Fix Corp {suffix}")
    credential = _issue_credential(client, inst["token"], student["student_id"])
    return {"inst": inst, "student": student, "verifier": verifier, "credential": credential}


# =====================================================================
# BUG 1 — case-insensitive / whitespace-tolerant student_identifier lookup
# =====================================================================


def test_company_can_request_student_with_exact_case_identifier(client, db_session):
    ctx = _setup(client, db_session, "1a")
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "FIX-STU-1a", "purpose": "Hiring", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["student_id"] == ctx["student"]["student_id"]


def test_company_can_request_student_with_lowercase_identifier(client, db_session):
    """The actual reproduced bug: a company typing the identifier in a different case must still find the student."""
    ctx = _setup(client, db_session, "1b")
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "fix-stu-1b", "purpose": "Hiring", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["student_id"] == ctx["student"]["student_id"]


def test_company_can_request_student_with_padded_whitespace_identifier(client, db_session):
    ctx = _setup(client, db_session, "1c")
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "  FIX-STU-1c  ", "purpose": "Hiring", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["student_id"] == ctx["student"]["student_id"]


def test_nonexistent_student_identifier_still_honestly_404s(client, db_session):
    ctx = _setup(client, db_session, "1d")
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "TOTALLY-BOGUS-ID", "purpose": "Hiring", "requested_credentials": ["Degree"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert resp.status_code == 404


def test_unauthorized_company_cannot_create_request(client, db_session):
    ctx = _setup(client, db_session, "1e")
    resp = client.post(
        "/api/credential-requests",
        json={"student_identifier": "FIX-STU-1e", "purpose": "Hiring", "requested_credentials": ["Degree"]},
    )
    assert resp.status_code == 401


def test_institution_student_lookup_is_also_case_insensitive(client, db_session):
    """Same root-cause fix applied to the institution's own manual-entry student lookup."""
    ctx = _setup(client, db_session, "1f")
    resp = client.get(
        "/api/institutions/me/students/lookup/fix-stu-1f",
        headers=_auth_header(ctx["inst"]["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["student_identifier"] == "FIX-STU-1f"


# =====================================================================
# BUG 2 — real student-initiated direct share (no CredentialRequest)
# =====================================================================


def test_student_can_create_direct_share_to_real_company(client, db_session):
    ctx = _setup(client, db_session, "2a")
    resp = client.post(
        "/api/students/me/shares",
        json={
            "company_id": ctx["verifier"]["company_id"],
            "credential_ids": [ctx["credential"]["id"]],
            "expires_in_days": 7,
            "permission": "view_only",
        },
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "share_token" in body
    assert body["share"]["company_name"] == "Fix Corp 2a"
    assert body["share"]["status"] == "active"
    assert len(body["share"]["credentials"]) == 1


def test_direct_share_grant_has_null_credential_request_id(client, db_session):
    ctx = _setup(client, db_session, "2b")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    share_id = resp.json()["share"]["id"]
    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(share_id)).first()
    assert grant.credential_request_id is None


def test_direct_share_appears_in_student_my_shares(client, db_session):
    ctx = _setup(client, db_session, "2c")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    share_id = resp.json()["share"]["id"]

    listed = client.get("/api/students/me/shares", headers=_auth_header(ctx["student"]["token"]))
    assert listed.status_code == 200
    assert share_id in [s["id"] for s in listed.json()]


def test_direct_share_appears_in_company_shares(client, db_session):
    """The exact consistency guarantee Bug 2 broke: student's share must show up on the company's side too."""
    ctx = _setup(client, db_session, "2d")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    share_id = resp.json()["share"]["id"]

    listed = client.get("/api/companies/me/shares", headers=_auth_header(ctx["verifier"]["token"]))
    assert listed.status_code == 200
    assert share_id in [s["id"] for s in listed.json()]


def test_direct_share_raw_token_not_stored(client, db_session):
    ctx = _setup(client, db_session, "2e")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    body = resp.json()
    raw_token = body["share_token"]
    grant = db_session.query(ShareGrant).filter(ShareGrant.id == uuid.UUID(body["share"]["id"])).first()
    assert grant.share_token_hash != raw_token
    assert raw_token not in grant.share_token_hash


def test_direct_share_token_resolves_at_real_share_verify_route(client, db_session):
    ctx = _setup(client, db_session, "2f")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    raw_token = resp.json()["share_token"]

    preview = client.get(f"/api/shares/verify/{raw_token}")
    assert preview.status_code == 200
    assert preview.json()["company_name"] == "Fix Corp 2f"


def test_direct_share_does_not_auto_verify_company_must_click_verify(client, db_session):
    ctx = _setup(client, db_session, "2g")
    client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    # No VerificationEvent exists until this explicit call — the share alone never implies "Verified".
    verify_resp = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["result"] == "VERIFIED"


def test_direct_share_view_only_blocks_download(client, db_session):
    ctx = _setup(client, db_session, "2h")
    client.post(
        "/api/students/me/shares",
        json={
            "company_id": ctx["verifier"]["company_id"],
            "credential_ids": [ctx["credential"]["id"]],
            "expires_in_days": 7,
            "permission": "view_only",
        },
        headers=_auth_header(ctx["student"]["token"]),
    )
    resp = client.get(f"/api/verification/credentials/{ctx['credential']['id']}/download", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 403


def test_direct_share_view_download_permits_download(client, db_session):
    ctx = _setup(client, db_session, "2i")
    client.post(
        "/api/students/me/shares",
        json={
            "company_id": ctx["verifier"]["company_id"],
            "credential_ids": [ctx["credential"]["id"]],
            "expires_in_days": 7,
            "permission": "view_download",
        },
        headers=_auth_header(ctx["student"]["token"]),
    )
    resp = client.get(f"/api/verification/credentials/{ctx['credential']['id']}/download", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200


def test_direct_share_revoke_denies_company_access(client, db_session):
    ctx = _setup(client, db_session, "2j")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    body = resp.json()
    share_id = body["share"]["id"]
    raw_token = body["share_token"]

    revoke_resp = client.post(f"/api/shares/{share_id}/revoke", headers=_auth_header(ctx["student"]["token"]))
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"

    preview_after_revoke = client.get(f"/api/shares/verify/{raw_token}")
    assert preview_after_revoke.status_code == 410

    verify_after_revoke = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert verify_after_revoke.json()["result"] == "UNAUTHORIZED"


def test_direct_share_to_nonexistent_company_is_404(client, db_session):
    ctx = _setup(client, db_session, "2k")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": str(uuid.uuid4()), "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 404


def test_direct_share_rejects_directory_only_company(client, db_session):
    """
    Regression test for the "012" incident: a directory-only Company row
    (user_id IS NULL, e.g. imported from Wikidata) can never have a logged-in
    verifier, so a share created against it could never be redeemed by
    anyone. create_direct_share must refuse it outright rather than silently
    creating a dead-end grant.
    """
    from app.models.company import Company

    ctx = _setup(client, db_session, "2m")
    directory_only = Company(name="Apple Inc.", source="wikidata", source_id="Q312")
    db_session.add(directory_only)
    db_session.commit()
    db_session.refresh(directory_only)

    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": str(directory_only.id), "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "directory listing" in resp.json()["detail"].lower()


def test_direct_share_to_similarly_named_registered_company_resolves_to_its_own_canonical_id(client, db_session):
    """
    Two rows can share a similar name — a directory-only 'Apple Inc.' and a
    separately registered 'Apple' account. The share must resolve to the
    REGISTERED company's own canonical company_id, and only that company's
    login can be authorized against it — never the directory-only lookalike.
    """
    from app.models.company import Company

    ctx = _setup(client, db_session, "2n")
    db_session.add(Company(name="Apple Inc.", source="wikidata", source_id="Q312"))
    db_session.commit()

    other_verifier = _register_verifier(client, db_session, "fix-apple-2n@test.credchain.dev", "Apple")

    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": other_verifier["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["share"]["company_id"] == other_verifier["company_id"]
    assert body["share"]["company_name"] == "Apple"

    # The unrelated pre-existing verifier from _setup (a different registered
    # company) must still be UNAUTHORIZED for this credential — the grant is
    # scoped to Apple's company_id only, exactly as before this change.
    verify_wrong_company = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert verify_wrong_company.json()["result"] == "UNAUTHORIZED"

    verify_apple = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(other_verifier["token"]),
    )
    assert verify_apple.json()["result"] == "VERIFIED"


def test_direct_share_cannot_include_another_students_credential(client, db_session):
    ctx = _setup(client, db_session, "2l")
    other_student = _register_student(client, ctx["inst"]["institution_id"], "fix-other-2l@test.credchain.dev", "FIX-OTHER-2l")
    other_credential = _issue_credential(client, ctx["inst"]["token"], other_student["student_id"])

    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [other_credential["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 422


def test_direct_share_requires_authentication(client, db_session):
    ctx = _setup(client, db_session, "2m")
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
    )
    assert resp.status_code == 401


def test_company_cannot_see_another_companys_direct_share(client, db_session):
    """Cross-company isolation: a direct share to Company A must never appear in Company B's shares list."""
    ctx = _setup(client, db_session, "2n")
    other_company = _register_verifier(client, db_session, "fix-co-other-2n@test.credchain.dev", "Fix Corp Other 2n")

    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    share_id = resp.json()["share"]["id"]

    other_listed = client.get("/api/companies/me/shares", headers=_auth_header(other_company["token"]))
    assert share_id not in [s["id"] for s in other_listed.json()]


def test_other_student_cannot_revoke_this_students_direct_share(client, db_session):
    ctx = _setup(client, db_session, "2o")
    other_student = _register_student(client, ctx["inst"]["institution_id"], "fix-other-2o@test.credchain.dev", "FIX-OTHER-2o")

    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [ctx["credential"]["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    share_id = resp.json()["share"]["id"]

    resp = client.post(f"/api/shares/{share_id}/revoke", headers=_auth_header(other_student["token"]))
    assert resp.status_code == 403
