# ---------------------------------------------------------------------------
# PS3 Phase E: notification counts. Every count here must be real (backed
# by actual rows) and must change as the underlying state changes — never a
# hardcoded number, never stale after the action that should clear it.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%notif\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Notif Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Notif Student {identifier}",
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
        json={"email": email, "password": "Password123", "full_name": "Notif Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    return {"token": resp.json()["access_token"]}


def test_institution_pending_certificate_request_count_is_real_and_clears_on_approval(client, db_session):
    inst = _register_institution(client, db_session, "notif-inst-1@test.credchain.dev", "Notif University 1")
    student = _register_student(client, inst["institution_id"], "notif-stu-1@test.credchain.dev", "NOTIF-STU-1")

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(inst["token"])).json()
    assert counts["pending_certificate_requests"] == 0

    req = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": inst["institution_id"], "credential_type": "degree"},
        headers=_auth_header(student["token"]),
    ).json()

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(inst["token"])).json()
    assert counts["pending_certificate_requests"] == 1

    client.post(f"/api/institutions/me/certificate-requests/{req['id']}/approve", headers=_auth_header(inst["token"]))

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(inst["token"])).json()
    assert counts["pending_certificate_requests"] == 0


def test_institution_pending_document_review_count_is_real_and_clears_on_review(client, db_session):
    inst = _register_institution(client, db_session, "notif-inst-2@test.credchain.dev", "Notif University 2")
    student = _register_student(client, inst["institution_id"], "notif-stu-2@test.credchain.dev", "NOTIF-STU-2")

    files = {"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    doc = client.post(
        "/api/students/me/documents",
        data={"institution_id": inst["institution_id"], "credential_type": "migration"},
        files=files,
        headers=_auth_header(student["token"]),
    ).json()

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(inst["token"])).json()
    assert counts["pending_document_reviews"] == 1

    client.post(f"/api/institutions/me/documents/{doc['id']}/approve", headers=_auth_header(inst["token"]))

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(inst["token"])).json()
    assert counts["pending_document_reviews"] == 0


def test_student_pending_company_request_count_is_real(client, db_session):
    inst = _register_institution(client, db_session, "notif-inst-3@test.credchain.dev", "Notif University 3")
    student = _register_student(client, inst["institution_id"], "notif-stu-3@test.credchain.dev", "NOTIF-STU-3")
    verifier = _register_verifier(client, db_session, "notif-verifier-1@test.credchain.dev", "Notif Co 1")

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(student["token"])).json()
    assert counts["pending_company_requests"] == 0

    client.post(
        "/api/credential-requests",
        json={"student_identifier": "NOTIF-STU-3", "purpose": "Job app", "requested_credentials": ["Degree"]},
        headers=_auth_header(verifier["token"]),
    )

    counts = client.get("/api/notifications/me/counts", headers=_auth_header(student["token"])).json()
    assert counts["pending_company_requests"] == 1


def test_cross_institution_notification_counts_are_isolated(client, db_session):
    inst_a = _register_institution(client, db_session, "notif-inst-xa@test.credchain.dev", "Notif University XA")
    inst_b = _register_institution(client, db_session, "notif-inst-xb@test.credchain.dev", "Notif University XB")
    student = _register_student(client, inst_a["institution_id"], "notif-stu-xa@test.credchain.dev", "NOTIF-STU-XA")

    client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": inst_a["institution_id"], "credential_type": "degree"},
        headers=_auth_header(student["token"]),
    )

    counts_a = client.get("/api/notifications/me/counts", headers=_auth_header(inst_a["token"])).json()
    counts_b = client.get("/api/notifications/me/counts", headers=_auth_header(inst_b["token"])).json()
    assert counts_a["pending_certificate_requests"] == 1
    assert counts_b["pending_certificate_requests"] == 0
