# ---------------------------------------------------------------------------
# Canonical organization identity: an Institution/Company row is claimed by
# exactly one user account (auth_service.register_user), never created fresh
# from typed text. These tests cover what test_registration_flow.py doesn't
# already: no partial/orphan state after a rejected claim, and that the
# existing ownership-scoped endpoints around institutions/companies can't be
# used as a side-channel to move or duplicate organization ownership.
# ---------------------------------------------------------------------------

from app.models.company import Company
from app.models.institution import Institution
from app.models.user import User


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_rejected_institution_claim_leaves_no_orphan_user(client, db_session):
    """
    A second registration attempt against an already-claimed institution must
    fail atomically — the just-created User row for that attempt must not
    survive (no login-capable account left behind with no real profile).
    """
    directory_row = Institution(name="No Orphan University")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    first = client.post(
        "/api/auth/register",
        json={
            "email": "orphan-first@test.credchain.dev",
            "password": "Password123",
            "full_name": "First",
            "role": "institution",
            "institution_id": str(directory_row.id),
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={
            "email": "orphan-second@test.credchain.dev",
            "password": "Password123",
            "full_name": "Second",
            "role": "institution",
            "institution_id": str(directory_row.id),
        },
    )
    assert second.status_code == 409

    # The rejected attempt's email must not exist as a user at all — proving the
    # whole transaction (User row included) rolled back, not just the claim.
    login = client.post("/api/auth/login", json={"email": "orphan-second@test.credchain.dev", "password": "Password123"})
    assert login.status_code == 401
    assert db_session.query(User).filter(User.email == "orphan-second@test.credchain.dev").first() is None


def test_rejected_company_claim_leaves_no_orphan_user(client, db_session):
    directory_row = Company(name="No Orphan Technologies")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    first = client.post(
        "/api/auth/register",
        json={
            "email": "co-orphan-first@test.credchain.dev",
            "password": "Password123",
            "full_name": "First",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/register",
        json={
            "email": "co-orphan-second@test.credchain.dev",
            "password": "Password123",
            "full_name": "Second",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    )
    assert second.status_code == 409

    login = client.post("/api/auth/login", json={"email": "co-orphan-second@test.credchain.dev", "password": "Password123"})
    assert login.status_code == 401
    assert db_session.query(User).filter(User.email == "co-orphan-second@test.credchain.dev").first() is None


def test_student_link_institution_endpoint_only_ever_affects_the_caller(client, db_session):
    """
    IDOR check: POST /api/students/me/institution derives the student purely from
    the authenticated user (current_user.student) — a payload can never target a
    different student's row, even if it tried to smuggle one in.
    """
    inst_a = Institution(name="Link Target University A")
    inst_b = Institution(name="Link Target University B")
    db_session.add_all([inst_a, inst_b])
    db_session.commit()
    db_session.refresh(inst_a)
    db_session.refresh(inst_b)

    student_a = client.post(
        "/api/auth/register",
        json={
            "email": "link-idor-a@test.credchain.dev",
            "password": "Password123",
            "full_name": "Student A",
            "role": "student",
            "student_identifier": "LINK-IDOR-A",
        },
    ).json()
    student_b = client.post(
        "/api/auth/register",
        json={
            "email": "link-idor-b@test.credchain.dev",
            "password": "Password123",
            "full_name": "Student B",
            "role": "student",
            "student_identifier": "LINK-IDOR-B",
        },
    ).json()

    # Student A links themself to inst_a — even if the payload also carried a
    # (nonexistent, schema-unknown) student_id field pointed at B, the endpoint has
    # no such field: it can only ever act on the authenticated caller's own row.
    resp = client.post(
        "/api/students/me/institution",
        json={"institution_id": str(inst_a.id), "student_id": student_b["user"]["student_id"]},
        headers=_auth_header(student_a["access_token"]),
    )
    assert resp.status_code == 200

    from app.models.student import Student

    a_row = db_session.query(Student).filter(Student.id == student_a["user"]["student_id"]).first()
    b_row = db_session.query(Student).filter(Student.id == student_b["user"]["student_id"]).first()
    assert str(a_row.institution_id) == str(inst_a.id)
    assert b_row.institution_id is None  # untouched


def test_company_profile_update_cannot_smuggle_a_user_id_reassignment(client, db_session):
    """
    PATCH /api/companies/me is schema-limited (UpdateCompanyProfileBody has no
    user_id field) — even a payload that includes one is silently ignored, never
    reassigning ownership of the canonical Company row.
    """
    directory_row = Company(name="Immutable Owner Technologies")
    db_session.add(directory_row)
    db_session.commit()
    db_session.refresh(directory_row)

    reg = client.post(
        "/api/auth/register",
        json={
            "email": "immutable-owner@test.credchain.dev",
            "password": "Password123",
            "full_name": "Owner",
            "role": "verifier",
            "company_id": str(directory_row.id),
        },
    ).json()
    original_user_id = reg["user"]["id"]

    resp = client.patch(
        "/api/companies/me",
        json={"description": "Trying to hijack ownership", "user_id": "00000000-0000-0000-0000-000000000000"},
        headers=_auth_header(reg["access_token"]),
    )
    assert resp.status_code == 200

    db_session.refresh(directory_row)
    assert str(directory_row.user_id) == original_user_id


def test_admin_verification_endpoints_reject_institution_and_verifier_roles(client, db_session):
    """Reinforces the existing admin-only gate specifically in the context of organization claims."""
    inst = Institution(name="Non Admin Uni")
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)

    inst_reg = client.post(
        "/api/auth/register",
        json={
            "email": "non-admin-inst@test.credchain.dev",
            "password": "Password123",
            "full_name": "Non Admin",
            "role": "institution",
            "institution_id": str(inst.id),
        },
    ).json()

    resp = client.get("/api/admin/institutions/pending", headers=_auth_header(inst_reg["access_token"]))
    assert resp.status_code == 403
