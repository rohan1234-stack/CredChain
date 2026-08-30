"""Add notifications table for the per-recipient notification center

Adds one new table, `notifications`. Purely additive — no existing table,
column, or constraint is touched.

ActivityLog remains the shared, append-only audit/event log (unchanged);
this table holds per-RECIPIENT read state and a self-contained display
snapshot (title/message), since read/unread is inherently per-viewer and
does not belong on the shared event row (see app/models/notification.py's
docstring for the full rationale).

activity_log_id is a nullable FK (ON DELETE SET NULL) — a Notification row
must never be lost just because its originating ActivityLog row is gone.
user_id is a nullable-never FK (ON DELETE CASCADE) — a notification only
ever makes sense attached to its recipient; if that user is deleted there
is nothing left for it to belong to.

Two indexes match the two real access patterns this table serves:
  - (user_id, created_at): paginated "my notifications, newest first"
  - (user_id) WHERE is_read = false: an O(unread rows only) unread count,
    a Postgres partial index so it never has to scan already-read rows.

Revision ID: j0c1d2e3f4g5
Revises: i9b0c1d2e3f4
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j0c1d2e3f4g5"
down_revision = "i9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "activity_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("activity_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("link_entity_type", sa.String(length=50), nullable=True),
        sa.Column("link_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_activity_log_id", "notifications", ["activity_log_id"])
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id"],
        postgresql_where=sa.text("is_read = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_activity_log_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
