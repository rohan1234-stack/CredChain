"""Add institutions.encrypted_private_key for durable, encrypted signing-key storage

Adds one nullable TEXT column, encrypted_private_key, to institutions. This is
additive only — no existing column, row, or constraint is touched.

Context: institution private keys were previously stored as plain PEM files on
the backend's local disk (KEYS_PATH), which is not durable across a Render
redeploy/restart. This column lets signing_service.py persist the private key
encrypted (via app/security/key_encryption.py, using KEY_ENCRYPTION_SECRET —
an env var, never stored in this database) directly in Postgres instead,
which is already this system's durable store for everything else.

This migration does NOT populate the new column for any existing institution
— every existing institutions.public_key value is left completely untouched,
and encrypted_private_key starts NULL for every row, including ones that
already have a public_key on file. Moving an existing institution's private
key (when its on-disk PEM file is still recoverable) into this column is a
separate, explicit, one-time operation — see
backend/scripts/backfill_encrypted_signing_keys.py — never automatic, and
never run as part of this migration.

Revision ID: i9b0c1d2e3f4
Revises: h7a8b9c0d1e2
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa

revision = "i9b0c1d2e3f4"
down_revision = "h7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institutions", sa.Column("encrypted_private_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("institutions", "encrypted_private_key")
