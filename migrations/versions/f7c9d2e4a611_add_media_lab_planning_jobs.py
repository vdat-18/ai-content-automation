"""Add durable Media Lab planning jobs.

Revision ID: f7c9d2e4a611
Revises: e8a1f0c3b5d7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7c9d2e4a611"
down_revision: str | None = "e8a1f0c3b5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_planning_jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('planning', 'ready', 'needs_input', 'failed')",
            name=op.f("ck_media_lab_planning_jobs_valid_media_lab_planning_job_state"),
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_media_lab_planning_jobs")),
        sa.UniqueConstraint("source_run_id", name=op.f("uq_media_lab_planning_jobs_source_run_id")),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_planning_jobs_state",
        "media_lab_planning_jobs",
        ["state"],
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_planning_jobs_created",
        "media_lab_planning_jobs",
        ["created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_planning_jobs_created",
        table_name="media_lab_planning_jobs",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_planning_jobs_state",
        table_name="media_lab_planning_jobs",
        schema="marketing",
    )
    op.drop_table("media_lab_planning_jobs", schema="marketing")
