# ---------------------------------------------------------------------------
# Phase A: student can request MULTIPLE documents from their institution in
# one submission. Reuses the existing single-item InstitutionCertificateRequest
# lifecycle unchanged — each requested document type is its own row with its
# own independent PENDING/APPROVED/REJECTED/FULFILLED state; a new nullable
# batch_id column just groups the rows created together so they render as
# "one request with several items." Approving/rejecting/fulfilling one item
# never affects the others in the same batch.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%batch\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


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
        json={"email": email, "password": "Password123", "full_name": "Batch Inst Admin", "role": "institution", "institution_id": str(institution.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": f"Batch Student {identifier}",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return {"token": resp.json()["access_token"], "student_id": resp.json()["user"]["student_id"]}


def _issue(client, inst_token, student_id, credential_type, title, fulfills_request_id=None):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    data = {"student_id": student_id, "credential_type": credential_type, "title": title}
    if fulfills_request_id:
        data["fulfills_request_id"] = fulfills_request_id
    resp = client.post("/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(inst_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_single_document_batch_request(client, db_session):
    inst = _register_institution(client, db_session, "batch-inst-1@test.credchain.dev", "Batch University 1")
    student = _register_student(client, inst["institution_id"], "batch-stu-1@test.credchain.dev", "BATCH-STU-1")

    resp = client.post(
        "/api/students/me/certificate-requests/batch",
        json={"institution_id": inst["institution_id"], "items": [{"credential_type": "transcript"}], "reason": "Job application"},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["credential_type"] == "transcript"
    assert items[0]["status"] == "pending"
    assert items[0]["batch_id"] is not None


def test_three_document_batch_request_shares_one_batch_id(client, db_session):
    inst = _register_institution(client, db_session, "batch-inst-2@test.credchain.dev", "Batch University 2")
    student = _register_student(client, inst["institution_id"], "batch-stu-2@test.credchain.dev", "BATCH-STU-2")

    resp = client.post(
        "/api/students/me/certificate-requests/batch",
        json={
            "institution_id": inst["institution_id"],
            "items": [{"credential_type": "transcript"}, {"credential_type": "degree"}, {"credential_type": "migration"}],
            "reason": "Higher studies abroad",
        },
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    items = resp.json()
    assert len(items) == 3
    batch_ids = {item["batch_id"] for item in items}
    assert len(batch_ids) == 1  # all three share the same batch_id
    types = {item["credential_type"] for item in items}
    assert types == {"transcript", "degree", "migration"}

    # Student sees all three when listing.
    list_resp = client.get("/api/students/me/certificate-requests", headers=_auth_header(student["token"]))
    assert len(list_resp.json()) == 3

    # Institution sees all three too.
    inst_list = client.get("/api/institutions/me/certificate-requests", headers=_auth_header(inst["token"]))
    assert len(inst_list.json()) == 3


def test_mixed_fulfilled_unfulfilled_state_within_one_batch(client, db_session):
    inst = _register_institution(client, db_session, "batch-inst-3@test.credchain.dev", "Batch University 3")
    student = _register_student(client, inst["institution_id"], "batch-stu-3@test.credchain.dev", "BATCH-STU-3")

    items = client.post(
        "/api/students/me/certificate-requests/batch",
        json={
            "institution_id": inst["institution_id"],
            "items": [{"credential_type": "transcript"}, {"credential_type": "degree"}, {"credential_type": "migration"}],
        },
        headers=_auth_header(student["token"]),
    ).json()

    transcript_req = next(i for i in items if i["credential_type"] == "transcript")
    degree_req = next(i for i in items if i["credential_type"] == "degree")
    migration_req = next(i for i in items if i["credential_type"] == "migration")

    # Approve and fulfill only the transcript item.
    client.post(f"/api/institutions/me/certificate-requests/{transcript_req['id']}/approve", headers=_auth_header(inst["token"]))
    _issue(client, inst["token"], student["student_id"], "transcript", "Transcript", fulfills_request_id=transcript_req["id"])

    # Approve the degree item but don't issue yet — approval alone must not fulfill it.
    client.post(f"/api/institutions/me/certificate-requests/{degree_req['id']}/approve", headers=_auth_header(inst["token"]))

    # Leave migration untouched (still pending).

    list_resp = client.get("/api/students/me/certificate-requests", headers=_auth_header(student["token"])).json()
    by_type = {r["credential_type"]: r for r in list_resp}
    assert by_type["transcript"]["status"] == "fulfilled"
    assert by_type["transcript"]["fulfilled_credential_id"] is not None
    assert by_type["degree"]["status"] == "approved"  # NOT fulfilled — issuance never happened
    assert by_type["degree"]["fulfilled_credential_id"] is None
    assert by_type["migration"]["status"] == "pending"


def test_rejecting_one_item_in_a_batch_does_not_affect_others(client, db_session):
    inst = _register_institution(client, db_session, "batch-inst-4@test.credchain.dev", "Batch University 4")
    student = _register_student(client, inst["institution_id"], "batch-stu-4@test.credchain.dev", "BATCH-STU-4")

    items = client.post(
        "/api/students/me/certificate-requests/batch",
        json={
            "institution_id": inst["institution_id"],
            "items": [{"credential_type": "transcript"}, {"credential_type": "migration"}],
        },
        headers=_auth_header(student["token"]),
    ).json()
    transcript_req = next(i for i in items if i["credential_type"] == "transcript")
    migration_req = next(i for i in items if i["credential_type"] == "migration")

    reject_resp = client.post(
        f"/api/institutions/me/certificate-requests/{migration_req['id']}/reject",
        json={"reason": "Migration certificate not applicable — student has not transferred."},
        headers=_auth_header(inst["token"]),
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"
    assert reject_resp.json()["rejection_reason"] == "Migration certificate not applicable — student has not transferred."

    list_resp = client.get("/api/students/me/certificate-requests", headers=_auth_header(student["token"])).json()
    by_type = {r["credential_type"]: r for r in list_resp}
    assert by_type["migration"]["status"] == "rejected"
    assert by_type["transcript"]["status"] == "pending"  # untouched by the sibling's rejection


def test_batch_request_requires_at_least_one_item(client, db_session):
    inst = _register_institution(client, db_session, "batch-inst-5@test.credchain.dev", "Batch University 5")
    student = _register_student(client, inst["institution_id"], "batch-stu-5@test.credchain.dev", "BATCH-STU-5")

    resp = client.post(
        "/api/students/me/certificate-requests/batch",
        json={"institution_id": inst["institution_id"], "items": []},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 422


def test_batch_request_cross_institution_isolation(client, db_session):
    inst_a = _register_institution(client, db_session, "batch-inst-6a@test.credchain.dev", "Batch University 6A")
    inst_b = _register_institution(client, db_session, "batch-inst-6b@test.credchain.dev", "Batch University 6B")
    student_a = _register_student(client, inst_a["institution_id"], "batch-stu-6a@test.credchain.dev", "BATCH-STU-6A")

    # Student A cannot batch-request from institution B (not affiliated).
    resp = client.post(
        "/api/students/me/certificate-requests/batch",
        json={"institution_id": inst_b["institution_id"], "items": [{"credential_type": "transcript"}]},
        headers=_auth_header(student_a["token"]),
    )
    assert resp.status_code == 403

    # A legitimate batch request to A must never be visible to institution B.
    client.post(
        "/api/students/me/certificate-requests/batch",
        json={"institution_id": inst_a["institution_id"], "items": [{"credential_type": "transcript"}]},
        headers=_auth_header(student_a["token"]),
    )
    inst_b_list = client.get("/api/institutions/me/certificate-requests", headers=_auth_header(inst_b["token"])).json()
    assert inst_b_list == []
