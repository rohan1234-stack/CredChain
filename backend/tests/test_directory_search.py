# ---------------------------------------------------------------------------
# Institution/Company/Job discovery directory (Phase 1 job-discovery work).
#
# Covers: directory-only rows (user_id=None, as scripts/seed_directory.py
# creates them) show up in the same public listings as real registered
# institutions/companies with no special-casing; search/location/industry/
# degree/company_id filters actually narrow results server-side; a
# nonexistent institution 404s; open_positions_count on a company reflects
# real OPEN jobs only (never draft/closed).
# ---------------------------------------------------------------------------

import uuid

from app.models.company import Company
from app.models.institution import Institution


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_verifier(client, db_session, email, name):
    company = _directory_company(db_session, name)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Dir Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _register_student(client, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Dir Student", "role": "student", "student_identifier": identifier},
    )
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _job_payload(**overrides):
    payload = {
        "title": "Software Engineer",
        "description": "Build real things.",
        "employment_type": "full_time",
        "required_degree": "B.Tech Computer Science",
        "minimum_cgpa": 7.5,
        "graduation_year_requirement": 2026,
        "required_skills": [],
        "required_documents": [],
    }
    payload.update(overrides)
    return payload


def _directory_institution(db_session, name: str, location: str | None = None, institution_type: str | None = None) -> Institution:
    """Mirrors what scripts/seed_directory.py inserts: a real row, no login (user_id=None)."""
    inst = Institution(user_id=None, name=name, location=location, institution_type=institution_type)
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


def _directory_company(db_session, name: str, industry: str | None = None, location: str | None = None) -> Company:
    comp = Company(user_id=None, name=name, industry=industry, location=location)
    db_session.add(comp)
    db_session.commit()
    db_session.refresh(comp)
    return comp


# ---- Institutions -----------------------------------------------------------


def test_directory_only_institution_is_publicly_listed_and_never_a_login_account(client, db_session):
    inst = _directory_institution(db_session, "Directory Only University", location="Nowhere City, Testland")

    list_resp = client.get("/api/institutions")
    assert list_resp.status_code == 200
    body = list_resp.json()
    names = [i["name"] for i in body["items"]]
    assert "Directory Only University" in names
    assert body["total"] >= 1
    assert body["page"] == 1

    detail_resp = client.get(f"/api/institutions/{inst.id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["location"] == "Nowhere City, Testland"
    assert detail_resp.json()["is_registered"] is False


def test_institution_search_matches_name_and_location_case_insensitively(client, db_session):
    _directory_institution(db_session, "Zeta Institute of Technology", location="Springfield, Testland")
    _directory_institution(db_session, "Unrelated College", location="Elsewhere, Testland")

    by_name = client.get("/api/institutions", params={"search": "zeta"})
    assert by_name.status_code == 200
    names = [i["name"] for i in by_name.json()["items"]]
    assert "Zeta Institute of Technology" in names
    assert "Unrelated College" not in names

    by_location = client.get("/api/institutions", params={"search": "Springfield"})
    names = [i["name"] for i in by_location.json()["items"]]
    assert "Zeta Institute of Technology" in names
    assert "Unrelated College" not in names


def test_institution_search_with_no_match_returns_empty_page_not_error(client, db_session):
    resp = client.get("/api/institutions", params={"search": "Definitely Not A Real Institution Name XYZ"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_nonexistent_institution_returns_404(client, db_session):
    resp = client.get(f"/api/institutions/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_institution_country_and_type_filters_are_exact_match(client, db_session):
    a = _directory_institution(db_session, "Filter Type Uni A", institution_type="Public University")
    b = _directory_institution(db_session, "Filter Type College B", institution_type="Private College")
    a.country = "India"
    b.country = "United States"
    db_session.commit()

    by_type = client.get("/api/institutions", params={"institution_type": "Public University"}).json()
    names = [i["name"] for i in by_type["items"]]
    assert "Filter Type Uni A" in names
    assert "Filter Type College B" not in names

    by_country = client.get("/api/institutions", params={"country": "India"}).json()
    names = [i["name"] for i in by_country["items"]]
    assert "Filter Type Uni A" in names
    assert "Filter Type College B" not in names


def test_institution_country_filter_still_matches_legacy_rows_with_no_structured_country(client, db_session):
    """
    Regression test: Phase 1's manually curated institutions (and any future row created before
    an import populates the structured `country` column) only ever have a combined `location`
    string like "Mumbai, Maharashtra, India" — `country` itself is NULL. Filtering by country must
    still find them via `location`, or every one of those institutions would silently vanish from
    country-filtered results the moment this column was introduced.
    """
    legacy = _directory_institution(db_session, "Legacy Location Only University", location="Chennai, Tamil Nadu, India")
    assert legacy.country is None  # exactly the Phase 1 shape — no structured country populated

    resp = client.get("/api/institutions", params={"country": "India"})
    assert resp.status_code == 200
    names = [i["name"] for i in resp.json()["items"]]
    assert "Legacy Location Only University" in names


def test_institution_region_filter_is_substring_match(client, db_session):
    inst = _directory_institution(db_session, "Filter Region Uni")
    inst.region = "Maharashtra"
    db_session.commit()

    resp = client.get("/api/institutions", params={"region": "Mahar"}).json()
    names = [i["name"] for i in resp["items"]]
    assert "Filter Region Uni" in names


def test_institution_pagination_deterministic_and_total_accurate(client, db_session):
    for i in range(5):
        _directory_institution(db_session, f"Pagination Test Uni {i}", institution_type="PaginationTestType")

    page1 = client.get("/api/institutions", params={"institution_type": "PaginationTestType", "page": 1, "page_size": 2}).json()
    page2 = client.get("/api/institutions", params={"institution_type": "PaginationTestType", "page": 2, "page_size": 2}).json()
    assert page1["total"] == 5
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert {i["name"] for i in page1["items"]}.isdisjoint({i["name"] for i in page2["items"]})


# ---- Companies ----------------------------------------------------------------


def test_directory_only_company_is_publicly_listed_alongside_registered_companies(client, db_session):
    _directory_company(db_session, "Directory Only Corp", industry="Testing", location="Test City")
    verifier = _register_verifier(client, db_session, "dir-search-co@test.credchain.dev", "Registered Search Co")

    resp = client.get("/api/companies")
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = [c["name"] for c in items]
    assert "Directory Only Corp" in names
    assert "Registered Search Co" in names
    assert verifier["company_id"] is not None
    directory_row = next(c for c in items if c["name"] == "Directory Only Corp")
    registered_row = next(c for c in items if c["name"] == "Registered Search Co")
    assert directory_row["is_registered"] is False
    assert registered_row["is_registered"] is True


def test_company_search_industry_and_location_filters(client, db_session):
    _directory_company(db_session, "Filter Target Robotics", industry="Robotics", location="Pune, Maharashtra, India")
    _directory_company(db_session, "Filter Other Bank", industry="Banking", location="Mumbai, Maharashtra, India")

    by_search = client.get("/api/companies", params={"search": "Robotics"})
    names = [c["name"] for c in by_search.json()["items"]]
    assert "Filter Target Robotics" in names
    assert "Filter Other Bank" not in names

    by_industry = client.get("/api/companies", params={"industry": "Robotics"})
    names = [c["name"] for c in by_industry.json()["items"]]
    assert "Filter Target Robotics" in names
    assert "Filter Other Bank" not in names

    by_location = client.get("/api/companies", params={"location": "Pune"})
    names = [c["name"] for c in by_location.json()["items"]]
    assert "Filter Target Robotics" in names
    assert "Filter Other Bank" not in names


def test_company_country_filter_is_exact_match(client, db_session):
    india = _directory_company(db_session, "Filter Country India Co", location="Mumbai, India")
    usa = _directory_company(db_session, "Filter Country USA Co", location="New York, USA")
    india.country = "India"
    usa.country = "United States"
    db_session.commit()

    resp = client.get("/api/companies", params={"country": "India"})
    names = [c["name"] for c in resp.json()["items"]]
    assert "Filter Country India Co" in names
    assert "Filter Country USA Co" not in names


def test_company_open_positions_count_reflects_only_open_jobs(client, db_session):
    verifier = _register_verifier(client, db_session, "dir-openjobs@test.credchain.dev", "Open Jobs Co")

    draft = client.post("/api/companies/me/jobs", json=_job_payload(title="Draft Role"), headers=_auth_header(verifier["token"])).json()
    open_job = client.post("/api/companies/me/jobs", json=_job_payload(title="Open Role"), headers=_auth_header(verifier["token"])).json()
    client.post(f"/api/companies/me/jobs/{open_job['id']}/publish", headers=_auth_header(verifier["token"]))

    detail = client.get(f"/api/companies/{verifier['company_id']}")
    assert detail.status_code == 200
    assert detail.json()["open_positions_count"] == 1  # only open_job is published; draft stays draft
    assert detail.json()["is_registered"] is True

    listing = client.get("/api/companies", params={"search": "Open Jobs Co"}).json()
    assert listing["items"][0]["open_positions_count"] == 1
    assert draft["status"] == "draft"


def test_company_pagination_page_size_and_total(client, db_session):
    for i in range(5):
        _directory_company(db_session, f"Pagination Test Co {i}", industry="PaginationTestIndustry")

    page1 = client.get("/api/companies", params={"industry": "PaginationTestIndustry", "page": 1, "page_size": 2}).json()
    assert len(page1["items"]) == 2
    assert page1["total"] == 5
    assert page1["total_pages"] == 3
    assert page1["page"] == 1

    page2 = client.get("/api/companies", params={"industry": "PaginationTestIndustry", "page": 2, "page_size": 2}).json()
    assert len(page2["items"]) == 2
    page1_names = {c["name"] for c in page1["items"]}
    page2_names = {c["name"] for c in page2["items"]}
    assert page1_names.isdisjoint(page2_names)  # different rows per page, deterministic ordering

    page3 = client.get("/api/companies", params={"industry": "PaginationTestIndustry", "page": 3, "page_size": 2}).json()
    assert len(page3["items"]) == 1


def test_company_page_size_is_capped_at_max(client, db_session):
    resp = client.get("/api/companies", params={"page_size": 99999})
    assert resp.status_code == 422  # FastAPI's own Query(le=MAX_PAGE_SIZE) validation rejects it


# ---- Jobs -----------------------------------------------------------------------


def test_job_company_id_search_and_degree_filters(client, db_session):
    verifier_a = _register_verifier(client, db_session, "dir-job-co-a@test.credchain.dev", "Job Filter Co A")
    verifier_b = _register_verifier(client, db_session, "dir-job-co-b@test.credchain.dev", "Job Filter Co B")
    student = _register_student(client, "dir-job-student@test.credchain.dev", "DIR-JOB-STU-1")

    job_a = client.post(
        "/api/companies/me/jobs",
        json=_job_payload(title="Backend Engineer", required_degree="B.Tech Computer Science"),
        headers=_auth_header(verifier_a["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job_a['id']}/publish", headers=_auth_header(verifier_a["token"]))

    job_b = client.post(
        "/api/companies/me/jobs",
        json=_job_payload(title="Mechanical Design Engineer", required_degree="B.Tech Mechanical Engineering"),
        headers=_auth_header(verifier_b["token"]),
    ).json()
    client.post(f"/api/companies/me/jobs/{job_b['id']}/publish", headers=_auth_header(verifier_b["token"]))

    by_company = client.get("/api/jobs", params={"company_id": verifier_a["company_id"]}, headers=_auth_header(student["token"]))
    assert by_company.status_code == 200
    titles = [j["title"] for j in by_company.json()["items"]]
    assert "Backend Engineer" in titles
    assert "Mechanical Design Engineer" not in titles

    by_search = client.get("/api/jobs", params={"search": "Backend"}, headers=_auth_header(student["token"]))
    titles = [j["title"] for j in by_search.json()["items"]]
    assert "Backend Engineer" in titles
    assert "Mechanical Design Engineer" not in titles

    # The student Jobs page has always let a student search by company name too (client-side,
    # pre-existing) — the backend `search` filter has to match that behavior now that Jobs.tsx
    # routes its search box through this endpoint instead of filtering an already-fetched array.
    by_company_name = client.get("/api/jobs", params={"search": "Job Filter Co B"}, headers=_auth_header(student["token"]))
    titles = [j["title"] for j in by_company_name.json()["items"]]
    assert "Mechanical Design Engineer" in titles
    assert "Backend Engineer" not in titles

    by_degree = client.get("/api/jobs", params={"degree": "Mechanical"}, headers=_auth_header(student["token"]))
    titles = [j["title"] for j in by_degree.json()["items"]]
    assert "Mechanical Design Engineer" in titles
    assert "Backend Engineer" not in titles


# ---------------------------------------------------------------------------
# Prefix-first ranking (organization-picker UX improvement): a name that
# STARTS WITH the search term ranks ahead of one that only contains it
# elsewhere. Substring matches still appear, just after every prefix match.
# ---------------------------------------------------------------------------


def test_company_search_prefix_match_ranks_before_substring_match(client, db_session):
    # industry is a scoping filter (AND'd with search) so this test's ordering assertion can
    # never be perturbed by unrelated companies elsewhere in the shared test database.
    _directory_company(db_session, "Global Infrastructure Partners", industry="PrefixRankTestIndustry")
    _directory_company(db_session, "Infosys", industry="PrefixRankTestIndustry")

    resp = client.get("/api/companies", params={"search": "Inf", "industry": "PrefixRankTestIndustry"})
    names = [c["name"] for c in resp.json()["items"]]
    assert names == ["Infosys", "Global Infrastructure Partners"]


def test_company_search_prefix_matches_sorted_alphabetically(client, db_session):
    _directory_company(db_session, "Infosys", industry="PrefixAlphaTestIndustry")
    _directory_company(db_session, "Infineon", industry="PrefixAlphaTestIndustry")

    resp = client.get("/api/companies", params={"search": "Inf", "industry": "PrefixAlphaTestIndustry"})
    names = [c["name"] for c in resp.json()["items"]]
    assert names == ["Infineon", "Infosys"]


def test_company_search_prefix_ranking_is_case_insensitive(client, db_session):
    _directory_company(db_session, "Global Infrastructure Partners", industry="PrefixCaseTestIndustry")
    _directory_company(db_session, "infosys", industry="PrefixCaseTestIndustry")

    resp = client.get("/api/companies", params={"search": "INF", "industry": "PrefixCaseTestIndustry"})
    names = [c["name"] for c in resp.json()["items"]]
    assert names == ["infosys", "Global Infrastructure Partners"]


def test_company_search_still_returns_pure_substring_matches(client, db_session):
    _directory_company(db_session, "Tech Mahindra", industry="SubstringTestIndustry")
    _directory_company(db_session, "Global Technology Partners", industry="SubstringTestIndustry")

    resp = client.get("/api/companies", params={"search": "tech", "industry": "SubstringTestIndustry"})
    names = [c["name"] for c in resp.json()["items"]]
    assert names == ["Tech Mahindra", "Global Technology Partners"]


def test_same_name_companies_remain_distinct_by_id_in_search_results(client, db_session):
    directory_apple = _directory_company(db_session, "Apple", industry="SameNameTestIndustry")
    verifier = _register_verifier(client, db_session, "apple-search-test@test.credchain.dev", "Apple")
    verifier_company_id = verifier["company_id"]
    registered_apple = db_session.get(Company, uuid.UUID(verifier_company_id))
    registered_apple.industry = "SameNameTestIndustry"
    db_session.commit()

    resp = client.get("/api/companies", params={"search": "Apple", "industry": "SameNameTestIndustry"})
    apple_rows = resp.json()["items"]
    assert len(apple_rows) == 2
    ids = {row["id"] for row in apple_rows}
    assert ids == {str(directory_apple.id), verifier_company_id}
    directory_row = next(r for r in apple_rows if r["id"] == str(directory_apple.id))
    registered_row = next(r for r in apple_rows if r["id"] == verifier_company_id)
    assert directory_row["is_registered"] is False
    assert registered_row["is_registered"] is True


def test_institution_search_prefix_match_ranks_before_substring_match(client, db_session):
    _directory_institution(db_session, "Royal Aalborg Institute", institution_type="PrefixRankTestType")
    _directory_institution(db_session, "Aalto University", institution_type="PrefixRankTestType")

    resp = client.get("/api/institutions", params={"search": "Aal", "institution_type": "PrefixRankTestType"})
    names = [i["name"] for i in resp.json()["items"]]
    assert names == ["Aalto University", "Royal Aalborg Institute"]


def test_institution_search_prefix_matches_sorted_alphabetically(client, db_session):
    _directory_institution(db_session, "Aalto University", institution_type="PrefixAlphaTestType")
    _directory_institution(db_session, "Aalborg University", institution_type="PrefixAlphaTestType")

    resp = client.get("/api/institutions", params={"search": "Aal", "institution_type": "PrefixAlphaTestType"})
    names = [i["name"] for i in resp.json()["items"]]
    assert names == ["Aalborg University", "Aalto University"]


def test_institution_search_prefix_ranking_is_case_insensitive(client, db_session):
    _directory_institution(db_session, "Royal Aalborg Institute", institution_type="PrefixCaseTestType")
    _directory_institution(db_session, "aalto university", institution_type="PrefixCaseTestType")

    resp = client.get("/api/institutions", params={"search": "AAL", "institution_type": "PrefixCaseTestType"})
    names = [i["name"] for i in resp.json()["items"]]
    assert names == ["aalto university", "Royal Aalborg Institute"]


def test_institution_search_with_empty_search_is_plain_alphabetical(client, db_session):
    _directory_institution(db_session, "Zzz Empty Search University", institution_type="EmptySearchOrderingType")
    _directory_institution(db_session, "Zza Empty Search University", institution_type="EmptySearchOrderingType")

    # No `search` term at all (institution_type alone isolates these two rows from everything
    # else the rest of the suite has created) — exercises the plain lower(name)-only ordering
    # path, with no prefix rank to compute.
    resp = client.get("/api/institutions", params={"institution_type": "EmptySearchOrderingType"})
    names = [i["name"] for i in resp.json()["items"]]
    assert names == ["Zza Empty Search University", "Zzz Empty Search University"]
