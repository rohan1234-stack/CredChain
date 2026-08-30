# ---------------------------------------------------------------------------
# Regression tests for the "View Degree does nothing" bug.
#
# Root cause: GET /api/verification/credentials/{id}/view and .../download
# already existed and were already correct (auth, ownership, permission
# enforcement, real file streaming) — the bug was entirely frontend-side:
# ResultCard.tsx's "View {title}" button had no onClick handler at all, and
# there was no Download button on the verifier's own /verifier/verify page.
# Fixed by wiring both buttons to the existing authenticated blob-fetch
# functions (viewSharedCredentialDocument / downloadSharedCredentialDocument
# in src/lib/api.ts) that already worked correctly on the QR/link share page.
#
# These tests cover the two scenarios from the permission test matrix that
# test_share_permissions.py didn't already assert: the actual Content-Type
# header and byte-exact equality with the originally uploaded document —
# proving this is the real stored PDF, never a fake/mock one.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%docview\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "DocView Inst", "role": "institution", "institution_id": str(institution.id)},
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
            "full_name": "DocView Student",
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
        json={"email": email, "password": "Password123", "full_name": "DocView Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    assert resp.status_code == 201, resp.text
    return {"token": resp.json()["access_token"]}


def _issue(client, inst_token, student_id):
    files = {"document": ("degree.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": "degree", "title": "Degree"},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _request_and_share(client, verifier_token, student_token, student_identifier, credential_id, permission="view_only"):
    req = client.post(
        "/api/credential-requests",
        json={"student_identifier": student_identifier, "purpose": "Doc view test", "requested_credentials": ["Degree"]},
        headers=_auth_header(verifier_token),
    ).json()
    resp = client.post(
        f"/api/credential-requests/{req['id']}/approve",
        json={"credential_ids": [credential_id], "expires_in_days": 7, "permission": permission},
        headers=_auth_header(student_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _setup(client, db_session, suffix, permission="view_only"):
    inst = _register_institution(client, db_session, f"docview-inst-{suffix}@test.credchain.dev", f"DocView University {suffix}")
    student = _register_student(client, inst["institution_id"], f"docview-stu-{suffix}@test.credchain.dev", f"DOCVIEW-STU-{suffix}")
    verifier = _register_verifier(client, db_session, f"docview-co-{suffix}@test.credchain.dev", f"DocView Co {suffix}")
    credential_id = _issue(client, inst["token"], student["student_id"])
    _request_and_share(client, verifier["token"], student["token"], f"DOCVIEW-STU-{suffix}", credential_id, permission=permission)
    return {"inst": inst, "student": student, "verifier": verifier, "credential_id": credential_id}


def test_view_endpoint_returns_real_pdf_content_type(client, db_session):
    ctx = _setup(client, db_session, "1a")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/view", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"


def test_view_endpoint_returns_exact_stored_bytes(client, db_session):
    """The core anti-fake-document guarantee: the response body is byte-for-byte identical to what the institution actually uploaded."""
    ctx = _setup(client, db_session, "1b")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/view", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200
    assert resp.content == SAMPLE_PDF_BYTES


def test_download_endpoint_returns_exact_stored_bytes(client, db_session):
    ctx = _setup(client, db_session, "1c", permission="view_download")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/download", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200
    assert resp.content == SAMPLE_PDF_BYTES
    assert resp.headers["content-type"] == "application/pdf"


def test_download_endpoint_sets_attachment_disposition(client, db_session):
    """View is inline (no Content-Disposition); download is a real attachment — the frontend distinguishes the two by calling different endpoints, not by guessing."""
    ctx = _setup(client, db_session, "1d", permission="view_download")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/download", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "").lower()


def test_view_endpoint_has_no_content_disposition(client, db_session):
    ctx = _setup(client, db_session, "1e")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/view", headers=_auth_header(ctx["verifier"]["token"]))
    assert resp.status_code == 200
    assert "content-disposition" not in {k.lower() for k in resp.headers.keys()}


def test_a_different_companys_share_does_not_grant_view(client, db_session):
    """Explicit 'another company's share' case: Company B was never shared with — not even indirectly via Company A's grant."""
    ctx = _setup(client, db_session, "1f")
    other_company = _register_verifier(client, db_session, "docview-co-other-1f@test.credchain.dev", "DocView Co Other 1f")

    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/view", headers=_auth_header(other_company["token"]))
    assert resp.status_code == 403


def test_view_requires_authentication(client, db_session):
    ctx = _setup(client, db_session, "1g")
    resp = client.get(f"/api/verification/credentials/{ctx['credential_id']}/view")
    assert resp.status_code == 401
