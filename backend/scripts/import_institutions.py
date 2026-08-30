"""
Import global institutions from the Hipolabs "world universities" open
dataset (http://universities.hipolabs.com) — 10,000+ real institutions
across 200+ countries. This is the public, MIT-licensed dataset derived
from the community-maintained Hipo/university-domains-list project: real
names, real countries, real official website URLs. Nothing here is
invented, and no institution/state/province/city is fabricated — a field
the source doesn't provide is simply left null.

DIRECTORY RECORD, not a CredChain account: every row this script creates
has user_id=NULL (see the Phase 2 migration that made institutions.user_id
nullable) — discoverable by a student, never able to log in or issue
credentials, until/unless the real institution registers separately.

Idempotent / safe to rerun:
  - each record's `source_id` (the first domain the source lists, or a
    normalized name+country fallback if it has no domain) is looked up
    against existing rows from THIS source first — a rerun updates changed
    fields (website, region, country) on rows it created before, and
    changes nothing else
  - a candidate that doesn't match by source_id is THEN checked against
    every existing institution regardless of source, by normalized
    name+country (see directory_import_service.build_name_country_index) —
    a match is reported and skipped, never silently merged or duplicated
  - never deletes anything, never touches users/students/credentials

This is a controlled backend/admin script — never exposed as a public API
endpoint (see docs/DIRECTORY.md's "Admin/maintenance" section).

Usage:
    cd backend
    venv\\Scripts\\Activate.ps1
    python -m scripts.import_institutions                     # every country
    python -m scripts.import_institutions --country India      # one country
    python -m scripts.import_institutions --limit 500           # cap records (testing)
    python -m scripts.import_institutions --dry-run             # fetch + normalize + report; NO database connection, NO writes
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote

# Institution/company names legitimately contain non-ASCII characters (accents, etc.); Windows'
# default console codepage (cp1252) can't print all of them and would crash mid-import on a
# print() otherwise. Render/Linux already default to UTF-8 — this just makes `python -m
# scripts.import_institutions` equally reliable run locally on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.institution import Institution  # noqa: E402
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

SOURCE = "hipolabs_world_universities"
API_URL = "http://universities.hipolabs.com/search"
GENERIC_INSTITUTION_TYPE = "Higher Education Institution"  # true of the whole dataset's scope, not a per-record guess
COMMIT_BATCH_SIZE = 200


def fetch(country: str | None) -> list[dict]:
    url = f"{API_URL}?country={quote(country)}" if country else API_URL
    req = urllib.request.Request(url, headers={"User-Agent": "CredChainDirectoryImport/1.0 (educational project)"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed http(s) API URL, not user input)
        return json.load(resp)


def normalize(raw: dict) -> NormalizedRecord:
    name = (raw.get("name") or "").strip()
    country = (raw.get("country") or "").strip() or None
    region = (raw.get("state-province") or "").strip() or None
    domains = [d.strip().lower() for d in (raw.get("domains") or []) if d and d.strip()]
    web_pages = raw.get("web_pages") or []
    website = clean_website(web_pages[0]) if web_pages else None
    source_id = domains[0] if domains else f"{name.lower()}|{(country or '').lower()}"
    return NormalizedRecord(
        name=name,
        source=SOURCE,
        source_id=source_id,
        country=country,
        region=region,
        city=None,  # the source does not provide city-level data — never fabricated
        website=website,
        description=None,  # not reliably sourced — left null rather than invented (spec section 14)
        extra={"institution_type": GENERIC_INSTITUTION_TYPE},
    )


def _location_of(rec: NormalizedRecord) -> str | None:
    parts = [p for p in (rec.region, rec.country) if p]
    return ", ".join(parts) if parts else None


def run_import(*, country: str | None, limit: int | None, dry_run: bool) -> ImportReport:
    report = ImportReport()
    raw_records = fetch(country)
    if limit:
        raw_records = raw_records[:limit]
    scope = f" (country={country})" if country else ""
    print(f"Fetched {len(raw_records)} raw record(s) from {SOURCE}{scope}.")

    candidates: list[NormalizedRecord] = []
    for raw in raw_records:
        rec = normalize(raw)
        try:
            validate_record(rec.name, rec.website)
        except RecordInvalidError as exc:
            report.skipped_invalid.append(f"{rec.name!r}: {exc}")
            continue
        candidates.append(rec)

    if dry_run:
        # No database connection is opened in dry-run mode, so duplicates can only be detected
        # within this fetched batch — genuinely proves fetch+normalize+validate work against the
        # live source without requiring a database (see README's local-environment note).
        seen: dict[tuple, NormalizedRecord] = {}
        within_batch_duplicates = 0
        for rec in candidates:
            if rec.dedup_key in seen:
                within_batch_duplicates += 1
                continue
            seen[rec.dedup_key] = rec
        print(
            f"[DRY RUN — no database connection made] would attempt to create/update up to {len(seen)} record(s); "
            f"{within_batch_duplicates} duplicate(s) within this batch; {len(report.skipped_invalid)} invalid record(s)."
        )
        for sample in list(seen.values())[:5]:
            print(f"  sample: {sample.name} | {sample.country} | {sample.region or '(no region)'} | {sample.website or '(no website)'}")
        return report

    db = SessionLocal()
    try:
        by_source_id = build_source_index(db, Institution, SOURCE)
        by_name_country = build_name_country_index(db, Institution)
        by_name_only = build_name_only_index(db, Institution)

        for rec in candidates:
            existing_by_source = by_source_id.get(rec.source_id)
            if existing_by_source is not None:
                changed = False
                for attr, value in (("website", rec.website), ("region", rec.region), ("country", rec.country)):
                    if value is not None and getattr(existing_by_source, attr) != value:
                        setattr(existing_by_source, attr, value)
                        changed = True
                if existing_by_source.institution_type is None:
                    existing_by_source.institution_type = GENERIC_INSTITUTION_TYPE
                    changed = True
                if changed:
                    new_location = _location_of(rec)
                    if new_location:
                        existing_by_source.location = new_location
                    db.add(existing_by_source)
                    report.updated += 1
                else:
                    report.skipped_unchanged += 1
                continue

            existing_by_name = find_cross_source_duplicate(by_name_country, by_name_only, rec)
            if existing_by_name is not None:
                report.skipped_duplicate.append(f"{rec.name} ({rec.country}) — matches existing institution {existing_by_name.id}")
                continue

            new_row = Institution(
                user_id=None,
                name=rec.name,
                country=rec.country,
                region=rec.region,
                city=rec.city,
                website=rec.website,
                description=rec.description,
                institution_type=rec.extra.get("institution_type"),
                location=_location_of(rec),
                source=rec.source,
                source_id=rec.source_id,
            )
            db.add(new_row)
            report.created += 1
            # Register in both indexes immediately so later candidates in THIS SAME batch also
            # dedupe against it — two near-identical rows from one run never both get created.
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
    parser.add_argument("--country", default=None, help="Import only this country (matches the source's own country field, e.g. 'India')")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of fetched records (useful for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + normalize + report only — no database connection, no writes")
    args = parser.parse_args()

    report = run_import(country=args.country, limit=args.limit, dry_run=args.dry_run)
    if args.dry_run:
        return

    print(f"Institution import complete: {report.summary()}")
    if report.skipped_duplicate:
        print(f"  {len(report.skipped_duplicate)} record(s) skipped as duplicates of an existing institution (first 10):")
        for line in report.skipped_duplicate[:10]:
            print(f"    - {line}")
    if report.skipped_invalid:
        print(f"  {len(report.skipped_invalid)} record(s) skipped as invalid (first 10):")
        for line in report.skipped_invalid[:10]:
            print(f"    - {line}")


if __name__ == "__main__":
    main()
