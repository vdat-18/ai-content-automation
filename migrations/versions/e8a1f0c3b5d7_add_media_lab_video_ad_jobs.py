"""Add autonomous Media Lab Video Ad jobs.

Revision ID: e8a1f0c3b5d7
Revises: d7c2a9f4e681
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a1f0c3b5d7"
down_revision: str | None = "d7c2a9f4e681"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_video_ad_jobs",
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
            "state IN ('planning', 'needs_input', 'generating_shots', 'selecting_segments', "
            "'assembling', 'completed', 'failed', 'cancel_requested', 'cancelled')",
            name=op.f("ck_media_lab_video_ad_jobs_valid_media_lab_video_ad_job_state"),
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_media_lab_video_ad_jobs")),
        sa.UniqueConstraint("source_run_id", name=op.f("uq_media_lab_video_ad_jobs_source_run_id")),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_video_ad_jobs_state", "media_lab_video_ad_jobs", ["state"], schema="marketing"
    )
    op.create_index(
        "ix_media_lab_video_ad_jobs_created",
        "media_lab_video_ad_jobs",
        ["created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_video_ad_jobs_created",
        table_name="media_lab_video_ad_jobs",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_video_ad_jobs_state", table_name="media_lab_video_ad_jobs", schema="marketing"
    )
    op.drop_table("media_lab_video_ad_jobs", schema="marketing")
