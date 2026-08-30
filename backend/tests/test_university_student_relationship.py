# ---------------------------------------------------------------------------
# University <-> Student relationship: tests for the NEW mechanisms that
# establish Student.institution_id safely (registration-time selection, and
# the authenticated link/re-link endpoint), plus the public institution
# listing used to pick a real institution.
#
# The authorization boundary itself (institution can only see/issue-to its
# own students, cannot see another institution's) already existed and is
# already covered extensively elsewhere (test_credential_issuance.py,
# test_student_lookup.py) — those tests are untouched and still pass. This
# file only adds coverage for what's actually new: how the link gets
# created in the first place, and that it can never be an invented id.
# ---------------------------------------------------------------------------

import uuid

from app.models.student import Student


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    return resp


def _register_institution(client, db_session, email="usr-inst@test.credchain.dev", name="USR University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = _register(client, role="institution", email=email, institution_id=str(institution.id))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


# --- public institution listing -------------------------------------------------


def test_institution_list_is_public_and_shows_real_institutions(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-list@test.credchain.dev", name="USR Listed University")
    resp = client.get("/api/institutions")  # no auth header at all
    assert resp.status_code == 200
    names = [i["name"] for i in resp.json()]
    assert "USR Listed University" in names
    # never exposes anything beyond id/name
    assert set(resp.json()[0].keys()) == {"id", "name"}


# --- 1/2/3: registration-time linking establishes a real relationship ------------


def test_student_can_register_with_institution_and_it_is_immediately_visible(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-a@test.credchain.dev", name="USR University A")

    resp = _register(
        client,
        role="student",
        email="usr-student-a@test.credchain.dev",
        student_identifier="USR-STU-A",
        institution_id=inst["institution_id"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["student_institution_id"] == inst["institution_id"]
    assert body["user"]["student_institution_name"] == "USR University A"

    # institution sees the student immediately, with no separate seed/manual step
    students_resp = client.get("/api/institutions/me/students", headers=_auth_header(inst["token"]))
    assert students_resp.status_code == 200
    assert any(s["student_identifier"] == "USR-STU-A" for s in students_resp.json())


def test_register_with_fake_institution_id_is_rejected(client, db_session):
    """The security invariant: an institution_id must correspond to a real row — never accepted blindly."""
    resp = _register(
        client,
        role="student",
        email="usr-student-fake@test.credchain.dev",
        student_identifier="USR-STU-FAKE",
        institution_id=str(uuid.uuid4()),
    )
    assert resp.status_code == 404


def test_student_without_institution_registers_successfully_and_shows_unlinked(client, db_session):
    resp = _register(client, role="student", email="usr-student-unlinked@test.credchain.dev", student_identifier="USR-STU-UNLINKED")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["student_institution_id"] is None
    assert body["user"]["student_institution_name"] is None


# --- link endpoint: the after-the-fact / re-link path -----------------------------


def test_student_can_link_institution_after_registration(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-b@test.credchain.dev", name="USR University B")
    student_resp = _register(client, role="student", email="usr-student-b@test.credchain.dev", student_identifier="USR-STU-B")
    student_token = student_resp.json()["access_token"]

    link_resp = client.post(
        "/api/students/me/institution",
        json={"institution_id": inst["institution_id"]},
        headers=_auth_header(student_token),
    )
    assert link_resp.status_code == 200, link_resp.text
    assert link_resp.json()["institution_name"] == "USR University B"

    # persists and is visible on /auth/me (survives "refresh")
    me = client.get("/api/auth/me", headers=_auth_header(student_token))
    assert me.json()["student_institution_id"] == inst["institution_id"]
    assert me.json()["student_institution_name"] == "USR University B"

    # and the institution now sees this student
    students_resp = client.get("/api/institutions/me/students", headers=_auth_header(inst["token"]))
    assert any(s["student_identifier"] == "USR-STU-B" for s in students_resp.json())


def test_link_to_nonexistent_institution_is_rejected(client, db_session):
    student_resp = _register(client, role="student", email="usr-student-c@test.credchain.dev", student_identifier="USR-STU-C")
    student_token = student_resp.json()["access_token"]

    resp = client.post(
        "/api/students/me/institution",
        json={"institution_id": str(uuid.uuid4())},
        headers=_auth_header(student_token),
    )
    assert resp.status_code == 404

    # the student's institution remains unset — a failed link attempt never corrupts state
    db_session.expire_all()
    student = db_session.query(Student).filter(Student.student_identifier == "USR-STU-C").first()
    assert student.institution_id is None


def test_link_institution_requires_student_role(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-d@test.credchain.dev", name="USR University D")
    resp = client.post(
        "/api/students/me/institution",
        json={"institution_id": inst["institution_id"]},
        headers=_auth_header(inst["token"]),
    )
    assert resp.status_code == 403


def test_link_institution_requires_authentication(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-e@test.credchain.dev", name="USR University E")
    resp = client.post("/api/students/me/institution", json={"institution_id": inst["institution_id"]})
    assert resp.status_code == 401


# --- 5/6: issuance authorization uses the newly-established link -----------------


def test_issue_credential_to_newly_linked_student_succeeds(client, db_session):
    inst = _register_institution(client, db_session, email="usr-inst-f@test.credchain.dev", name="USR University F")
    student_resp = _register(
        client, role="student", email="usr-student-f@test.credchain.dev", student_identifier="USR-STU-F",
        institution_id=inst["institution_id"],
    )
    student_id = student_resp.json()["user"]["student_id"]

    files = {"document": ("t.pdf", b"%PDF-1.4\n%test\ntrailer\n<< /Root 1 0 R >>\n%%EOF", "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": "degree", "title": "Test Degree"},
        files=files,
        headers=_auth_header(inst["token"]),
    )
    assert resp.status_code == 201, resp.text


def test_issue_credential_to_student_linked_elsewhere_is_rejected(client, db_session):
    inst_a = _register_institution(client, db_session, email="usr-inst-g@test.credchain.dev", name="USR University G")
    inst_b = _register_institution(client, db_session, email="usr-inst-h@test.credchain.dev", name="USR University H")
    student_resp = _register(
        client, role="student", email="usr-student-g@test.credchain.dev", student_identifier="USR-STU-G",
        institution_id=inst_b["institution_id"],  # linked to B
    )
    student_id = student_resp.json()["user"]["student_id"]

    files = {"document": ("t.pdf", b"%PDF-1.4\n%test\ntrailer\n<< /Root 1 0 R >>\n%%EOF", "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": "degree", "title": "Test Degree"},
        files=files,
        headers=_auth_header(inst_a["token"]),  # A tries to issue to B's student
    )
    assert resp.status_code == 403
