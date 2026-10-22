"""Add persisted Media Lab video runs.

Revision ID: 8e53b3a4c0d1
Revises: f2a7d4c10b2e
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8e53b3a4c0d1"
down_revision: str | None = "f2a7d4c10b2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_video_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("generation_state", sa.Text(), nullable=False),
        sa.Column("review_state", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("backend_run_id", sa.Text(), nullable=True),
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
            "generation_state IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
            name=op.f("ck_media_lab_video_runs_valid_media_lab_video_generation_state"),
        ),
        sa.CheckConstraint(
            "review_state IN ('not_ready', 'awaiting_human_review', 'approved', 'rejected')",
            name=op.f("ck_media_lab_video_runs_valid_media_lab_video_review_state"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_media_lab_video_runs")),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_video_runs_backend",
        "media_lab_video_runs",
        ["backend_run_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_video_runs_created",
        "media_lab_video_runs",
        ["created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_video_runs_created",
        table_name="media_lab_video_runs",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_video_runs_backend",
        table_name="media_lab_video_runs",
        schema="marketing",
    )
    op.drop_table("media_lab_video_runs", schema="marketing")
