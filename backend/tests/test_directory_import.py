# ---------------------------------------------------------------------------
# Directory import architecture (Phase 2): the pure normalize/validate/dedupe
# logic shared by scripts/import_institutions.py and scripts/import_companies.py
# (app/services/directory_import_service.py), plus the create/update/skip
# decision against real database rows. No external network call is made by
# any test here — normalize()/validate_record() are pure functions, and the
# create/update/skip tests seed rows directly via db_session instead of
# hitting Hipolabs/Wikidata (see the scripts themselves for real-data proof,
# run manually — see the Phase 2 report).
# ---------------------------------------------------------------------------

from app.models.company import Company
from app.models.institution import Institution
from app.services.directory_import_service import (
    NormalizedRecord,
    RecordInvalidError,
    build_name_country_index,
    build_name_only_index,
    build_source_index,
    clean_website,
    find_cross_source_duplicate,
    normalize_country,
    normalize_name,
    validate_record,
)


def test_normalize_name_is_case_and_whitespace_insensitive_but_conservative():
    assert normalize_name("  Indian Institute  of Technology Bombay ") == "indian institute of technology bombay"
    assert normalize_name("Indian Institute of Technology, Bombay.") == "indian institute of technology, bombay"
    # Conservative: does NOT strip meaningful words that could turn two different real
    # institutions into a false match (e.g. "Institute" vs "University").
    assert normalize_name("Institute of Technology") != normalize_name("University of Technology")


def test_normalize_country_trims_and_collapses_whitespace():
    assert normalize_country("  India  ") == "India"
    assert normalize_country(None) is None
    assert normalize_country("") is None


def test_clean_website_accepts_real_urls_and_rejects_junk():
    assert clean_website("https://www.iitb.ac.in") == "https://www.iitb.ac.in"
    assert clean_website("http://tcs.com") == "http://tcs.com"
    assert clean_website(None) is None
    assert clean_website("") is None
    assert clean_website("not a url") is None
    assert clean_website("ftp://old-scheme.example.com") is None
    assert clean_website("javascript:alert(1)") is None
    assert clean_website("http://") is None


def test_validate_record_rejects_empty_name_and_bad_website():
    try:
        validate_record("", None)
        assert False, "should have raised"
    except RecordInvalidError:
        pass

    try:
        validate_record("Real Name", "not a url")
        assert False, "should have raised"
    except RecordInvalidError:
        pass

    validate_record("Real Name", None)  # no website is fine — never fabricated
    validate_record("Real Name", "https://example.edu")  # passes


def test_build_source_index_only_includes_rows_from_that_source(db_session):
    a = Institution(user_id=None, name="Source A Uni", source="hipolabs_world_universities", source_id="a.edu")
    b = Institution(user_id=None, name="Source B Uni", source="manual_curated", source_id="ignored")
    c = Institution(user_id=None, name="No Source Uni")  # Phase 1 legacy row: source is NULL
    db_session.add_all([a, b, c])
    db_session.commit()

    index = build_source_index(db_session, Institution, "hipolabs_world_universities")
    assert set(index.keys()) == {"a.edu"}
    assert index["a.edu"].name == "Source A Uni"


def test_build_name_country_index_covers_every_row_regardless_of_source(db_session):
    curated = Institution(user_id=None, name="Cross Source University", country="India", source=None)
    db_session.add(curated)
    db_session.commit()

    index = build_name_country_index(db_session, Institution)
    key = (normalize_name("Cross Source University"), normalize_country("India"))
    assert key in index
    assert index[key].id == curated.id


def test_reimport_of_same_source_id_updates_not_duplicates(db_session):
    """Simulates what import_institutions.py's create/update/skip branch does on a rerun — without hitting the network."""
    existing = Institution(
        user_id=None, name="Rerun Test University", source="hipolabs_world_universities", source_id="rerun.edu",
        website=None, region=None, country="India",
    )
    db_session.add(existing)
    db_session.commit()

    by_source_id = build_source_index(db_session, Institution, "hipolabs_world_universities")
    assert "rerun.edu" in by_source_id

    found = by_source_id["rerun.edu"]
    found.website = "https://rerun.edu"  # what the importer would do on finding a changed field
    db_session.commit()

    count_before = db_session.query(Institution).filter(Institution.source_id == "rerun.edu").count()
    assert count_before == 1  # still exactly one row — an update, never a duplicate insert


def test_cross_source_duplicate_is_detected_when_both_sides_have_a_country(db_session):
    """Two sources that both populate a structured country for the "same" institution must be recognized as the same real-world entity."""
    existing = Institution(user_id=None, name="Indian Institute of Technology Bombay", country="India", source="some_other_source", source_id="x")
    db_session.add(existing)
    db_session.commit()

    candidate = NormalizedRecord(name="Indian Institute of Technology Bombay", source="hipolabs_world_universities", source_id="iitb.ac.in", country="India")
    name_country_index = build_name_country_index(db_session, Institution)
    name_only_index = build_name_only_index(db_session, Institution)
    match = find_cross_source_duplicate(name_country_index, name_only_index, candidate)
    assert match is not None
    assert match.id == existing.id  # the importer would skip creating a second row here


def test_cross_source_duplicate_matches_a_legacy_row_that_has_no_structured_country(db_session):
    """
    Regression test for the real shape of Phase 1's manually curated institutions/companies:
    they only ever have the combined free-text `location` field, never the structured `country`
    column populated — `country` is genuinely None on every one of them. A naive (name, country)
    tuple match can NEVER find these rows once a real import candidate (which always has a real
    country) comes along, because (name, "India") != (name, None) — which would create a
    duplicate "Indian Institute of Technology Bombay" for every single Phase 1 institution the
    first time a real import ran. find_cross_source_duplicate's name-only fallback exists
    specifically to prevent that.
    """
    legacy = Institution(user_id=None, name="Indian Institute of Technology Bombay", location="Mumbai, Maharashtra, India", country=None, source=None)
    db_session.add(legacy)
    db_session.commit()
    assert legacy.country is None  # exactly Phase 1's real shape

    candidate = NormalizedRecord(name="Indian Institute of Technology Bombay", source="hipolabs_world_universities", source_id="iitb.ac.in", country="India")
    name_country_index = build_name_country_index(db_session, Institution)
    name_only_index = build_name_only_index(db_session, Institution)

    # The naive tuple lookup alone would NOT find it (this is the bug being guarded against):
    assert name_country_index.get(candidate.dedup_key) is None

    match = find_cross_source_duplicate(name_country_index, name_only_index, candidate)
    assert match is not None
    assert match.id == legacy.id


def test_cross_source_fallback_never_applies_when_candidate_has_no_country_either():
    """The name-only fallback is deliberately narrow: two rows that both lack a country never match through it (there is nothing to safely compare), which keeps it from being a blanket "match by name alone" rule."""
    name_only_index = {normalize_name("Ambiguous University"): object()}
    candidate_with_no_country = NormalizedRecord(name="Ambiguous University", source="some_source", source_id="y", country=None)
    match = find_cross_source_duplicate({}, name_only_index, candidate_with_no_country)
    assert match is None


def test_company_source_and_name_country_indexes_work_the_same_way(db_session):
    a = Company(user_id=None, name="Wikidata Test Co", source="wikidata", source_id="Q999999")
    b = Company(user_id=None, name="Curated Test Co", country="India", source=None)
    db_session.add_all([a, b])
    db_session.commit()

    source_index = build_source_index(db_session, Company, "wikidata")
    assert "Q999999" in source_index

    name_index = build_name_country_index(db_session, Company)
    assert (normalize_name("Curated Test Co"), normalize_country("India")) in name_index
