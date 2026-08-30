# ---------------------------------------------------------------------------
# Phase A: admin role, institution/company verification gates, and the login
# rate limiter. Every institution/company registered anywhere in this test
# suite is auto-verified at insert time (see conftest.py's after_insert
# hooks) — tests here that need to exercise the PENDING/REJECTED gate itself
# deliberately reset verification_status back down first, via db_session
# directly, exactly the way conftest.py's hook comment documents.
# ---------------------------------------------------------------------------

import uuid

import pytest

from app.models.company import Company
from app.models.institution import Institution
from app.models.user import User
from app.security import login_rate_limit

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%credchain-test-fixture\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, email, role, full_name="Test User", **extra):
    payload = {"email": email, "password": "Password123", "full_name": full_name, "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, email=email, role="institution", institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, email=email, role="verifier", company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _register_student(client, institution_id, email, identifier):
    body = _register(client, email=email, role="student", student_identifier=identifier, institution_id=institution_id)
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _create_admin(db_session, email="admin@test.credchain.dev") -> User:
    from app.models.enums import UserRole
    from app.security.password import hash_password

    admin = User(email=email, password_hash=hash_password("AdminPass123"), full_name="Test Admin", role=UserRole.ADMIN, is_active=True)
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _admin_token(client, db_session, email="admin@test.credchain.dev") -> str:
    _create_admin(db_session, email)
    resp = client.post("/api/auth/login", json={"email": email, "password": "AdminPass123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _set_institution_status(db_session, institution_id: str, status: str) -> None:
    inst = db_session.query(Institution).filter(Institution.id == uuid.UUID(institution_id)).first()
    inst.verification_status = status
    db_session.commit()


def _set_company_status(db_session, company_id: str, status: str) -> None:
    company = db_session.query(Company).filter(Company.id == uuid.UUID(company_id)).first()
    company.verification_status = status
    db_session.commit()


def _issue(client, institution_token, student_id):
    data = {"student_id": student_id, "credential_type": "transcript", "title": "Final Transcript"}
    files = {"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    return client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token))


# --- Admin cannot self-register ---------------------------------------------


def test_admin_role_cannot_self_register(client, db_session):
    resp = client.post(
        "/api/auth/register",
        json={"email": "sneaky-admin@test.credchain.dev", "password": "Password123", "full_name": "Sneaky", "role": "admin"},
    )
    assert resp.status_code == 403


# --- Authorization: only admin can reach admin endpoints ---------------------


@pytest.mark.parametrize(
    "role,register_fn,email",
    [
        ("student", None, "auth-student@test.credchain.dev"),
        ("institution", _register_institution, "auth-inst@test.credchain.dev"),
        ("verifier", _register_verifier, "auth-verifier@test.credchain.dev"),
    ],
)
def test_non_admin_roles_get_403_on_admin_endpoints(client, db_session, role, register_fn, email):
    if role == "student":
        inst = _register_institution(client, db_session, "auth-owner@test.credchain.dev", "Auth Owner Uni")
        token = _register_student(client, inst["institution_id"], email, "AUTH-STU")["token"]
    else:
        token = register_fn(client, email, "Auth Test Org")["token"]

    for path in ("/api/admin/institutions/pending", "/api/admin/companies/pending"):
        resp = client.get(path, headers=_auth_header(token))
        assert resp.status_code == 403, f"{role} on {path}: {resp.text}"


def test_unauthenticated_request_to_admin_endpoint_is_401(client, db_session):
    resp = client.get("/api/admin/institutions/pending")
    assert resp.status_code == 401


# --- Admin: institution verification lifecycle -------------------------------


def test_admin_can_list_approve_and_reject_institutions(client, db_session):
    admin_token = _admin_token(client, db_session)

    pending_inst = _register_institution(client, db_session, "pending-inst@test.credchain.dev", "Pending University")
    _set_institution_status(db_session, pending_inst["institution_id"], "pending")

    listing = client.get("/api/admin/institutions/pending", headers=_auth_header(admin_token))
    assert listing.status_code == 200
    page = listing.json()
    assert set(page.keys()) == {"items", "page", "page_size", "total", "total_pages"}
    ids = [i["id"] for i in page["items"]]
    assert pending_inst["institution_id"] in ids
    row = next(i for i in page["items"] if i["id"] == pending_inst["institution_id"])
    assert row["contact_email"] == "pending-inst@test.credchain.dev"

    approve = client.post(f"/api/admin/institutions/{pending_inst['institution_id']}/approve", headers=_auth_header(admin_token))
    assert approve.status_code == 200
    assert approve.json()["verification_status"] == "verified"

    # Already-decided: approving again is rejected, not silently repeated.
    again = client.post(f"/api/admin/institutions/{pending_inst['institution_id']}/approve", headers=_auth_header(admin_token))
    assert again.status_code == 409

    other_inst = _register_institution(client, db_session, "reject-inst@test.credchain.dev", "Reject University")
    _set_institution_status(db_session, other_inst["institution_id"], "pending")
    reject = client.post(
        f"/api/admin/institutions/{other_inst['institution_id']}/reject",
        json={"reason": "Could not verify registration number"},
        headers=_auth_header(admin_token),
    )
    assert reject.status_code == 200
    assert reject.json()["verification_status"] == "rejected"


def test_admin_reject_requires_a_reason(client, db_session):
    admin_token = _admin_token(client, db_session)
    inst = _register_institution(client, db_session, "reason-inst@test.credchain.dev", "Reason University")
    _set_institution_status(db_session, inst["institution_id"], "pending")
    resp = client.post(f"/api/admin/institutions/{inst['institution_id']}/reject", json={"reason": ""}, headers=_auth_header(admin_token))
    assert resp.status_code == 422


def test_admin_cannot_verify_a_directory_only_institution(client, db_session):
    """A directory listing (user_id IS NULL) is not an account — there is nothing to verify."""
    admin_token = _admin_token(client, db_session)
    directory_row = Institution(user_id=None, name="Directory Only University")
    db_session.add(directory_row)
    db_session.commit()

    resp = client.post(f"/api/admin/institutions/{directory_row.id}/approve", headers=_auth_header(admin_token))
    assert resp.status_code == 409


# --- Admin pending queues: pagination, search, and scope ---------------------


def test_admin_pending_institutions_pagination(client, db_session):
    admin_token = _admin_token(client, db_session)
    for i in range(3):
        inst = _register_institution(client, db_session, f"page-inst-{i}@test.credchain.dev", f"Page University {i}")
        _set_institution_status(db_session, inst["institution_id"], "pending")

    page1 = client.get("/api/admin/institutions/pending", params={"page": 1, "page_size": 2}, headers=_auth_header(admin_token))
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["total_pages"] == 2
    assert len(body1["items"]) == 2

    page2 = client.get("/api/admin/institutions/pending", params={"page": 2, "page_size": 2}, headers=_auth_header(admin_token))
    body2 = page2.json()
    assert len(body2["items"]) == 1
    assert {i["id"] for i in body1["items"]}.isdisjoint({i["id"] for i in body2["items"]})


def test_admin_pending_institutions_search_by_name(client, db_session):
    admin_token = _admin_token(client, db_session)
    matching = _register_institution(client, db_session, "search-match-inst@test.credchain.dev", "Zeta Search University")
    _set_institution_status(db_session, matching["institution_id"], "pending")
    other = _register_institution(client, db_session, "search-other-inst@test.credchain.dev", "Omega Institute")
    _set_institution_status(db_session, other["institution_id"], "pending")

    resp = client.get("/api/admin/institutions/pending", params={"search": "zeta"}, headers=_auth_header(admin_token))
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == matching["institution_id"]


def test_admin_pending_institutions_page_size_over_max_is_rejected(client, db_session):
    admin_token = _admin_token(client, db_session)
    resp = client.get("/api/admin/institutions/pending", params={"page_size": 500}, headers=_auth_header(admin_token))
    assert resp.status_code == 422


def test_admin_pending_institutions_never_include_verified_or_rejected(client, db_session):
    admin_token = _admin_token(client, db_session)
    verified = _register_institution(client, db_session, "already-verified-inst@test.credchain.dev", "Already Verified Uni")
    rejected = _register_institution(client, db_session, "already-rejected-inst@test.credchain.dev", "Already Rejected Uni")
    _set_institution_status(db_session, rejected["institution_id"], "rejected")

    resp = client.get("/api/admin/institutions/pending", headers=_auth_header(admin_token))
    ids = [i["id"] for i in resp.json()["items"]]
    assert verified["institution_id"] not in ids  # auto-verified by the conftest hook, never pending
    assert rejected["institution_id"] not in ids


def test_admin_pending_companies_pagination(client, db_session):
    admin_token = _admin_token(client, db_session)
    for i in range(3):
        co = _register_verifier(client, db_session, f"page-co-{i}@test.credchain.dev", f"Page Co {i}")
        _set_company_status(db_session, co["company_id"], "pending")

    page1 = client.get("/api/admin/companies/pending", params={"page": 1, "page_size": 2}, headers=_auth_header(admin_token))
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["total_pages"] == 2
    assert len(body1["items"]) == 2

    page2 = client.get("/api/admin/companies/pending", params={"page": 2, "page_size": 2}, headers=_auth_header(admin_token))
    body2 = page2.json()
    assert len(body2["items"]) == 1
    assert {c["id"] for c in body1["items"]}.isdisjoint({c["id"] for c in body2["items"]})


def test_admin_pending_companies_search_by_name(client, db_session):
    admin_token = _admin_token(client, db_session)
    matching = _register_verifier(client, db_session, "search-match-co@test.credchain.dev", "Zeta Search Corp")
    _set_company_status(db_session, matching["company_id"], "pending")
    other = _register_verifier(client, db_session, "search-other-co@test.credchain.dev", "Omega Corp")
    _set_company_status(db_session, other["company_id"], "pending")

    resp = client.get("/api/admin/companies/pending", params={"search": "zeta"}, headers=_auth_header(admin_token))
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == matching["company_id"]


def test_admin_pending_companies_never_include_verified_or_rejected(client, db_session):
    admin_token = _admin_token(client, db_session)
    verified = _register_verifier(client, db_session, "already-verified-co@test.credchain.dev", "Already Verified Co")
    rejected = _register_verifier(client, db_session, "already-rejected-co@test.credchain.dev", "Already Rejected Co")
    _set_company_status(db_session, rejected["company_id"], "rejected")

    resp = client.get("/api/admin/companies/pending", headers=_auth_header(admin_token))
    ids = [c["id"] for c in resp.json()["items"]]
    assert verified["company_id"] not in ids
    assert rejected["company_id"] not in ids


def test_admin_pagination_authorization_still_enforced(client, db_session):
    """The paginated/searchable variants of these endpoints still require require_admin — same boundary, not weakened by this change."""
    inst = _register_institution(client, db_session, "pag-auth-inst@test.credchain.dev", "Pagination Auth Uni")
    resp = client.get(
        "/api/admin/institutions/pending", params={"page": 1, "page_size": 5}, headers=_auth_header(inst["token"])
    )
    assert resp.status_code == 403


# --- Admin: company verification lifecycle -----------------------------------


def test_admin_can_list_approve_and_reject_companies(client, db_session):
    admin_token = _admin_token(client, db_session)

    pending_co = _register_verifier(client, db_session, "pending-co@test.credchain.dev", "Pending Co")
    _set_company_status(db_session, pending_co["company_id"], "pending")

    listing = client.get("/api/admin/companies/pending", headers=_auth_header(admin_token))
    assert listing.status_code == 200
    ids = [c["id"] for c in listing.json()["items"]]
    assert pending_co["company_id"] in ids

    approve = client.post(f"/api/admin/companies/{pending_co['company_id']}/approve", headers=_auth_header(admin_token))
    assert approve.status_code == 200
    assert approve.json()["verification_status"] == "verified"

    other_co = _register_verifier(client, db_session, "reject-co@test.credchain.dev", "Reject Co")
    _set_company_status(db_session, other_co["company_id"], "pending")
    reject = client.post(
        f"/api/admin/companies/{other_co['company_id']}/reject",
        json={"reason": "Website does not resolve"},
        headers=_auth_header(admin_token),
    )
    assert reject.status_code == 200
    assert reject.json()["verification_status"] == "rejected"


# --- Institution verification gates credential issuance ----------------------


def test_pending_institution_cannot_issue_credentials(client, db_session):
    inst = _register_institution(client, db_session, "gate-pending-inst@test.credchain.dev", "Gate Pending Uni")
    student = _register_student(client, inst["institution_id"], "gate-pending-stu@test.credchain.dev", "GATE-PEND")
    _set_institution_status(db_session, inst["institution_id"], "pending")

    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 403
    assert "pending" in resp.json()["detail"].lower()


def test_rejected_institution_cannot_issue_credentials(client, db_session):
    inst = _register_institution(client, db_session, "gate-rejected-inst@test.credchain.dev", "Gate Rejected Uni")
    student = _register_student(client, inst["institution_id"], "gate-rejected-stu@test.credchain.dev", "GATE-REJ")
    _set_institution_status(db_session, inst["institution_id"], "rejected")

    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 403
    assert "rejected" in resp.json()["detail"].lower()


def test_verified_institution_can_issue_credentials(client, db_session):
    """Verified is the auto-verified default the conftest.py hook already applies on registration — this is the control case proving the gate doesn't over-block."""
    inst = _register_institution(client, db_session, "gate-verified-inst@test.credchain.dev", "Gate Verified Uni")
    student = _register_student(client, inst["institution_id"], "gate-verified-stu@test.credchain.dev", "GATE-OK")

    resp = _issue(client, inst["token"], student["student_id"])
    assert resp.status_code == 201, resp.text


def test_bulk_issuance_also_blocked_for_pending_institution(client, db_session):
    inst = _register_institution(client, db_session, "gate-bulk-inst@test.credchain.dev", "Gate Bulk Uni")
    student = _register_student(client, inst["institution_id"], "gate-bulk-stu@test.credchain.dev", "GATE-BULK")
    _set_institution_status(db_session, inst["institution_id"], "pending")

    data = {"student_ids": [student["student_id"]], "credential_type": "transcript", "title": "Bulk Transcript"}
    files = [("documents", ("t.pdf", SAMPLE_PDF_BYTES, "application/pdf"))]
    resp = client.post("/api/institutions/me/credentials/bulk", data=data, files=files, headers=_auth_header(inst["token"]))
    assert resp.status_code == 403


# --- Company verification gates job publication -------------------------------


def _job_payload(**overrides):
    payload = {"title": "Software Engineer", "description": "Build things.", "employment_type": "full_time"}
    payload.update(overrides)
    return payload


def test_pending_company_cannot_publish_job(client, db_session):
    verifier = _register_verifier(client, db_session, "gate-pending-co@test.credchain.dev", "Gate Pending Co")
    _set_company_status(db_session, verifier["company_id"], "pending")

    create = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(verifier["token"]))
    assert create.status_code == 201, create.text  # draft creation is never gated
    job_id = create.json()["id"]

    publish = client.post(f"/api/companies/me/jobs/{job_id}/publish", headers=_auth_header(verifier["token"]))
    assert publish.status_code == 403
    assert "pending" in publish.json()["detail"].lower()


def test_rejected_company_cannot_publish_job(client, db_session):
    verifier = _register_verifier(client, db_session, "gate-rejected-co@test.credchain.dev", "Gate Rejected Co")
    create = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(verifier["token"]))
    job_id = create.json()["id"]
    _set_company_status(db_session, verifier["company_id"], "rejected")

    publish = client.post(f"/api/companies/me/jobs/{job_id}/publish", headers=_auth_header(verifier["token"]))
    assert publish.status_code == 403
    assert "rejected" in publish.json()["detail"].lower()


def test_verified_company_can_publish_job(client, db_session):
    verifier = _register_verifier(client, db_session, "gate-verified-co@test.credchain.dev", "Gate Verified Co")
    create = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(verifier["token"]))
    job_id = create.json()["id"]

    publish = client.post(f"/api/companies/me/jobs/{job_id}/publish", headers=_auth_header(verifier["token"]))
    assert publish.status_code == 200
    assert publish.json()["status"] == "open"


# --- Existing accounts are unaffected by the gate machinery -------------------


def test_existing_registered_institution_keeps_working_end_to_end(client, db_session):
    """Simulates a pre-Phase-A account: the migration grandfathers real registered rows to
    'verified' — here that's simply the auto-verified state every registration already gets in
    this test suite, exercised through the exact same student/credential flow as before Phase A."""
    inst = _register_institution(client, db_session, "existing-inst@test.credchain.dev", "Existing University")
    student = _register_student(client, inst["institution_id"], "existing-stu@test.credchain.dev", "EXIST-STU")
    assert _issue(client, inst["token"], student["student_id"]).status_code == 201


def test_directory_only_institution_is_not_a_platform_account(client, db_session):
    """A directory-only row must never be treated as verified merely for existing in the directory — it has no user_id, so it isn't in the admin pending queue either (nothing to decide)."""
    directory_row = Institution(user_id=None, name="Directory Only U2")
    db_session.add(directory_row)
    db_session.commit()
    assert directory_row.verification_status.value == "pending"  # the harmless, irrelevant default — no account exists to act on it

    admin_token = _admin_token(client, db_session)
    listing = client.get("/api/admin/institutions/pending", headers=_auth_header(admin_token))
    assert str(directory_row.id) not in [i["id"] for i in listing.json()["items"]]


# --- Jobs pagination -----------------------------------------------------------


def test_jobs_endpoint_returns_paginated_envelope(client, db_session):
    inst = _register_institution(client, db_session, "jobs-page-inst@test.credchain.dev", "Jobs Page Uni")
    student = _register_student(client, inst["institution_id"], "jobs-page-stu@test.credchain.dev", "JOBS-PAGE")
    verifier = _register_verifier(client, db_session, "jobs-page-co@test.credchain.dev", "Jobs Page Co")

    for n in range(3):
        job = client.post("/api/companies/me/jobs", json=_job_payload(title=f"Role {n}"), headers=_auth_header(verifier["token"])).json()
        client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    resp = client.get("/api/jobs", params={"page": 1, "page_size": 2}, headers=_auth_header(student["token"]))
    assert resp.status_code == 200
    page = resp.json()
    assert set(page.keys()) == {"items", "page", "page_size", "total", "total_pages"}
    assert page["page"] == 1
    assert page["page_size"] == 2
    assert page["total"] == 3
    assert page["total_pages"] == 2
    assert len(page["items"]) == 2

    page2 = client.get("/api/jobs", params={"page": 2, "page_size": 2}, headers=_auth_header(student["token"])).json()
    assert len(page2["items"]) == 1
    assert {j["id"] for j in page["items"]}.isdisjoint({j["id"] for j in page2["items"]})


def test_jobs_page_size_over_max_is_rejected(client, db_session):
    inst = _register_institution(client, db_session, "jobs-max-inst@test.credchain.dev", "Jobs Max Uni")
    student = _register_student(client, inst["institution_id"], "jobs-max-stu@test.credchain.dev", "JOBS-MAX")
    resp = client.get("/api/jobs", params={"page_size": 500}, headers=_auth_header(student["token"]))
    assert resp.status_code == 422


def test_jobs_pagination_respects_search_filter_and_total(client, db_session):
    inst = _register_institution(client, db_session, "jobs-search-inst@test.credchain.dev", "Jobs Search Uni")
    student = _register_student(client, inst["institution_id"], "jobs-search-stu@test.credchain.dev", "JOBS-SEARCH")
    verifier = _register_verifier(client, db_session, "jobs-search-co@test.credchain.dev", "Jobs Search Co")

    for title in ("Backend Engineer", "Frontend Engineer", "Mechanical Technician"):
        job = client.post("/api/companies/me/jobs", json=_job_payload(title=title), headers=_auth_header(verifier["token"])).json()
        client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    resp = client.get("/api/jobs", params={"search": "Engineer"}, headers=_auth_header(student["token"]))
    page = resp.json()
    assert page["total"] == 2
    titles = {j["title"] for j in page["items"]}
    assert titles == {"Backend Engineer", "Frontend Engineer"}


# --- Login rate limiting -------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """The rate limiter is a module-level in-memory store, not reset by the db_session transaction rollback that isolates every other test — clear it before and after each test in this file so tests can't leak lockout state into each other."""
    login_rate_limit._ACCOUNT_FAILURES.clear()
    login_rate_limit._IP_FAILURES.clear()
    yield
    login_rate_limit._ACCOUNT_FAILURES.clear()
    login_rate_limit._IP_FAILURES.clear()


def test_normal_login_is_not_rate_limited(client, db_session):
    _register(client, email="rl-normal@test.credchain.dev", role="student", student_identifier="RL-NORMAL")
    resp = client.post("/api/auth/login", json={"email": "rl-normal@test.credchain.dev", "password": "Password123"})
    assert resp.status_code == 200


def test_repeated_failed_logins_eventually_return_429(client, db_session):
    email = "rl-brute@test.credchain.dev"
    _register(client, email=email, role="student", student_identifier="RL-BRUTE")

    statuses = []
    for _ in range(login_rate_limit.MAX_ACCOUNT_ATTEMPTS + 2):
        resp = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword1"})
        statuses.append(resp.status_code)

    assert 401 in statuses
    assert statuses[-1] == 429
    assert "too many" in client.post("/api/auth/login", json={"email": email, "password": "WrongPassword1"}).json()["detail"].lower()


def test_successful_login_resets_the_account_failure_counter(client, db_session):
    email = "rl-reset@test.credchain.dev"
    _register(client, email=email, role="student", student_identifier="RL-RESET")

    for _ in range(login_rate_limit.MAX_ACCOUNT_ATTEMPTS - 1):
        client.post("/api/auth/login", json={"email": email, "password": "WrongPassword1"})

    # Not yet locked out — one more real failure would be, but a correct password succeeds first.
    ok = client.post("/api/auth/login", json={"email": email, "password": "Password123"})
    assert ok.status_code == 200

    # The account counter was cleared by the successful login, so a fresh run of failures starts
    # from zero again rather than being immediately locked out from where the last run left off.
    resp = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword1"})
    assert resp.status_code == 401


def test_rate_limit_does_not_disclose_whether_an_account_exists(client, db_session):
    """A nonexistent email hits the same InvalidCredentialsError path (and the same rate-limit accounting) as a wrong password for a real account — the 401 body must be identical either way."""
    real_email = "rl-enum-real@test.credchain.dev"
    _register(client, email=real_email, role="student", student_identifier="RL-ENUM")

    real_resp = client.post("/api/auth/login", json={"email": real_email, "password": "WrongPassword1"})
    fake_resp = client.post("/api/auth/login", json={"email": "rl-enum-does-not-exist@test.credchain.dev", "password": "WrongPassword1"})
    assert real_resp.status_code == fake_resp.status_code == 401
    assert real_resp.json() == fake_resp.json()
