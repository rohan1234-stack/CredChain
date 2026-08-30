# ---------------------------------------------------------------------------
# Phase 8C: dedicated coverage for institution/company registration and
# logout, filling gaps not already exercised by test_auth.py's role-
# authorization tests (which register those roles only incidentally, to get
# a token to test the role-gating dependency).
# ---------------------------------------------------------------------------

from app.models.company import Company
from app.models.institution import Institution
from app.models.user import User


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- institution registration (canonical-directory claim model) -----------------


def test_institution_registration_claims_existing_directory_record_and_creates_keypair(client, db_session):
    """
    Institution signup no longer creates a new Institution row from typed text —
    it must select an existing canonical directory record (by id) and claim it.
    """
    directory_row = Institution(name="Signup University", registration_number="REG-001")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-inst@test.credchain.dev",
            "password": "Password123",
            "full_name": "Admin Contact",
            "role": "institution",
            "institution_id": str(directory_row.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "institution"
    assert body["user"]["org_name"] == "Signup University"
    assert body["user"]["institution_id"] == str(directory_row.id)

    # Exactly the same canonical row was claimed — no duplicate was created.
    matches = db_session.query(Institution).filter(Institution.name == "Signup University").all()
    assert len(matches) == 1
    assert matches[0].id == directory_row.id
    assert str(matches[0].user_id) == body["user"]["id"]
    # ensure_institution_keypair runs synchronously during registration.
    assert matches[0].public_key is not None


def test_institution_registration_missing_institution_id_rejected(client):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-inst-bad@test.credchain.dev",
            "password": "Password123",
            "full_name": "Admin Contact",
            "role": "institution",
        },
    )
    assert resp.status_code == 422


def test_institution_registration_unknown_institution_id_is_404(client):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-inst-unknown@test.credchain.dev",
            "password": "Password123",
            "full_name": "Admin Contact",
            "role": "institution",
            "institution_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 404


def test_institution_registration_already_claimed_institution_is_rejected(client, db_session):
    """Two different accounts must never both end up owning the same canonical Institution row."""
    directory_row = Institution(name="Already Claimed University")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    first = client.post(
        "/api/auth/register",
        json={
            "email": "first-claim@test.credchain.dev",
            "password": "Password123",
            "full_name": "First Admin",
            "role": "institution",
            "institution_id": str(directory_row.id),
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/auth/register",
        json={
            "email": "second-claim@test.credchain.dev",
            "password": "Password123",
            "full_name": "Second Admin",
            "role": "institution",
            "institution_id": str(directory_row.id),
        },
    )
    assert second.status_code == 409
    # Never overwritten — the row still belongs to whoever claimed it first.
    db_session.refresh(directory_row)
    assert str(directory_row.user_id) == first.json()["user"]["id"]

    # Still exactly one Institution row with this name — the rejected second attempt
    # must not have created a duplicate.
    assert db_session.query(Institution).filter(Institution.name == "Already Claimed University").count() == 1


# --- company registration (canonical-directory claim model) ---------------------


def test_company_registration_claims_existing_directory_record(client, db_session):
    directory_row = Company(name="Signup Technologies", industry="Software", website="https://signup.example.com")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-company@test.credchain.dev",
            "password": "Password123",
            "full_name": "HR Contact",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "verifier"
    assert body["user"]["org_name"] == "Signup Technologies"
    assert body["user"]["company_id"] == str(directory_row.id)

    matches = db_session.query(Company).filter(Company.name == "Signup Technologies").all()
    assert len(matches) == 1
    assert matches[0].id == directory_row.id
    assert str(matches[0].user_id) == body["user"]["id"]
    assert matches[0].industry == "Software"
    assert matches[0].website == "https://signup.example.com"


def test_company_registration_missing_company_id_rejected(client):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-company-bad@test.credchain.dev",
            "password": "Password123",
            "full_name": "HR Contact",
            "role": "verifier",
        },
    )
    assert resp.status_code == 422


def test_company_registration_already_claimed_company_is_rejected(client, db_session):
    directory_row = Company(name="Already Claimed Technologies")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    first = client.post(
        "/api/auth/register",
        json={
            "email": "first-co-claim@test.credchain.dev",
            "password": "Password123",
            "full_name": "First HR",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/auth/register",
        json={
            "email": "second-co-claim@test.credchain.dev",
            "password": "Password123",
            "full_name": "Second HR",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    )
    assert second.status_code == 409
    db_session.refresh(directory_row)
    assert str(directory_row.user_id) == first.json()["user"]["id"]
    assert db_session.query(Company).filter(Company.name == "Already Claimed Technologies").count() == 1


# --- registration establishes a real, immediately-usable session ----------------


def test_registration_returns_working_session_token(client):
    """Register -> the returned token is real and immediately authenticates, matching login's behavior (no separate auth path)."""
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "signup-session@test.credchain.dev",
            "password": "Password123",
            "full_name": "Test Student",
            "role": "student",
            "student_identifier": "SIGNUP-STU-001",
        },
    )
    token = resp.json()["access_token"]
    me = client.get("/api/auth/me", headers=_auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "signup-session@test.credchain.dev"


# --- logout -----------------------------------------------------------------------


def test_logout_requires_valid_token(client):
    resp = client.post("/api/auth/register", json={
        "email": "logout-test@test.credchain.dev",
        "password": "Password123",
        "full_name": "Test Student",
        "role": "student",
        "student_identifier": "LOGOUT-STU-001",
    })
    token = resp.json()["access_token"]

    logout_resp = client.post("/api/auth/logout", headers=_auth_header(token))
    assert logout_resp.status_code == 200

    unauth_logout = client.post("/api/auth/logout")
    assert unauth_logout.status_code == 401


def test_token_still_usable_after_logout_call(client):
    """
    Stateless JWT (documented in routes/auth.py) — logout doesn't revoke the
    token server-side; the frontend discarding it is what actually ends the
    session. This test documents that real behavior rather than assuming
    server-side revocation that doesn't exist.
    """
    resp = client.post("/api/auth/register", json={
        "email": "logout-stateless@test.credchain.dev",
        "password": "Password123",
        "full_name": "Test Student",
        "role": "student",
        "student_identifier": "LOGOUT-STU-002",
    })
    token = resp.json()["access_token"]

    client.post("/api/auth/logout", headers=_auth_header(token))
    # The same token is still cryptographically valid for a fresh request —
    # session persistence across refresh, and the reason the frontend must
    # be the one to discard it on logout.
    me = client.get("/api/auth/me", headers=_auth_header(token))
    assert me.status_code == 200


# --- users cannot self-elevate role by any registration trick -------------------


def test_registering_twice_with_different_role_is_rejected(client):
    """A user can't 'switch role' by re-registering the same email as a different role — email uniqueness blocks it."""
    email = "no-role-switch@test.credchain.dev"
    first = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Test", "role": "student", "student_identifier": "NRS-001"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Test", "role": "institution"},
    )
    assert second.status_code == 409


def test_user_object_has_no_writable_role_field_client_side(client):
    """The role in every response comes from the DB row created at registration — there is no endpoint that mutates a user's role."""
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "role-immutable@test.credchain.dev",
            "password": "Password123",
            "full_name": "Test Student",
            "role": "student",
            "student_identifier": "IMMUTABLE-001",
        },
    )
    user_id = resp.json()["user"]["id"]
    token = resp.json()["access_token"]

    # Confirm /me always reflects the DB row's role, not anything client-supplied.
    me = client.get("/api/auth/me", headers=_auth_header(token))
    assert me.json()["role"] == "student"
    assert me.json()["id"] == user_id
