# ---------------------------------------------------------------------------
# Tests for GET /api/companies/me/shared-credentials — the paginated,
# searchable, filterable "Credentials Shared With You" inbox backing the new
# CredentialInbox.tsx UI. Authorization is unchanged: this is scoped to the
# logged-in company's own canonical company_id exactly like every other
# /api/companies/me/* route (see sharing_service.list_shared_credentials_for_company).
# ---------------------------------------------------------------------------

import uuid

from app.models.credential import Credential
from app.models.enums import CredentialStatus

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


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email, identifier):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email, name):
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
    resp = client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _direct_share(client, student_token, company_id, credential_id, expires_in_days=7, permission="view_only"):
    resp = client.post(
        "/api/students/me/shares",
        json={"company_id": company_id, "credential_ids": [credential_id], "expires_in_days": expires_in_days, "permission": permission},
        headers=_auth_header(student_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _verify(client, verifier_token, credential_id, demo_cgpa_override=None):
    body = {"credential_id": credential_id}
    if demo_cgpa_override is not None:
        body["demo_cgpa_override"] = demo_cgpa_override
    return client.post("/api/verification/verify", json=body, headers=_auth_header(verifier_token))


def _inbox(client, verifier_token, **params):
    return client.get("/api/companies/me/shared-credentials", params=params, headers=_auth_header(verifier_token))


def _setup(client, db_session, suffix):
    inst = _register_institution(client, db_session, f"inbox-inst-{suffix}@test.credchain.dev", f"Inbox University {suffix}")
    student = _register_student(client, db_session, inst["institution_id"], f"inbox-stu-{suffix}@test.credchain.dev", f"INBOX-STU-{suffix}")
    verifier = _register_verifier(client, db_session, f"inbox-co-{suffix}@test.credchain.dev", f"Inbox Corp {suffix}")
    credential = _issue_credential(client, inst["token"], student["student_id"])
    share = _direct_share(client, student["token"], verifier["company_id"], credential["id"])
    return {"inst": inst, "student": student, "verifier": verifier, "credential": credential, "share": share}


# =====================================================================
# Core shape / "not verified" default
# =====================================================================


def test_inbox_shows_not_verified_by_default(client, db_session):
    ctx = _setup(client, db_session, "1a")
    resp = _inbox(client, ctx["verifier"]["token"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["latest_verification_result"] is None
    assert item["latest_verified_at"] is None
    assert item["student_name"] == "Test Student"
    assert item["institution_name"] == "Inbox University 1a"
    assert item["title"] == "Final Transcript"
    assert item["share_status"] == "active"
    assert item["id"] == ctx["credential"]["id"]
    assert item["share_id"] == ctx["share"]["share"]["id"]


def test_inbox_requires_authentication(client, db_session):
    resp = client.get("/api/companies/me/shared-credentials")
    assert resp.status_code == 401


# =====================================================================
# Real verification results, never inferred
# =====================================================================


def test_inbox_reflects_latest_verified_status(client, db_session):
    ctx = _setup(client, db_session, "1b")
    v = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    assert v.json()["result"] == "VERIFIED"

    item = _inbox(client, ctx["verifier"]["token"]).json()["items"][0]
    assert item["latest_verification_result"] == "VERIFIED"
    assert item["latest_verified_at"] is not None


def test_inbox_reflects_invalid_after_tamper_demo(client, db_session):
    ctx = _setup(client, db_session, "1c")
    tampered = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"], demo_cgpa_override=9.7)
    assert tampered.json()["result"] == "INVALID"

    item = _inbox(client, ctx["verifier"]["token"]).json()["items"][0]
    assert item["latest_verification_result"] == "INVALID"


def test_inbox_reflects_revoked_credential(client, db_session):
    ctx = _setup(client, db_session, "1d")
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.status = CredentialStatus.REVOKED
    db_session.commit()

    v = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    assert v.json()["result"] == "REVOKED"

    item = _inbox(client, ctx["verifier"]["token"]).json()["items"][0]
    assert item["latest_verification_result"] == "REVOKED"


def test_inbox_reflects_expired_credential(client, db_session):
    ctx = _setup(client, db_session, "1e")
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.status = CredentialStatus.EXPIRED
    db_session.commit()

    v = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    assert v.json()["result"] == "EXPIRED"

    item = _inbox(client, ctx["verifier"]["token"]).json()["items"][0]
    assert item["latest_verification_result"] == "EXPIRED"


# =====================================================================
# Filtering
# =====================================================================


def test_inbox_filter_matches_only_the_requested_status(client, db_session):
    ctx = _setup(client, db_session, "1f")
    _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])

    matching = _inbox(client, ctx["verifier"]["token"], status="verified")
    assert matching.json()["total"] == 1

    non_matching = _inbox(client, ctx["verifier"]["token"], status="revoked")
    assert non_matching.json()["total"] == 0


def test_inbox_rejects_invalid_status_filter(client, db_session):
    ctx = _setup(client, db_session, "1g")
    resp = _inbox(client, ctx["verifier"]["token"], status="not-a-real-status")
    assert resp.status_code == 422


# =====================================================================
# Search
# =====================================================================


def test_inbox_search_by_student_name(client, db_session):
    ctx = _setup(client, db_session, "1h")
    assert _inbox(client, ctx["verifier"]["token"], search="Test Student").json()["total"] == 1
    assert _inbox(client, ctx["verifier"]["token"], search="Nonexistent Name Zzz").json()["total"] == 0


def test_inbox_search_by_institution_name(client, db_session):
    ctx = _setup(client, db_session, "1i")
    assert _inbox(client, ctx["verifier"]["token"], search="Inbox University 1i").json()["total"] == 1


def test_inbox_search_by_credential_title(client, db_session):
    ctx = _setup(client, db_session, "1j")
    assert _inbox(client, ctx["verifier"]["token"], search="Final Transcript").json()["total"] == 1


def test_inbox_search_by_credential_type(client, db_session):
    ctx = _setup(client, db_session, "1k")
    assert _inbox(client, ctx["verifier"]["token"], search="transcript").json()["total"] == 1


# =====================================================================
# Pagination — never loads more than one page's worth
# =====================================================================


def test_inbox_pagination(client, db_session):
    ctx = _setup(client, db_session, "1l")
    for i in range(2):
        cred = _issue_credential(client, ctx["inst"]["token"], ctx["student"]["student_id"], title=f"Extra Credential {i}")
        _direct_share(client, ctx["student"]["token"], ctx["verifier"]["company_id"], cred["id"])

    page1 = _inbox(client, ctx["verifier"]["token"], page=1, page_size=2).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert page1["total_pages"] == 2

    page2 = _inbox(client, ctx["verifier"]["token"], page=2, page_size=2).json()
    assert len(page2["items"]) == 1


# =====================================================================
# Authorization: only this company's own shares, never another's
# =====================================================================


def test_inbox_only_shows_own_company_shares(client, db_session):
    ctx = _setup(client, db_session, "1m")
    other_verifier = _register_verifier(client, db_session, "inbox-other-1m@test.credchain.dev", "Other Corp 1m")

    assert _inbox(client, other_verifier["token"]).json()["total"] == 0
    assert _inbox(client, ctx["verifier"]["token"]).json()["total"] == 1


# =====================================================================
# Multiple shares of the same credential are never hidden/deduplicated
# =====================================================================


def test_inbox_shows_two_separate_shares_of_the_same_credential_distinctly(client, db_session):
    ctx = _setup(client, db_session, "1n")
    _direct_share(client, ctx["student"]["token"], ctx["verifier"]["company_id"], ctx["credential"]["id"])

    body = _inbox(client, ctx["verifier"]["token"]).json()
    assert body["total"] == 2
    share_ids = {item["share_id"] for item in body["items"]}
    assert len(share_ids) == 2
    assert all(item["id"] == ctx["credential"]["id"] for item in body["items"])
