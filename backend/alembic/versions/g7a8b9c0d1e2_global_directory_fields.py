"""global directory fields: country/region/city/source/source_id/logo_url on institutions + companies

Phase 2: scales the directory (Phase 1's ~56 institutions / ~58 companies,
manually curated) to bulk imports from external datasets (see
scripts/import_institutions.py, scripts/import_companies.py). Adds
structured location fields (country/region/city) so search/filtering can be
done with real indexed SQL predicates instead of substring-matching the
existing free-text `location` column, plus source/source_id so an importer
can be idempotent (upsert-by-source-id) and every record keeps a record of
where it came from (never a stored claim of "verified" beyond that).

Adds indexes on country and (source, source_id) — the latter is what makes
re-running an importer safe (look up by source+source_id before inserting).

Purely additive: new nullable columns + new indexes. No existing column is
altered, dropped, or renamed; no data is modified. Every row created by
Phase 1 (manually curated, no source recorded) simply has these new columns
as NULL until/unless a future import enriches it — the existing `location`,
`description`, `website`, `institution_type`/`industry` columns are
untouched and keep working exactly as before.

Revision ID: g7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "g7a8b9c0d1e2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("institutions", "companies"):
        op.add_column(table, sa.Column("country", sa.String(length=120), nullable=True))
        op.add_column(table, sa.Column("region", sa.String(length=120), nullable=True))
        op.add_column(table, sa.Column("city", sa.String(length=120), nullable=True))
        op.add_column(table, sa.Column("logo_url", sa.String(length=500), nullable=True))
        # Free text ("manual_curated", "hipolabs_world_universities", "wikidata", ...) rather than
        # an enum: new sources will keep getting added as the directory grows, and a Postgres enum
        # would need its own migration every time one does.
        op.add_column(table, sa.Column("source", sa.String(length=100), nullable=True))
        # The source's own stable identifier for this record (e.g. a Wikidata QID, or a domain for
        # the Hipolabs dataset which has no numeric id) — the idempotency key an importer looks up
        # by before deciding create/update/skip. NULL for Phase 1's manually curated rows and for
        # any real institution/company that registered directly rather than being imported.
        op.add_column(table, sa.Column("source_id", sa.String(length=255), nullable=True))

        op.create_index(f"ix_{table}_country", table, ["country"])
        # A source can reuse the same source_id in a different source's namespace (e.g. two
        # different datasets both using "12345"), so uniqueness is scoped to the pair, not
        # source_id alone. Partial-safe: rows with NULL source/source_id (all pre-Phase-2 rows)
        # never collide with each other or with real imported rows under Postgres NULL semantics.
        op.create_index(f"ix_{table}_source_source_id", table, ["source", "source_id"], unique=True)


def downgrade() -> None:
    for table in ("institutions", "companies"):
        op.drop_index(f"ix_{table}_source_source_id", table_name=table)
        op.drop_index(f"ix_{table}_country", table_name=table)
        op.drop_column(table, "source_id")
        op.drop_column(table, "source")
        op.drop_column(table, "logo_url")
        op.drop_column(table, "city")
        op.drop_column(table, "region")
        op.drop_column(table, "country")
