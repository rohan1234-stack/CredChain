"""
Shared normalize/validate/dedupe machinery for the directory import scripts
(scripts/import_institutions.py, scripts/import_companies.py). One
implementation of "is this record already in the directory" rather than
each importer inventing its own — see docs/DIRECTORY.md for the full
duplicate-handling policy this implements.

Nothing here talks to an external data source — that's each script's own
concern (fetching Hipolabs JSON, running a Wikidata SPARQL query, etc.).
This module only normalizes already-fetched records and decides
create/update/skip against what's already in the database (or, in
--dry-run mode, only against the rest of the current batch).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy.orm import Session

MAX_NAME_LENGTH = 255
MAX_LOCATION_PART_LENGTH = 120
MAX_WEBSITE_LENGTH = 500


def normalize_name(name: str) -> str:
    """
    Lowercase, trim, collapse internal whitespace, strip trailing/leading
    punctuation. Deliberately conservative — never strips meaningful words
    (e.g. "Institute", "University"), which could turn two different real
    institutions into a false-positive match. Used only as a dedup key,
    never written to the database (the real, human-facing `name` column
    always keeps its original casing/formatting).
    """
    if not name:
        return ""
    collapsed = re.sub(r"\s+", " ", name.strip())
    return collapsed.strip(" .,-").lower()


def normalize_country(country: str | None) -> str | None:
    if not country:
        return None
    collapsed = re.sub(r"\s+", " ", country.strip())
    return collapsed or None


def clean_website(url: str | None) -> str | None:
    """Returns url unchanged if it looks like a real http(s) URL with a domain, else None. Never constructs or guesses a URL — a record with no trustworthy website source value simply has none."""
    if not url:
        return None
    url = url.strip()
    if len(url) > MAX_WEBSITE_LENGTH:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    return url


def _truncate(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:max_length] if value else None


@dataclass
class NormalizedRecord:
    """One candidate row, already normalized and validated, ready to be created/updated/skipped."""

    name: str
    source: str
    source_id: str
    country: str | None = None
    region: str | None = None
    city: str | None = None
    website: str | None = None
    description: str | None = None
    extra: dict = field(default_factory=dict)  # e.g. {"institution_type": ...} or {"industry": ...} — field name differs per model

    @property
    def dedup_key(self) -> tuple[str, str | None]:
        return normalize_name(self.name), normalize_country(self.country)


class RecordInvalidError(Exception):
    """Raised by a caller-supplied validator; caught by run_import to count as a validation error, not raised out of the import loop."""


def validate_record(name: str, website: str | None) -> None:
    """Minimum data-quality bar for any imported record (spec section 14): non-empty name, valid URL format where a website exists."""
    if not name or not name.strip():
        raise RecordInvalidError("empty name")
    if len(name.strip()) > MAX_NAME_LENGTH:
        raise RecordInvalidError(f"name longer than {MAX_NAME_LENGTH} characters")
    if website is not None and clean_website(website) is None:
        raise RecordInvalidError(f"website does not look like a valid http(s) URL: {website!r}")


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped_unchanged: int = 0
    skipped_duplicate: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"created={self.created} updated={self.updated} skipped_unchanged={self.skipped_unchanged} "
            f"skipped_duplicate={len(self.skipped_duplicate)} skipped_invalid={len(self.skipped_invalid)}"
        )


def build_source_index(db: Session, model, source: str) -> dict[str, object]:
    """{source_id: row} for every existing row from THIS source — the idempotency key an importer looks up before deciding create/update/skip on a rerun."""
    rows = db.query(model).filter(model.source == source).all()
    return {row.source_id: row for row in rows if row.source_id}


def build_name_country_index(db: Session, model) -> dict[tuple[str, str | None], object]:
    """
    {(normalized_name, normalized_country): row} for EVERY existing row regardless of source —
    the primary half of the cross-source duplicate check (spec section 13: don't create a second
    "Massachusetts Institute of Technology" just because it came from a different source than the
    first one). One query, whole table, into memory, rather than one query per candidate — the
    whole point of an index instead of an O(n) scan per row on a 10,000+ row table.
    """
    index: dict[tuple[str, str | None], object] = {}
    for row in db.query(model).all():
        key = (normalize_name(row.name), normalize_country(row.country))
        index.setdefault(key, row)
    return index


def build_name_only_index(db: Session, model) -> dict[str, object]:
    """
    {normalized_name: row}, restricted to existing rows with NO structured country — Phase 1's
    manually curated institutions/companies (and anything else predating this schema) only ever
    have the combined free-text `location` field, never the `country` column. A (name, country)
    tuple match in build_name_country_index is therefore IMPOSSIBLE for these rows, no matter how
    exactly a new candidate's name matches, because the candidate always has a real country and
    the existing row's country is None — (name, "India") != (name, None). Without this fallback,
    reimporting a real institution/company that's ALSO one of Phase 1's ~56/58 curated rows would
    create a duplicate for every single one of them, which is exactly what spec section 13 forbids.

    Deliberately narrow: only legacy no-country rows are eligible for this fallback, and only when
    the candidate itself has a country (see find_cross_source_duplicate) — two rows that both carry
    a (possibly different) real country always go through the stronger, exact name+country check
    instead, so this can never conflate two different institutions that happen to share a name in
    different countries.
    """
    index: dict[str, object] = {}
    for row in db.query(model).filter(model.country.is_(None)).all():
        index.setdefault(normalize_name(row.name), row)
    return index


def find_cross_source_duplicate(
    name_country_index: dict[tuple[str, str | None], object],
    name_only_index: dict[str, object],
    rec: NormalizedRecord,
) -> object | None:
    """
    The full cross-source duplicate lookup an importer should use — see build_name_country_index
    and build_name_only_index for what each tier catches and why the second one exists at all.
    """
    existing = name_country_index.get(rec.dedup_key)
    if existing is not None:
        return existing
    if rec.country is not None:
        return name_only_index.get(normalize_name(rec.name))
    return None
