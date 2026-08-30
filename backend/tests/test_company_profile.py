# ---------------------------------------------------------------------------
# Job marketplace Phase A: real company profiles. A student must only ever
# see genuine Company rows — these tests exist to prove the profile
# endpoints are real, ownership-scoped, and never fabricate anything.
# ---------------------------------------------------------------------------

def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Profile Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def test_company_can_view_and_update_own_profile(client, db_session):
    verifier = _register_verifier(client, db_session, "profile-co-1@test.credchain.dev", "Profile Co 1")

    me_resp = client.get("/api/companies/me", headers=_auth_header(verifier["token"]))
    assert me_resp.status_code == 200
    assert me_resp.json()["name"] == "Profile Co 1"
    assert me_resp.json()["description"] is None

    update_resp = client.patch(
        "/api/companies/me",
        json={"description": "We build real things.", "location": "Bengaluru", "company_size": "51-200", "industry": "Software"},
        headers=_auth_header(verifier["token"]),
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["description"] == "We build real things."
    assert body["location"] == "Bengaluru"
    assert body["company_size"] == "51-200"
    assert body["industry"] == "Software"


def test_student_sees_real_company_list_and_detail_no_fabrication(client, db_session):
    verifier = _register_verifier(client, db_session, "profile-co-2@test.credchain.dev", "Profile Co 2")
    client.patch("/api/companies/me", json={"description": "Real description"}, headers=_auth_header(verifier["token"]))

    list_resp = client.get("/api/companies")
    assert list_resp.status_code == 200
    names = [c["name"] for c in list_resp.json()]
    assert "Profile Co 2" in names
    assert "ABC Technologies" not in names

    detail_resp = client.get(f"/api/companies/{verifier['company_id']}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["description"] == "Real description"


def test_company_cannot_update_another_companys_profile(client, db_session):
    verifier_a = _register_verifier(client, db_session, "profile-co-a@test.credchain.dev", "Profile Co A")
    verifier_b = _register_verifier(client, db_session, "profile-co-b@test.credchain.dev", "Profile Co B")

    client.patch("/api/companies/me", json={"description": "Company A's real description"}, headers=_auth_header(verifier_a["token"]))
    # Company B updates its OWN profile — never A's, since there's no route that accepts a target company_id for writes.
    client.patch("/api/companies/me", json={"description": "Company B's description"}, headers=_auth_header(verifier_b["token"]))

    a_profile = client.get(f"/api/companies/{verifier_a['company_id']}").json()
    assert a_profile["description"] == "Company A's real description"


def test_nonexistent_company_returns_404(client, db_session):
    import uuid

    resp = client.get(f"/api/companies/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_student_cannot_update_company_profile(client, db_session):
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "profile-stu-1@test.credchain.dev",
            "password": "Password123",
            "full_name": "Profile Student",
            "role": "student",
            "student_identifier": "PROFILE-STU-1",
        },
    )
    token = reg.json()["access_token"]
    resp = client.patch("/api/companies/me", json={"description": "hijack"}, headers=_auth_header(token))
    assert resp.status_code == 403
