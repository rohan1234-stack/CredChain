# ---------------------------------------------------------------------------
# Phase 3 auth tests. Role-authorization tests (8-10, and the two "critical"
# tests from the spec) mount three throwaway protected endpoints onto the
# app for the test session only, via require_student/require_institution/
# require_verifier — no student/institution/verifier *business* endpoints
# exist yet (that's Phase 4+), so this is the only way to test the
# dependencies end-to-end over real HTTP without waiting for those routes.
# ---------------------------------------------------------------------------

import uuid
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends

from app.main import app
from app.security.jwt import create_access_token
from app.security.password import hash_password
from app.security.permissions import require_institution, require_student, require_verifier

# --- register throwaway role-gated test routes (once) ----------------------

_test_router = APIRouter(prefix="/api/_test", tags=["test-only"])


@_test_router.get("/student-only")
def _student_only(user=Depends(require_student)):
    return {"ok": True, "role": user.role.value}


@_test_router.get("/institution-only")
def _institution_only(user=Depends(require_institution)):
    return {"ok": True, "role": user.role.value}


@_test_router.get("/verifier-only")
def _verifier_only(user=Depends(require_verifier)):
    return {"ok": True, "role": user.role.value}


app.include_router(_test_router)


# --- helpers -----------------------------------------------------------------

STUDENT_PAYLOAD = {
    "email": "student1@test.credchain.dev",
    "password": "Password123",
    "full_name": "Test Student",
    "role": "student",
    "student_identifier": "TEST-STU-001",
}
# institution_id/company_id are filled in per-test (a real directory row must exist first —
# see test_institution_role_authorization/test_verifier_role_authorization below), since
# registration now claims an existing canonical directory record rather than creating one
# from a typed name.
INSTITUTION_PAYLOAD = {
    "email": "institution1@test.credchain.dev",
    "password": "Password123",
    "full_name": "Test Institution Admin",
    "role": "institution",
}
VERIFIER_PAYLOAD = {
    "email": "verifier1@test.credchain.dev",
    "password": "Password123",
    "full_name": "Test Verifier",
    "role": "verifier",
}


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- 1/2: registration -------------------------------------------------------


def test_register_success(client):
    resp = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["email"] == STUDENT_PAYLOAD["email"]
    assert body["user"]["role"] == "student"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_duplicate_email(client):
    client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    resp = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    assert resp.status_code == 409


# --- 3/4: login ---------------------------------------------------------------


def test_login_success(client):
    client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    resp = client.post(
        "/api/auth/login", json={"email": STUDENT_PAYLOAD["email"], "password": STUDENT_PAYLOAD["password"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_incorrect_password(client):
    client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    resp = client.post("/api/auth/login", json={"email": STUDENT_PAYLOAD["email"], "password": "WrongPassword1"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_login_nonexistent_email_same_error_as_wrong_password(client):
    resp = client.post("/api/auth/login", json={"email": "nobody@nowhere.dev", "password": "Whatever123"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


# --- 5/6: token validity -------------------------------------------------------


def test_me_invalid_token(client):
    resp = client.get("/api/auth/me", headers=_auth_header("not-a-real-jwt"))
    assert resp.status_code == 401


def test_me_expired_token(client):
    reg = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    user_id = uuid.UUID(reg.json()["user"]["id"])
    expired_token = create_access_token(subject=user_id, role="student", expires_delta=timedelta(minutes=-5))
    resp = client.get("/api/auth/me", headers=_auth_header(expired_token))
    assert resp.status_code == 401


# --- 7: /me ---------------------------------------------------------------------


def test_me_success(client):
    reg = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    token = reg.json()["access_token"]
    resp = client.get("/api/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == STUDENT_PAYLOAD["email"]
    assert body["role"] == "student"
    assert body["student_id"] is not None


# --- 8/9/10: role authorization ---------------------------------------------------


def test_student_role_authorization(client):
    reg = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    token = reg.json()["access_token"]

    assert client.get("/api/_test/student-only", headers=_auth_header(token)).status_code == 200
    # critical test: student JWT -> institution-only endpoint -> 403
    assert client.get("/api/_test/institution-only", headers=_auth_header(token)).status_code == 403
    assert client.get("/api/_test/verifier-only", headers=_auth_header(token)).status_code == 403


def test_institution_role_authorization(client, db_session):
    from app.models.institution import Institution

    institution = Institution(name="Test University")
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)

    reg = client.post("/api/auth/register", json={**INSTITUTION_PAYLOAD, "institution_id": str(institution.id)})
    token = reg.json()["access_token"]

    assert client.get("/api/_test/institution-only", headers=_auth_header(token)).status_code == 200
    assert client.get("/api/_test/student-only", headers=_auth_header(token)).status_code == 403
    assert client.get("/api/_test/verifier-only", headers=_auth_header(token)).status_code == 403


def test_verifier_role_authorization(client, db_session):
    from app.models.company import Company

    company = Company(name="Test Company")
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)

    reg = client.post("/api/auth/register", json={**VERIFIER_PAYLOAD, "company_id": str(company.id)})
    token = reg.json()["access_token"]

    assert client.get("/api/_test/verifier-only", headers=_auth_header(token)).status_code == 200
    assert client.get("/api/_test/student-only", headers=_auth_header(token)).status_code == 403
    assert client.get("/api/_test/institution-only", headers=_auth_header(token)).status_code == 403


# --- 11: inactive user -------------------------------------------------------------


def test_inactive_user_login_rejected(client, db_session):
    reg = client.post("/api/auth/register", json=STUDENT_PAYLOAD)
    assert reg.status_code == 201

    from app.models.user import User

    user = db_session.query(User).filter(User.email == STUDENT_PAYLOAD["email"]).first()
    user.is_active = False
    db_session.commit()

    resp = client.post(
        "/api/auth/login", json={"email": STUDENT_PAYLOAD["email"], "password": STUDENT_PAYLOAD["password"]}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account is inactive"


# --- 12: protected endpoint without authentication --------------------------------


def test_protected_endpoint_without_token(client):
    # critical test: no JWT -> protected endpoint -> 401
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_protected_test_route_without_token(client):
    resp = client.get("/api/_test/student-only")
    assert resp.status_code == 401


# --- extra: password hashing sanity -------------------------------------------------


def test_passwords_are_hashed_not_plaintext(client, db_session):
    client.post("/api/auth/register", json=STUDENT_PAYLOAD)

    from app.models.user import User

    user = db_session.query(User).filter(User.email == STUDENT_PAYLOAD["email"]).first()
    assert user.password_hash != STUDENT_PAYLOAD["password"]
    assert user.password_hash.startswith("$argon2")
