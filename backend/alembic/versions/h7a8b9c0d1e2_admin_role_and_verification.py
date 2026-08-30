"""Phase A: admin role + institution/company verification status

Adds:
  - 'admin' as a new value of the existing user_role Postgres enum (ADD VALUE,
    not a new type — every existing user_role value and every row that uses
    them is completely untouched).
  - a new verification_status Postgres enum (pending/verified/rejected).
  - verification_status, verified_at, verified_by, rejection_reason on both
    institutions and companies — trust/verification fields for REGISTERED
    accounts only (a directory-only row, user_id IS NULL, gets the column's
    'pending' default too, but it is never surfaced or acted on for one —
    see institution_service.to_response / company_service.to_response).

EXISTING DATA (critical — this is what prevents the migration from locking
anyone out): every institution/company row that ALREADY has a real user_id
(i.e. is a real, currently-working registered account, not a directory
listing) is immediately backfilled to 'verified' in this same migration.
Directory-only rows (user_id IS NULL) are left at the 'pending' default,
which is irrelevant to them since they have no User account and can never
log in, issue a credential, or publish a job. No row is deleted, renamed, or
has an existing column altered.

Revision ID: h7a8b9c0d1e2
Revises: g7a8b9c0d1e2
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "h7a8b9c0d1e2"
down_revision = "g7a8b9c0d1e2"
branch_labels = None
depends_on = None

_VERIFICATION_STATUS = postgresql.ENUM("pending", "verified", "rejected", name="verification_status")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block (same
    # pattern already used in a1b2c3d4e5f6_add_other_credential_type.py).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'admin'")

    _VERIFICATION_STATUS.create(op.get_bind(), checkfirst=True)

    for table in ("institutions", "companies"):
        op.add_column(
            table,
            sa.Column("verification_status", _VERIFICATION_STATUS, nullable=False, server_default="pending"),
        )
        op.add_column(table, sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "verified_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(table, sa.Column("rejection_reason", sa.Text(), nullable=True))
        op.create_index(f"ix_{table}_verification_status", table, ["verification_status"])

    # Grandfather every EXISTING registered account (real login-linked row) as verified — these
    # accounts are already operating in production (some have already issued real credentials /
    # published real jobs) and must not be retroactively blocked. Directory-only rows (user_id
    # IS NULL) are deliberately left at the 'pending' default — they are not accounts at all, and
    # must never be implied to be a verified platform account merely for existing in the
    # directory.
    op.execute("UPDATE institutions SET verification_status = 'verified' WHERE user_id IS NOT NULL")
    op.execute("UPDATE companies SET verification_status = 'verified' WHERE user_id IS NOT NULL")


def downgrade() -> None:
    for table in ("institutions", "companies"):
        op.drop_index(f"ix_{table}_verification_status", table_name=table)
        op.drop_column(table, "rejection_reason")
        op.drop_column(table, "verified_by")
        op.drop_column(table, "verified_at")
        op.drop_column(table, "verification_status")
    _VERIFICATION_STATUS.drop(op.get_bind(), checkfirst=True)
    # Postgres has no ALTER TYPE ... DROP VALUE — removing the 'admin' enum value would require
    # rebuilding the user_role type, unsafe to do blindly in a downgrade (same reasoning, and
    # same no-op choice, as a1b2c3d4e5f6_add_other_credential_type.py's downgrade).
