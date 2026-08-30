# ---------------------------------------------------------------------------
# PS3 Phase B: bulk credential issuance. Each student gets their OWN
# document and their own fully-independent credential (own id, identifier,
# signature, document hash) — these tests exist specifically to prove the
# batch is never treated as all-or-nothing and never silently reuses one
# student's PDF for another.
# ---------------------------------------------------------------------------

import hashlib
import uuid

SAMPLE_PDF_A = b"%PDF-1.4\n%bulk-a\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
SAMPLE_PDF_B = b"%PDF-1.4\n%bulk-b\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
SAMPLE_PDF_C = b"%PDF-1.4\n%bulk-c\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email="bulk-inst@test.credchain.dev", name="Bulk University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "Bulk Inst Admin",
            "role": "institution",
            "institution_id": str(institution.id),
        },
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
            "full_name": f"Student {identifier}",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]["student_id"]


def _bulk_issue(client, token, student_ids, documents, **overrides):
    data = {
        "student_ids": student_ids,
        "credential_type": "certification",
        "title": "Bulk Workshop Certificate",
    }
    data.update(overrides)
    files = [("documents", (fname, content, "application/pdf")) for fname, content in documents]
    return client.post("/api/institutions/me/credentials/bulk", data=data, files=files, headers=_auth_header(token))


def test_bulk_issuance_all_succeed_each_credential_independent(client, db_session):
    inst = _register_institution(client, db_session)
    s1 = _register_student(client, inst["institution_id"], "bulk-s1@test.credchain.dev", "BULK-S1")
    s2 = _register_student(client, inst["institution_id"], "bulk-s2@test.credchain.dev", "BULK-S2")

    resp = _bulk_issue(
        client,
        inst["token"],
        [s1, s2],
        [("a.pdf", SAMPLE_PDF_A), ("b.pdf", SAMPLE_PDF_B)],
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) == 2
    assert all(r["status"] == "issued" for r in results)

    # different documents -> different hashes -> different signatures/ids
    assert results[0]["credential_id"] != results[1]["credential_id"]

    cred_a = client.get(f"/api/credentials/{results[0]['credential_id']}", headers=_auth_header(inst["token"])).json()
    cred_b = client.get(f"/api/credentials/{results[1]['credential_id']}", headers=_auth_header(inst["token"])).json()
    assert cred_a["credential_identifier"] != cred_b["credential_identifier"]
    assert cred_a["signature"] != cred_b["signature"]
    assert cred_a["document_hash"] == hashlib.sha256(SAMPLE_PDF_A).hexdigest()
    assert cred_b["document_hash"] == hashlib.sha256(SAMPLE_PDF_B).hexdigest()
    assert cred_a["student_id"] != cred_b["student_id"]


def test_bulk_issuance_partial_failure_does_not_abort_batch(client, db_session):
    inst_a = _register_institution(client, db_session, email="bulk-inst-a@test.credchain.dev", name="Bulk University A")
    inst_b = _register_institution(client, db_session, email="bulk-inst-b@test.credchain.dev", name="Bulk University B")
    good_student = _register_student(client, inst_a["institution_id"], "bulk-good@test.credchain.dev", "BULK-GOOD")
    # This student belongs to institution B, not A — issuing to them from A must fail for THIS item only.
    other_students_student = _register_student(client, inst_b["institution_id"], "bulk-wrong@test.credchain.dev", "BULK-WRONG")

    resp = _bulk_issue(
        client,
        inst_a["token"],
        [good_student, other_students_student],
        [("good.pdf", SAMPLE_PDF_A), ("wrong.pdf", SAMPLE_PDF_B)],
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert results[0]["status"] == "issued"
    assert results[0]["credential_id"] is not None
    assert results[1]["status"] == "failed"
    assert results[1]["credential_id"] is None
    assert "not affiliated" in results[1]["error"].lower()

    # the good student's credential really exists and is fetchable
    get_resp = client.get(f"/api/credentials/{results[0]['credential_id']}", headers=_auth_header(inst_a["token"]))
    assert get_resp.status_code == 200


def test_bulk_issuance_bad_document_reported_per_item(client, db_session):
    inst = _register_institution(client, db_session, email="bulk-inst-baddoc@test.credchain.dev", name="Bulk Baddoc University")
    s1 = _register_student(client, inst["institution_id"], "bulk-baddoc-1@test.credchain.dev", "BULK-BADDOC-1")
    s2 = _register_student(client, inst["institution_id"], "bulk-baddoc-2@test.credchain.dev", "BULK-BADDOC-2")

    resp = _bulk_issue(
        client,
        inst["token"],
        [s1, s2],
        [("good.pdf", SAMPLE_PDF_A), ("not-a-pdf.pdf", b"not a pdf at all")],
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert results[0]["status"] == "issued"
    assert results[1]["status"] == "failed"
    assert results[1]["credential_id"] is None


def test_bulk_issuance_requires_matching_student_and_document_counts(client, db_session):
    inst = _register_institution(client, db_session, email="bulk-inst-mismatch@test.credchain.dev", name="Bulk Mismatch University")
    s1 = _register_student(client, inst["institution_id"], "bulk-mismatch-1@test.credchain.dev", "BULK-MISMATCH-1")

    resp = _bulk_issue(client, inst["token"], [s1], [("a.pdf", SAMPLE_PDF_A), ("b.pdf", SAMPLE_PDF_B)])
    assert resp.status_code == 422


def test_bulk_issuance_requires_institution_role(client, db_session):
    inst = _register_institution(client, db_session, email="bulk-inst-role@test.credchain.dev", name="Bulk Role University")
    s1 = _register_student(client, inst["institution_id"], "bulk-role-1@test.credchain.dev", "BULK-ROLE-1")

    student_login = client.post(
        "/api/auth/login", json={"email": "bulk-role-1@test.credchain.dev", "password": "Password123"}
    ).json()
    resp = _bulk_issue(client, student_login["access_token"], [s1], [("a.pdf", SAMPLE_PDF_A)])
    assert resp.status_code == 403


def test_bulk_issuance_empty_student_list_rejected(client, db_session):
    inst = _register_institution(client, db_session, email="bulk-inst-empty@test.credchain.dev", name="Bulk Empty University")
    resp = client.post(
        "/api/institutions/me/credentials/bulk",
        data={"credential_type": "certification", "title": "Nothing"},
        files=[],
        headers=_auth_header(inst["token"]),
    )
    assert resp.status_code == 422
