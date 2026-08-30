# ---------------------------------------------------------------------------
# Activity Feed presentation fix: focused coverage confirming render_message()
# (backend/app/services/activity_service.py) already produces a real, human-
# readable message for every action code the frontend's Activity Feed mapping
# was extended to support (APPLICATION_*, CERTIFICATE_REQUEST_*,
# STUDENT_DOCUMENT_*, ADMIN_*) — never the generic "Activity recorded"
# fallback, never a raw snake_case entity_type string embedded in the
# sentence. There is no frontend test framework in this repo, so this only
# verifies the backend data the frontend's label/category/icon maps render
# from is already correct — it does not (and cannot) test the frontend
# mapping tables themselves.
# ---------------------------------------------------------------------------

import uuid

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%actmsg\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"

# Raw entity_type strings that must never leak into a rendered message —
# these are the multi-word snake_case identifiers a user could visibly
# recognize as "internal"; single-word ones (institution/company/credential)
# are also real English words that legitimately appear in real sentences, so
# there is no meaningful "raw leakage" check possible for those.
_RAW_ENTITY_STRINGS = ("job_application", "institution_certificate_request", "student_document")


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_human_readable(message: str) -> None:
    assert message, "expected a non-empty message"
    assert message != "Activity recorded", f"fell through to the generic fallback: {message!r}"
    for raw in _RAW_ENTITY_STRINGS:
        assert raw not in message, f"raw entity_type leaked into message: {message!r}"


def _register(client, *, role, email, full_name="Test User", **extra):
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
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    body = _register(client, role="student", email=email, student_identifier=identifier, institution_id=institution_id)
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _create_admin(db_session, email) -> None:
    from app.models.enums import UserRole
    from app.models.user import User
    from app.security.password import hash_password

    admin = User(email=email, password_hash=hash_password("AdminPass123"), full_name="Test Admin", role=UserRole.ADMIN, is_active=True)
    db_session.add(admin)
    db_session.commit()


def _admin_token(client, db_session, email) -> str:
    _create_admin(db_session, email)
    resp = client.post("/api/auth/login", json={"email": email, "password": "AdminPass123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _set_institution_status(db_session, institution_id, status) -> None:
    from app.models.institution import Institution

    inst = db_session.query(Institution).filter(Institution.id == uuid.UUID(institution_id)).first()
    inst.verification_status = status
    db_session.commit()


def _set_company_status(db_session, company_id, status) -> None:
    from app.models.company import Company

    company = db_session.query(Company).filter(Company.id == uuid.UUID(company_id)).first()
    company.verification_status = status
    db_session.commit()


def _row_for_action(rows: list[dict], action: str) -> dict:
    matches = [r for r in rows if r["action"] == action]
    assert matches, f"no activity row found for action {action!r} among {[r['action'] for r in rows]}"
    return matches[-1]


# --- APPLICATION_* ------------------------------------------------------------


def test_application_lifecycle_messages_are_human_readable(client, db_session):
    inst = _register_institution(client, db_session, "actmsg-inst@test.credchain.dev", "ActMsg University")
    student = _register_student(client, inst["institution_id"], "actmsg-stu@test.credchain.dev", "ACTMSG-STU-1")
    verifier = _register_verifier(client, db_session, "actmsg-verifier@test.credchain.dev", "ActMsg Co")

    cred = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student["student_id"], "credential_type": "migration", "title": "Migration Certificate"},
        files={"document": ("m.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(inst["token"]),
    ).json()

    job = client.post(
        "/api/companies/me/jobs",
        json={"title": "Backend Engineer", "description": "Ship things", "employment_type": "full_time", "required_documents": ["Migration Certificate"]},
        headers=_auth_header(verifier["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier["token"]))

    apply_resp = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred["id"]]},
        headers=_auth_header(student["token"]),
    )
    assert apply_resp.status_code == 201, apply_resp.text
    app_id = apply_resp.json()["id"]

    def student_rows():
        return client.get("/api/students/me/activity", headers=_auth_header(student["token"])).json()

    def company_rows():
        return client.get("/api/companies/me/activity", headers=_auth_header(verifier["token"])).json()

    submitted = _row_for_action(student_rows(), "APPLICATION_SUBMITTED")
    _assert_human_readable(submitted["message"])
    assert job["title"] in submitted["message"]
    _assert_human_readable(_row_for_action(company_rows(), "APPLICATION_SUBMITTED")["message"])

    client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "under_review"}, headers=_auth_header(verifier["token"]))
    under_review = _row_for_action(student_rows(), "APPLICATION_UNDER_REVIEW")
    _assert_human_readable(under_review["message"])
    assert job["title"] in under_review["message"]

    client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "shortlisted"}, headers=_auth_header(verifier["token"]))
    shortlisted = _row_for_action(student_rows(), "APPLICATION_SHORTLISTED")
    _assert_human_readable(shortlisted["message"])

    client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "accepted"}, headers=_auth_header(verifier["token"]))
    accepted = _row_for_action(student_rows(), "APPLICATION_ACCEPTED")
    _assert_human_readable(accepted["message"])
    _assert_human_readable(_row_for_action(company_rows(), "APPLICATION_ACCEPTED")["message"])

    # A second, independent application to exercise REJECTED directly from "applied".
    student_b = _register_student(client, inst["institution_id"], "actmsg-stu-b@test.credchain.dev", "ACTMSG-STU-2")
    cred_b = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_b["student_id"], "credential_type": "migration", "title": "Migration Certificate"},
        files={"document": ("m2.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(inst["token"]),
    ).json()
    app_b_id = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_b["id"]]},
        headers=_auth_header(student_b["token"]),
    ).json()["id"]
    client.post(f"/api/companies/me/applications/{app_b_id}/status", json={"status": "rejected"}, headers=_auth_header(verifier["token"]))
    rejected_rows = client.get("/api/students/me/activity", headers=_auth_header(student_b["token"])).json()
    rejected = _row_for_action(rejected_rows, "APPLICATION_REJECTED")
    _assert_human_readable(rejected["message"])
    _assert_human_readable(_row_for_action(company_rows(), "APPLICATION_REJECTED")["message"])

    # A third, independent application to exercise WITHDRAWN.
    student_c = _register_student(client, inst["institution_id"], "actmsg-stu-c@test.credchain.dev", "ACTMSG-STU-3")
    cred_c = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_c["student_id"], "credential_type": "migration", "title": "Migration Certificate"},
        files={"document": ("m3.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(inst["token"]),
    ).json()
    app_c_id = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_c["id"]]},
        headers=_auth_header(student_c["token"]),
    ).json()["id"]
    client.post(f"/api/students/me/applications/{app_c_id}/withdraw", headers=_auth_header(student_c["token"]))
    withdrawn_rows = client.get("/api/students/me/activity", headers=_auth_header(student_c["token"])).json()
    _assert_human_readable(_row_for_action(withdrawn_rows, "APPLICATION_WITHDRAWN")["message"])


# --- CERTIFICATE_REQUEST_* -----------------------------------------------------


def test_certificate_request_messages_are_human_readable(client, db_session):
    inst = _register_institution(client, db_session, "actmsg-cert-inst@test.credchain.dev", "ActMsg Cert University")
    student = _register_student(client, inst["institution_id"], "actmsg-cert-stu@test.credchain.dev", "ACTMSG-CERT-1")

    req_id = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": inst["institution_id"], "credential_type": "degree"},
        headers=_auth_header(student["token"]),
    ).json()["id"]
    submitted = _row_for_action(
        client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json(), "CERTIFICATE_REQUEST_CREATED"
    )
    _assert_human_readable(submitted["message"])

    client.post(f"/api/institutions/me/certificate-requests/{req_id}/approve", headers=_auth_header(inst["token"]))
    approved = _row_for_action(
        client.get("/api/students/me/activity", headers=_auth_header(student["token"])).json(), "CERTIFICATE_REQUEST_APPROVED"
    )
    _assert_human_readable(approved["message"])
    _assert_human_readable(
        _row_for_action(client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json(), "CERTIFICATE_REQUEST_APPROVED")[
            "message"
        ]
    )

    req_id_2 = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": inst["institution_id"], "credential_type": "transcript"},
        headers=_auth_header(student["token"]),
    ).json()["id"]
    client.post(
        f"/api/institutions/me/certificate-requests/{req_id_2}/reject",
        json={"reason": "Missing prerequisite coursework"},
        headers=_auth_header(inst["token"]),
    )
    rejected = _row_for_action(
        client.get("/api/students/me/activity", headers=_auth_header(student["token"])).json(), "CERTIFICATE_REQUEST_REJECTED"
    )
    _assert_human_readable(rejected["message"])


# --- STUDENT_DOCUMENT_* --------------------------------------------------------


def test_student_document_messages_are_human_readable(client, db_session):
    inst = _register_institution(client, db_session, "actmsg-doc-inst@test.credchain.dev", "ActMsg Doc University")
    student = _register_student(client, inst["institution_id"], "actmsg-doc-stu@test.credchain.dev", "ACTMSG-DOC-1")

    doc_id = client.post(
        "/api/students/me/documents",
        data={"institution_id": inst["institution_id"], "credential_type": "migration"},
        files={"document": ("d.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(student["token"]),
    ).json()["id"]
    submitted = _row_for_action(
        client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json(), "STUDENT_DOCUMENT_SUBMITTED"
    )
    _assert_human_readable(submitted["message"])

    client.post(f"/api/institutions/me/documents/{doc_id}/approve", headers=_auth_header(inst["token"]))
    approved = _row_for_action(
        client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json(), "STUDENT_DOCUMENT_APPROVED"
    )
    _assert_human_readable(approved["message"])

    doc_id_2 = client.post(
        "/api/students/me/documents",
        data={"institution_id": inst["institution_id"], "credential_type": "internship"},
        files={"document": ("d2.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(student["token"]),
    ).json()["id"]
    client.post(
        f"/api/institutions/me/documents/{doc_id_2}/reject",
        json={"reason": "Illegible scan"},
        headers=_auth_header(inst["token"]),
    )
    rejected = _row_for_action(
        client.get("/api/students/me/activity", headers=_auth_header(student["token"])).json(), "STUDENT_DOCUMENT_REJECTED"
    )
    _assert_human_readable(rejected["message"])


# --- ADMIN_* --------------------------------------------------------------------


def test_admin_institution_and_company_messages_are_human_readable(client, db_session):
    inst_approved = _register_institution(client, db_session, "actmsg-admin-inst-a@test.credchain.dev", "ActMsg Admin University A")
    inst_rejected = _register_institution(client, db_session, "actmsg-admin-inst-b@test.credchain.dev", "ActMsg Admin University B")
    _set_institution_status(db_session, inst_approved["institution_id"], "pending")
    _set_institution_status(db_session, inst_rejected["institution_id"], "pending")

    company_approved = _register_verifier(client, db_session, "actmsg-admin-co-a@test.credchain.dev", "ActMsg Admin Co A")
    company_rejected = _register_verifier(client, db_session, "actmsg-admin-co-b@test.credchain.dev", "ActMsg Admin Co B")
    _set_company_status(db_session, company_approved["company_id"], "pending")
    _set_company_status(db_session, company_rejected["company_id"], "pending")

    admin_token = _admin_token(client, db_session, "actmsg-admin@test.credchain.dev")

    client.post(f"/api/admin/institutions/{inst_approved['institution_id']}/approve", headers=_auth_header(admin_token))
    approved_msg = _row_for_action(
        client.get("/api/institutions/me/activity", headers=_auth_header(inst_approved["token"])).json(), "ADMIN_APPROVED_INSTITUTION"
    )["message"]
    _assert_human_readable(approved_msg)

    client.post(
        f"/api/admin/institutions/{inst_rejected['institution_id']}/reject",
        json={"reason": "Accreditation could not be verified"},
        headers=_auth_header(admin_token),
    )
    rejected_msg = _row_for_action(
        client.get("/api/institutions/me/activity", headers=_auth_header(inst_rejected["token"])).json(), "ADMIN_REJECTED_INSTITUTION"
    )["message"]
    _assert_human_readable(rejected_msg)
    assert "Accreditation could not be verified" in rejected_msg

    client.post(f"/api/admin/companies/{company_approved['company_id']}/approve", headers=_auth_header(admin_token))
    company_approved_msg = _row_for_action(
        client.get("/api/companies/me/activity", headers=_auth_header(company_approved["token"])).json(), "ADMIN_APPROVED_COMPANY"
    )["message"]
    _assert_human_readable(company_approved_msg)

    client.post(
        f"/api/admin/companies/{company_rejected['company_id']}/reject",
        json={"reason": "Business registration mismatch"},
        headers=_auth_header(admin_token),
    )
    company_rejected_msg = _row_for_action(
        client.get("/api/companies/me/activity", headers=_auth_header(company_rejected["token"])).json(), "ADMIN_REJECTED_COMPANY"
    )["message"]
    _assert_human_readable(company_rejected_msg)
    assert "Business registration mismatch" in company_rejected_msg
