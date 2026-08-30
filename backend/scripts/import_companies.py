"""
Import global companies from Wikidata (https://www.wikidata.org), via its
public SPARQL query service. Wikidata is free, CC0-licensed, structured,
and globally scoped — real company names, real countries, real official
websites (P856) and real industries (P452), sourced from Wikidata's own
"instance of: business (Q4830453)" entities. Nothing here is invented; a
company with no reliably-sourced website/industry on Wikidata simply has
that field left null rather than guessed.

Known data-quality caveat: Wikidata is community-edited, so a small minority
of P856 (official website) values can be wrong or stale (e.g. a vandalized
edit pointing at an unrelated page). This script validates URL *format*
(scheme + domain) but cannot verify a URL's *content* is genuinely that
company's site — see docs/DIRECTORY.md's "known limitations" section. Every
imported row records source="wikidata" + its Wikidata QID specifically so
a bad value can be found and corrected later.

Queried per-country (see COUNTRIES below) rather than as one global query —
Wikidata's public endpoint times out / 502s on broad, unconstrained
property-path queries over millions of entities; a per-country query with a
LIMIT is the shape that reliably completes.

DIRECTORY RECORD, not a CredChain account: every row this script creates has
user_id=NULL — discoverable by a student, never able to post jobs or
receive applications, until/unless the real company registers separately.

Idempotent / safe to rerun: same policy as import_institutions.py — a
Wikidata QID is a genuinely stable identifier, so a rerun's create/update/
skip decision is unambiguous. Duplicate check against Phase 1's manually
curated companies uses the same normalized name+country match.

Usage:
    cd backend
    venv\\Scripts\\Activate.ps1
    python -m scripts.import_companies                       # every configured country
    python -m scripts.import_companies --country India        # one country only
    python -m scripts.import_companies --limit-per-country 50  # cap per country (testing)
    python -m scripts.import_companies --dry-run               # fetch + normalize + report; NO database connection, NO writes
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # see import_institutions.py for why

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.services.directory_import_service import (  # noqa: E402
    ImportReport,
    NormalizedRecord,
    RecordInvalidError,
    build_name_country_index,
    build_name_only_index,
    build_source_index,
    clean_website,
    find_cross_source_duplicate,
    validate_record,
)

SOURCE = "wikidata"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
COMMIT_BATCH_SIZE = 200
DEFAULT_LIMIT_PER_COUNTRY = 150
# Politeness delay between sequential SPARQL requests to the shared public endpoint.
REQUEST_DELAY_SECONDS = 2.0

# Wikidata QIDs verified by a live query resolving each to its English label before being
# hardcoded here (see PR/commit description) — a representative, India-first (per Phase 1's
# stated priority) spread of major economies across every populated continent, not "the whole
# world" (there is no practical single Wikidata query that safely returns that). Extending
# global coverage later just means adding more (name, QID) pairs here and re-running.
COUNTRIES: list[tuple[str, str]] = [
    ("India", "Q668"),
    ("United States", "Q30"),
    ("United Kingdom", "Q145"),
    ("Germany", "Q183"),
    ("France", "Q142"),
    ("Japan", "Q17"),
    ("China", "Q148"),
    ("Canada", "Q16"),
    ("Australia", "Q408"),
    ("Brazil", "Q155"),
    ("Singapore", "Q334"),
    ("South Korea", "Q884"),
    ("Italy", "Q38"),
    ("Spain", "Q29"),
    ("Netherlands", "Q55"),
    ("Switzerland", "Q39"),
    ("Sweden", "Q34"),
    ("Russia", "Q159"),
    ("Mexico", "Q96"),
    ("Indonesia", "Q252"),
    ("Israel", "Q801"),
    ("United Arab Emirates", "Q878"),
    ("South Africa", "Q258"),
    ("Nigeria", "Q1033"),
    ("Ireland", "Q27"),
    ("Belgium", "Q31"),
    ("Poland", "Q36"),
    ("Norway", "Q20"),
    ("Finland", "Q33"),
    ("Denmark", "Q35"),
    ("New Zealand", "Q664"),
    ("Malaysia", "Q833"),
    ("Thailand", "Q869"),
    ("Vietnam", "Q881"),
    ("Philippines", "Q928"),
    ("Pakistan", "Q843"),
    ("Bangladesh", "Q902"),
    ("Egypt", "Q79"),
    ("Turkey", "Q43"),
    ("Saudi Arabia", "Q851"),
    ("Argentina", "Q414"),
    ("Chile", "Q298"),
    ("Austria", "Q40"),
    ("Portugal", "Q45"),
    ("Greece", "Q41"),
    ("Czech Republic", "Q213"),
    ("Hungary", "Q28"),
]


def _query(country_qid: str, limit: int) -> list[dict]:
    sparql = f"""
    SELECT ?company ?companyLabel (SAMPLE(?website) AS ?website) (SAMPLE(?industryLabel) AS ?industry) WHERE {{
      ?company wdt:P31 wd:Q4830453 .
      ?company wdt:P17 wd:{country_qid} .
      ?company wdt:P856 ?website .
      OPTIONAL {{ ?company wdt:P452 ?industry . ?industry rdfs:label ?industryLabel . FILTER(lang(?industryLabel)="en") }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    GROUP BY ?company ?companyLabel
    LIMIT {limit}
    """
    url = f"{SPARQL_ENDPOINT}?query={quote(sparql)}"
    req = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json", "User-Agent": "CredChainDirectoryImport/1.0 (educational project)"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed https API URL, not user input)
        body = json.load(resp)
    return body["results"]["bindings"]


def fetch_country(country_name: str, country_qid: str, limit: int, *, max_retries: int = 3) -> list[dict]:
    """
    Wikidata's shared public endpoint rate-limits bursty callers (HTTP 429) and occasionally
    502s on load — both transient. Retries with backoff before giving up on this one country;
    a non-transient failure (bad query, DNS, etc.) still fails fast after the same number of
    attempts rather than hanging forever. Never aborts the whole import over one country.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return _query(country_qid, limit)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                wait = 10 * attempt
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.isdigit():
                    wait = max(wait, int(retry_after))
                print(f"  rate limited fetching {country_name} ({country_qid}) — waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
                continue
            print(f"  WARNING: fetch failed for {country_name} ({country_qid}) after {attempt} attempt(s): {exc} — skipping this country, continuing.")
            return []
        except (urllib.error.URLError, TimeoutError) as exc:
            # TimeoutError includes socket timeouts (urllib.error.URLError also wraps most of
            # these, but a bare TimeoutError can surface directly) — transient like a 429, so
            # also worth a backoff-and-retry rather than giving up on the first slow response.
            if attempt < max_retries:
                wait = 10 * attempt
                print(f"  timed out fetching {country_name} ({country_qid}) — waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
                continue
            print(f"  WARNING: fetch failed for {country_name} ({country_qid}) after {attempt} attempt(s): {exc} — skipping this country, continuing.")
            return []
        except KeyError as exc:
            print(f"  WARNING: unexpected response shape for {country_name} ({country_qid}): {exc} — skipping this country, continuing.")
            return []
    return []


def normalize(raw: dict, country_name: str) -> NormalizedRecord:
    qid = raw["company"]["value"].rsplit("/", 1)[-1]
    name = raw.get("companyLabel", {}).get("value", "").strip()
    website = clean_website(raw.get("website", {}).get("value"))
    industry = raw.get("industry", {}).get("value", "").strip() or None
    return NormalizedRecord(
        name=name,
        source=SOURCE,
        source_id=qid,
        country=country_name,
        region=None,  # not requested from this query — Wikidata's admin-region data is inconsistent enough across entities to be unreliable at this scale
        city=None,
        website=website,
        description=None,  # not reliably sourced — left null rather than invented (spec section 14)
        extra={"industry": industry},
    )


def run_import(*, country: str | None, limit_per_country: int, dry_run: bool) -> ImportReport:
    report = ImportReport()
    countries = [(n, q) for n, q in COUNTRIES if country is None or n.lower() == country.lower()]
    if not countries:
        print(f"'{country}' is not in this script's configured COUNTRIES list — see the list at the top of scripts/import_companies.py.")
        return report

    candidates: list[NormalizedRecord] = []
    for i, (country_name, qid) in enumerate(countries):
        raw_rows = fetch_country(country_name, qid, limit_per_country)
        print(f"Fetched {len(raw_rows)} raw record(s) for {country_name} ({qid}).")
        for raw in raw_rows:
            rec = normalize(raw, country_name)
            try:
                validate_record(rec.name, rec.website)
            except RecordInvalidError as exc:
                report.skipped_invalid.append(f"{rec.name!r} ({country_name}): {exc}")
                continue
            candidates.append(rec)
        if i < len(countries) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)  # politeness delay against the shared public endpoint

    if dry_run:
        seen: dict[tuple, NormalizedRecord] = {}
        within_batch_duplicates = 0
        for rec in candidates:
            if rec.dedup_key in seen:
                within_batch_duplicates += 1
                continue
            seen[rec.dedup_key] = rec
        print(
            f"[DRY RUN — no database connection made] would attempt to create/update up to {len(seen)} record(s) "
            f"across {len(countries)} countries; {within_batch_duplicates} duplicate(s) within this batch; "
            f"{len(report.skipped_invalid)} invalid record(s)."
        )
        for sample in list(seen.values())[:5]:
            print(f"  sample: {sample.name} | {sample.country} | {sample.extra.get('industry') or '(no industry)'} | {sample.website}")
        return report

    db = SessionLocal()
    try:
        by_source_id = build_source_index(db, Company, SOURCE)
        by_name_country = build_name_country_index(db, Company)
        by_name_only = build_name_only_index(db, Company)

        for rec in candidates:
            existing_by_source = by_source_id.get(rec.source_id)
            if existing_by_source is not None:
                changed = False
                for attr, value in (("website", rec.website), ("industry", rec.extra.get("industry")), ("country", rec.country)):
                    if value is not None and getattr(existing_by_source, attr) != value:
                        setattr(existing_by_source, attr, value)
                        changed = True
                if changed:
                    existing_by_source.location = rec.country or existing_by_source.location
                    db.add(existing_by_source)
                    report.updated += 1
                else:
                    report.skipped_unchanged += 1
                continue

            existing_by_name = find_cross_source_duplicate(by_name_country, by_name_only, rec)
            if existing_by_name is not None:
                report.skipped_duplicate.append(f"{rec.name} ({rec.country}) — matches existing company {existing_by_name.id}")
                continue

            new_row = Company(
                user_id=None,
                name=rec.name,
                industry=rec.extra.get("industry"),
                website=rec.website,
                description=rec.description,
                country=rec.country,
                region=rec.region,
                city=rec.city,
                location=rec.country,
                source=rec.source,
                source_id=rec.source_id,
            )
            db.add(new_row)
            report.created += 1
            by_source_id[rec.source_id] = new_row
            by_name_country[rec.dedup_key] = new_row

            if report.created % COMMIT_BATCH_SIZE == 0:
                db.commit()

        db.commit()
    finally:
        db.close()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country", default=None, help="Import only this configured country (e.g. 'India')")
    parser.add_argument("--limit-per-country", type=int, default=DEFAULT_LIMIT_PER_COUNTRY, help=f"Cap records fetched per country (default {DEFAULT_LIMIT_PER_COUNTRY})")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + normalize + report only — no database connection, no writes")
    args = parser.parse_args()

    report = run_import(country=args.country, limit_per_country=args.limit_per_country, dry_run=args.dry_run)
    if args.dry_run:
        return

    print(f"Company import complete: {report.summary()}")
    if report.skipped_duplicate:
        print(f"  {len(report.skipped_duplicate)} record(s) skipped as duplicates of an existing company (first 10):")
        for line in report.skipped_duplicate[:10]:
            print(f"    - {line}")
    if report.skipped_invalid:
        print(f"  {len(report.skipped_invalid)} record(s) skipped as invalid (first 10):")
        for line in report.skipped_invalid[:10]:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
