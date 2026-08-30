# ---------------------------------------------------------------------------
# Final polish pass: GET /api/institutions/me/students/lookup/{identifier} —
# the manual-entry fallback for credential issuance when an institution
# doesn't want to (or can't) pick a student from the dropdown. Never a way
# to bypass the existing institution/student ownership boundary that
# issue_credential already enforces.
# ---------------------------------------------------------------------------

import uuid

from app.models.student import Student


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email="lookup-inst@test.credchain.dev", name="Lookup University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="lookup-student@test.credchain.dev", identifier="STU-LOOKUP-001"):
    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def test_institution_can_look_up_own_linked_student(client, db_session):
    inst = _register_institution(client, db_session)
    _register_student(client, db_session, inst["institution_id"])

    resp = client.get("/api/institutions/me/students/lookup/STU-LOOKUP-001", headers=_auth_header(inst["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Test Student"
    assert body["student_identifier"] == "STU-LOOKUP-001"


def test_lookup_unknown_identifier_returns_clear_404(client, db_session):
    inst = _register_institution(client, db_session)
    resp = client.get("/api/institutions/me/students/lookup/NO-SUCH-ID", headers=_auth_header(inst["token"]))
    assert resp.status_code == 404
    assert "must create a CredChain account" in resp.json()["detail"]


def test_lookup_cannot_reach_another_institutions_student(client, db_session):
    """A real student identifier that belongs to a DIFFERENT institution must not be usable — same ownership boundary as issuance itself."""
    inst_a = _register_institution(client, db_session, email="lookup-inst-a@test.credchain.dev", name="Lookup University A")
    inst_b = _register_institution(client, db_session, email="lookup-inst-b@test.credchain.dev", name="Lookup University B")
    _register_student(client, db_session, inst_a["institution_id"], email="lookup-student-a@test.credchain.dev", identifier="STU-LOOKUP-A")

    resp = client.get("/api/institutions/me/students/lookup/STU-LOOKUP-A", headers=_auth_header(inst_b["token"]))
    assert resp.status_code == 404


def test_lookup_requires_institution_role(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    resp = client.get("/api/institutions/me/students/lookup/STU-LOOKUP-001", headers=_auth_header(student["token"]))
    assert resp.status_code == 403
