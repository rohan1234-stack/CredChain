# ---------------------------------------------------------------------------
# Tests for the notification center (backend/app/models/notification.py,
# services/notification_service.py, routes/notifications.py) and the
# ActivityLog additions/fixes that feed it (activity_service.py,
# institution_request_service.py, student_document_service.py,
# credential_service.py, sharing_service.py, job_application_service.py,
# admin_service.py, auth_service.py).
#
# Follows test_activity.py's ownership/isolation style: real HTTP calls
# through the actual routes, never a direct Notification insert, so every
# assertion here proves the real domain-service call site actually creates
# (or correctly withholds) a notification for the real recipient.
# ---------------------------------------------------------------------------

import uuid

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, full_name=None, **extra):
    payload = {"email": email, "password": "Password123", "full_name": full_name or f"Test {role.title()}", "role": role, **extra}
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
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"], "user_id": body["user"]["id"]}


def _register_student(client, db_session, institution_id, email, identifier, full_name=None):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier, full_name=full_name)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id) if institution_id else None
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id, "user_id": body["user"]["id"]}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"], "user_id": body["user"]["id"]}


def _create_admin(db_session, email):
    from app.models.enums import UserRole
    from app.models.user import User
    from app.security.password import hash_password

    admin = User(email=email, password_hash=hash_password("AdminPass123"), full_name="Test Admin", role=UserRole.ADMIN, is_active=True)
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def _admin_token(client, db_session, email):
    _create_admin(db_session, email)
    resp = client.post("/api/auth/login", json={"email": email, "password": "AdminPass123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _set_institution_status(db_session, institution_id, status):
    from app.models.institution import Institution

    inst = db_session.query(Institution).filter(Institution.id == uuid.UUID(institution_id)).first()
    inst.verification_status = status
    db_session.commit()


def _issue(client, institution_token, student_id, **overrides):
    data = {"student_id": student_id, "credential_type": "transcript", "title": "Final Transcript"}
    data.update(overrides)
    files = {"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _job_payload(**overrides):
    payload = {"title": "Software Engineer", "description": "Build things.", "employment_type": "full_time"}
    payload.update(overrides)
    return payload


def _my_notifications(client, token, **params):
    return client.get("/api/notifications/me", params=params, headers=_auth_header(token))


def _unread_count(client, token):
    resp = client.get("/api/notifications/me/unread-count", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _setup(client, db_session, suffix):
    inst = _register_institution(client, db_session, f"notif-inst-{suffix}@test.credchain.dev", f"Notif University {suffix}")
    student = _register_student(client, db_session, inst["institution_id"], f"notif-stu-{suffix}@test.credchain.dev", f"NOTIF-STU-{suffix}")
    verifier = _register_verifier(client, db_session, f"notif-co-{suffix}@test.credchain.dev", f"Notif Corp {suffix}")
    return {"inst": inst, "student": student, "verifier": verifier}


# =====================================================================
# AUTHORIZATION (1-5)
# =====================================================================


def test_unauthenticated_cannot_list_notifications(client, db_session):
    assert client.get("/api/notifications/me").status_code == 401


def test_user_a_cannot_see_user_b_notifications(client, db_session):
    ctx = _setup(client, db_session, "1a")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])  # notifies ctx student only

    other = _register_student(client, db_session, ctx["inst"]["institution_id"], "notif-other-1a@test.credchain.dev", "NOTIF-OTHER-1a")

    mine = _my_notifications(client, ctx["student"]["token"]).json()
    theirs = _my_notifications(client, other["token"]).json()
    assert mine["total"] >= 1
    assert theirs["total"] == 0


def test_user_a_cannot_mark_user_b_notification_read(client, db_session):
    ctx = _setup(client, db_session, "1b")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    notification_id = _my_notifications(client, ctx["student"]["token"]).json()["items"][0]["id"]

    other = _register_student(client, db_session, ctx["inst"]["institution_id"], "notif-other-1b@test.credchain.dev", "NOTIF-OTHER-1b")
    resp = client.post(f"/api/notifications/me/{notification_id}/read", headers=_auth_header(other["token"]))
    assert resp.status_code == 403


def test_admin_notification_not_visible_to_normal_users(client, db_session):
    admin_token = _admin_token(client, db_session, "notif-admin-1c@test.credchain.dev")
    inst = _register_institution(client, db_session, "notif-pending-1c@test.credchain.dev", "Notif Pending Uni 1c")
    _set_institution_status(db_session, inst["institution_id"], "pending")

    # Re-trigger registration's own admin-notify path isn't re-runnable post-hoc; instead confirm
    # the institution's OWN account (a normal, non-admin user) never sees the admin's
    # "awaiting review" notification meant for admins only.
    mine = _my_notifications(client, inst["token"]).json()
    assert all(n["title"] != "New registration awaiting review" for n in mine["items"])
    admin_mine = _my_notifications(client, admin_token).json()
    assert any(n["title"] == "New registration awaiting review" for n in admin_mine["items"])


def test_cross_role_isolation(client, db_session):
    ctx = _setup(client, db_session, "1d")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    # The institution and company involved must not see the student's own credential-issued notification.
    inst_notifs = _my_notifications(client, ctx["inst"]["token"]).json()
    co_notifs = _my_notifications(client, ctx["verifier"]["token"]).json()
    assert all(n["title"] != "Credential issued" for n in inst_notifs["items"])
    assert all(n["title"] != "Credential issued" for n in co_notifs["items"])


# =====================================================================
# LIST (6-9)
# =====================================================================


def test_notifications_newest_first(client, db_session):
    ctx = _setup(client, db_session, "2a")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title="First")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title="Second")

    items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    timestamps = [n["created_at"] for n in items]
    assert timestamps == sorted(timestamps, reverse=True)


def test_notifications_pagination_shape_and_disjoint_pages(client, db_session):
    ctx = _setup(client, db_session, "2b")
    for i in range(3):
        _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title=f"Cred {i}")

    page1 = _my_notifications(client, ctx["student"]["token"], page=1, page_size=2).json()
    assert set(page1.keys()) == {"items", "page", "page_size", "total", "total_pages"}
    assert page1["total"] >= 3
    assert len(page1["items"]) == 2

    page2 = _my_notifications(client, ctx["student"]["token"], page=2, page_size=2).json()
    assert {n["id"] for n in page1["items"]}.isdisjoint({n["id"] for n in page2["items"]})


def test_notifications_empty_list_for_fresh_user(client, db_session):
    student = _register_student(client, db_session, None, "notif-fresh-2c@test.credchain.dev", "NOTIF-FRESH-2c")
    body = _my_notifications(client, student["token"]).json()
    assert body["total"] == 0
    assert body["items"] == []


# =====================================================================
# UNREAD COUNT + READ STATE (10-15)
# =====================================================================


def test_unread_count_correct_and_decreases_on_read(client, db_session):
    ctx = _setup(client, db_session, "3a")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])

    before = _unread_count(client, ctx["student"]["token"])
    assert before >= 1

    notification_id = _my_notifications(client, ctx["student"]["token"]).json()["items"][0]["id"]
    read_resp = client.post(f"/api/notifications/me/{notification_id}/read", headers=_auth_header(ctx["student"]["token"]))
    assert read_resp.status_code == 200, read_resp.text
    assert read_resp.json()["is_read"] is True
    assert read_resp.json()["read_at"] is not None

    after = _unread_count(client, ctx["student"]["token"])
    assert after == before - 1


def test_mark_one_read_twice_is_idempotent(client, db_session):
    ctx = _setup(client, db_session, "3b")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    notification_id = _my_notifications(client, ctx["student"]["token"]).json()["items"][0]["id"]

    first = client.post(f"/api/notifications/me/{notification_id}/read", headers=_auth_header(ctx["student"]["token"]))
    second = client.post(f"/api/notifications/me/{notification_id}/read", headers=_auth_header(ctx["student"]["token"]))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_read"] is True


def test_mark_all_read_zeroes_unread_count_and_scoped_to_caller(client, db_session):
    ctx = _setup(client, db_session, "3c")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title="Second")
    other = _register_student(client, db_session, ctx["inst"]["institution_id"], "notif-other-3c@test.credchain.dev", "NOTIF-OTHER-3c")
    _issue(client, ctx["inst"]["token"], other["student_id"], title="Other's credential")

    resp = client.post("/api/notifications/me/read-all", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] >= 2

    assert _unread_count(client, ctx["student"]["token"]) == 0
    # The other student's own notification is untouched — mark-all never crosses users.
    assert _unread_count(client, other["token"]) >= 1


# =====================================================================
# CREATION — correct recipient per event type (16-24)
# =====================================================================


def test_credential_issued_notifies_the_student(client, db_session):
    ctx = _setup(client, db_session, "4a")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])

    items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    match = next(n for n in items if n["title"] == "Credential issued")
    assert match["link_entity_type"] == "credential"
    assert match["link_entity_id"] == credential["id"]


def test_credential_revoked_notifies_the_student(client, db_session):
    ctx = _setup(client, db_session, "4b")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    revoke = client.post(f"/api/credentials/{credential['id']}/revoke", headers=_auth_header(ctx["inst"]["token"]))
    assert revoke.status_code == 200, revoke.text

    items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    assert any(n["title"] == "Credential revoked" for n in items)


def test_credential_shared_notifies_the_registered_company(client, db_session):
    ctx = _setup(client, db_session, "4c")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    share = client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [credential["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert share.status_code == 201, share.text

    items = _my_notifications(client, ctx["verifier"]["token"]).json()["items"]
    match = next(n for n in items if n["title"] == "Credentials shared with you")
    assert match["link_entity_type"] == "share_grant"


def test_credential_request_notifications_go_to_correct_parties(client, db_session):
    ctx = _setup(client, db_session, "4d")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])

    create = client.post(
        "/api/credential-requests",
        json={"student_id": ctx["student"]["student_id"], "purpose": "Hiring", "requested_credentials": ["Final Transcript"]},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]

    # Student is notified of the new request.
    student_items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    assert any(n["title"] == "New credential request" for n in student_items)

    approve = client.post(
        f"/api/credential-requests/{request_id}/approve",
        json={"credential_ids": [credential["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert approve.status_code == 200, approve.text

    # Company is notified its request was approved.
    company_items = _my_notifications(client, ctx["verifier"]["token"]).json()["items"]
    assert any(n["title"] == "Credential request approved" for n in company_items)


def test_verification_does_not_create_a_notification(client, db_session):
    """Deliberate design decision: repeated verification clicks must never spam the student/institution — see sharing_service/_create_share_grant docstrings and the final report."""
    ctx = _setup(client, db_session, "4e")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [credential["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )
    before = _unread_count(client, ctx["student"]["token"])

    verify = client.post(
        "/api/verification/verify", json={"credential_id": credential["id"]}, headers=_auth_header(ctx["verifier"]["token"])
    )
    assert verify.status_code == 200, verify.text

    after = _unread_count(client, ctx["student"]["token"])
    assert after == before


def test_application_notifications_go_to_correct_parties(client, db_session):
    ctx = _setup(client, db_session, "4f")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    job = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(ctx["verifier"]["token"])).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(ctx["verifier"]["token"]))

    apply_resp = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [credential["id"]]},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert apply_resp.status_code == 201, apply_resp.text
    application_id = apply_resp.json()["id"]

    company_items = _my_notifications(client, ctx["verifier"]["token"]).json()["items"]
    assert any(n["title"] == "New job application" for n in company_items)
    # The system-generated CREDENTIAL_REQUEST_APPROVED/CREDENTIAL_SHARED side effects of applying
    # must NOT also separately notify the company — one applicaton click, one notification.
    assert not any(n["title"] in ("Credential request approved", "Credentials shared with you") for n in company_items)

    status_resp = client.post(
        f"/api/companies/me/applications/{application_id}/status",
        json={"status": "under_review"},
        headers=_auth_header(ctx["verifier"]["token"]),
    )
    assert status_resp.status_code == 200, status_resp.text
    student_items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    assert any(n["title"] == "Application status updated" for n in student_items)


def test_admin_approval_and_rejection_notify_correct_organization(client, db_session):
    admin_token = _admin_token(client, db_session, "notif-admin-4g@test.credchain.dev")
    inst = _register_institution(client, db_session, "notif-approve-4g@test.credchain.dev", "Notif Approve Uni 4g")
    _set_institution_status(db_session, inst["institution_id"], "pending")

    approve = client.post(f"/api/admin/institutions/{inst['institution_id']}/approve", headers=_auth_header(admin_token))
    assert approve.status_code == 200, approve.text

    items = _my_notifications(client, inst["token"]).json()["items"]
    assert any(n["title"] == "Institution approved" for n in items)

    inst2 = _register_institution(client, db_session, "notif-reject-4g@test.credchain.dev", "Notif Reject Uni 4g")
    _set_institution_status(db_session, inst2["institution_id"], "pending")
    reject = client.post(
        f"/api/admin/institutions/{inst2['institution_id']}/reject",
        json={"reason": "Could not verify"},
        headers=_auth_header(admin_token),
    )
    assert reject.status_code == 200, reject.text
    items2 = _my_notifications(client, inst2["token"]).json()["items"]
    assert any(n["title"] == "Institution registration rejected" for n in items2)


def test_certificate_request_notifications_go_to_correct_party(client, db_session):
    ctx = _setup(client, db_session, "4h")
    create = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": ctx["inst"]["institution_id"], "credential_type": "transcript", "reason": "Need it"},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]

    inst_items = _my_notifications(client, ctx["inst"]["token"]).json()["items"]
    assert any(n["title"] == "New certificate request" for n in inst_items)

    approve = client.post(f"/api/institutions/me/certificate-requests/{request_id}/approve", headers=_auth_header(ctx["inst"]["token"]))
    assert approve.status_code == 200, approve.text
    student_items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    assert any(n["title"] == "Certificate request approved" for n in student_items)


def test_student_document_notifications_go_to_correct_party(client, db_session):
    ctx = _setup(client, db_session, "4i")
    upload = client.post(
        "/api/students/me/documents",
        data={"institution_id": ctx["inst"]["institution_id"], "credential_type": "transcript"},
        files={"document": ("t.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    inst_items = _my_notifications(client, ctx["inst"]["token"]).json()["items"]
    assert any(n["title"] == "New document submitted" for n in inst_items)

    reject = client.post(
        f"/api/institutions/me/documents/{document_id}/reject",
        json={"reason": "Illegible scan"},
        headers=_auth_header(ctx["inst"]["token"]),
    )
    assert reject.status_code == 200, reject.text
    student_items = _my_notifications(client, ctx["student"]["token"]).json()["items"]
    assert any(n["title"] == "Document rejected" for n in student_items)


# =====================================================================
# ISOLATION / SECURITY (25-27)
# =====================================================================


def test_unrelated_user_cannot_see_anothers_notification(client, db_session):
    ctx = _setup(client, db_session, "5a")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    unrelated = _register_verifier(client, db_session, "notif-unrelated-5a@test.credchain.dev", "Unrelated Co 5a")
    assert _my_notifications(client, unrelated["token"]).json()["total"] == 0


def test_directory_only_institution_receives_no_notification(client, db_session):
    """A directory-only institution (never registered) has no logged-in user — a certificate request to it must not error and must not create a notification nobody can ever read."""
    from app.models.institution import Institution

    directory_institution = Institution(user_id=None, name="Directory Only Uni Notif")
    db_session.add(directory_institution)
    db_session.commit()

    student = _register_student(client, db_session, str(directory_institution.id), "notif-dir-5b@test.credchain.dev", "NOTIF-DIR-5b")
    resp = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": str(directory_institution.id), "credential_type": "transcript", "reason": "Need it"},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    # No error, and — since the institution has no user — nothing was created for anyone to leak to.
    from app.models.notification import Notification

    assert db_session.query(Notification).filter(Notification.link_entity_id == uuid.UUID(resp.json()["id"])).count() == 0


def test_no_notification_contains_secret_material(client, db_session):
    ctx = _setup(client, db_session, "5c")
    _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"], title="Second Cred")
    client.post(
        "/api/students/me/shares",
        json={"company_id": ctx["verifier"]["company_id"], "credential_ids": [credential["id"]], "expires_in_days": 7},
        headers=_auth_header(ctx["student"]["token"]),
    )

    resp = _my_notifications(client, ctx["student"]["token"])
    raw_text = resp.text
    assert "PRIVATE KEY" not in raw_text
    assert "share_token" not in raw_text
    assert "password" not in raw_text.lower()
    assert "signature" not in raw_text.lower()


# =====================================================================
# EVENT / ACTIVITY FEED (28-32)
# =====================================================================


def test_application_events_appear_in_student_activity(client, db_session):
    ctx = _setup(client, db_session, "6a")
    credential = _issue(client, ctx["inst"]["token"], ctx["student"]["student_id"])
    job = client.post("/api/companies/me/jobs", json=_job_payload(), headers=_auth_header(ctx["verifier"]["token"])).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(ctx["verifier"]["token"]))
    client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [credential["id"]]},
        headers=_auth_header(ctx["student"]["token"]),
    )

    activity = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    assert any(a["action"] == "APPLICATION_SUBMITTED" for a in activity)
    match = next(a for a in activity if a["action"] == "APPLICATION_SUBMITTED")
    assert match["message"] != "Activity recorded"


def test_admin_institution_decision_appears_in_institution_activity(client, db_session):
    admin_token = _admin_token(client, db_session, "notif-admin-6b@test.credchain.dev")
    inst = _register_institution(client, db_session, "notif-activity-6b@test.credchain.dev", "Notif Activity Uni 6b")
    _set_institution_status(db_session, inst["institution_id"], "pending")
    client.post(f"/api/admin/institutions/{inst['institution_id']}/approve", headers=_auth_header(admin_token))

    activity = client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json()
    assert any(a["action"] == "ADMIN_APPROVED_INSTITUTION" for a in activity)
    match = next(a for a in activity if a["action"] == "ADMIN_APPROVED_INSTITUTION")
    assert "approved" in match["message"].lower()


def test_new_certificate_request_activity_exists_for_both_parties(client, db_session):
    ctx = _setup(client, db_session, "6c")
    resp = client.post(
        "/api/students/me/certificate-requests",
        json={"institution_id": ctx["inst"]["institution_id"], "credential_type": "transcript", "reason": "Need it"},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert resp.status_code == 201, resp.text

    student_activity = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    inst_activity = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"])).json()
    assert any(a["action"] == "CERTIFICATE_REQUEST_CREATED" for a in student_activity)
    assert any(a["action"] == "CERTIFICATE_REQUEST_CREATED" for a in inst_activity)


def test_student_document_activity_exists_for_both_parties(client, db_session):
    ctx = _setup(client, db_session, "6d")
    upload = client.post(
        "/api/students/me/documents",
        data={"institution_id": ctx["inst"]["institution_id"], "credential_type": "transcript"},
        files={"document": ("t.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(ctx["student"]["token"]),
    )
    assert upload.status_code == 201, upload.text

    student_activity = client.get("/api/students/me/activity", headers=_auth_header(ctx["student"]["token"])).json()
    inst_activity = client.get("/api/institutions/me/activity", headers=_auth_header(ctx["inst"]["token"])).json()
    assert any(a["action"] == "STUDENT_DOCUMENT_SUBMITTED" for a in student_activity)
    assert any(a["action"] == "STUDENT_DOCUMENT_SUBMITTED" for a in inst_activity)


def test_application_and_admin_messages_are_human_readable(client, db_session):
    """Neither APPLICATION_* nor ADMIN_* action codes should ever fall back to the bare 'Activity recorded' generic label anymore."""
    admin_token = _admin_token(client, db_session, "notif-admin-6e@test.credchain.dev")
    inst = _register_institution(client, db_session, "notif-readable-6e@test.credchain.dev", "Notif Readable Uni 6e")
    _set_institution_status(db_session, inst["institution_id"], "pending")
    client.post(f"/api/admin/institutions/{inst['institution_id']}/approve", headers=_auth_header(admin_token))

    activity = client.get("/api/institutions/me/activity", headers=_auth_header(inst["token"])).json()
    match = next(a for a in activity if a["action"] == "ADMIN_APPROVED_INSTITUTION")
    assert match["message"] != "Activity recorded"
    assert len(match["message"]) > len("Activity recorded")
