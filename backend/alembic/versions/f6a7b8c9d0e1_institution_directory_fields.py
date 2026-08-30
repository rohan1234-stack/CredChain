"""institution directory fields + nullable institution/company user_id

Adds public directory fields to institutions (description, location, website,
institution_type) — companies already carry the equivalent fields from the
job-marketplace migration.

Relaxes institutions.user_id and companies.user_id from NOT NULL to nullable.
This is required so the new discovery directory (backend/scripts/seed_directory.py)
can seed real institutions/companies that are listable in the directory
WITHOUT fabricating a login account for each one — a directory row is never
a CredChain-registered account unless a real institution/company later signs
up and a genuine 1:1 link is made. Every existing row already has a non-null
user_id and keeps it; nothing about the current login-linked institution/
company flow changes. This is a pure constraint relaxation (nullable=True),
not a data change — safe to run against existing data.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("institutions", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("companies", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    op.add_column("institutions", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("institutions", sa.Column("location", sa.String(length=255), nullable=True))
    op.add_column("institutions", sa.Column("website", sa.String(length=255), nullable=True))
    op.add_column("institutions", sa.Column("institution_type", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("institutions", "institution_type")
    op.drop_column("institutions", "website")
    op.drop_column("institutions", "location")
    op.drop_column("institutions", "description")

    # Downgrading the nullability back to NOT NULL would fail if any directory-only
    # (user_id IS NULL) rows exist — deleting seeded directory data is a decision
    # for whoever runs this downgrade, not something to do silently here.
    op.alter_column("companies", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.alter_column("institutions", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
