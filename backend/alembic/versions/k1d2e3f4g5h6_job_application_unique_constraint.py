"""add unique constraint on job_applications(job_id, student_id)

Purely additive concurrency safety boundary. The application layer
(job_application_service.apply_to_job) already rejects a second
application with a friendly error before this is ever reached in normal
sequential use — this constraint only matters when two requests for the
same (job_id, student_id) race each other, so that the database itself
can never end up with two application rows for the same student/job pair.

No existing column, row, or other constraint is touched.

Revision ID: k1d2e3f4g5h6
Revises: j0c1d2e3f4g5
Create Date: 2026-08-29
"""

from alembic import op

revision = "k1d2e3f4g5h6"
down_revision = "j0c1d2e3f4g5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_job_applications_job_id_student_id",
        "job_applications",
        ["job_id", "student_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_applications_job_id_student_id",
        "job_applications",
        type_="unique",
    )
