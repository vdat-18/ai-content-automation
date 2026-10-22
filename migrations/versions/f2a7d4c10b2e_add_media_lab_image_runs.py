"""Add persisted Media Lab image runs.

Revision ID: f2a7d4c10b2e
Revises: e4b178ef257a
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a7d4c10b2e"
down_revision: str | None = "e4b178ef257a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_image_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("generation_state", sa.Text(), nullable=False),
        sa.Column("review_state", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("backend_run_id", sa.Text(), nullable=True),
        sa.Column("parent_run_id", sa.Text(), nullable=True),
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
            name=op.f("ck_media_lab_image_runs_valid_media_lab_image_generation_state"),
        ),
        sa.CheckConstraint(
            "review_state IN ('not_ready', 'awaiting_human_review', 'approved', 'rejected')",
            name=op.f("ck_media_lab_image_runs_valid_media_lab_image_review_state"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_media_lab_image_runs")),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_image_runs_backend",
        "media_lab_image_runs",
        ["backend_run_id"],
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_image_runs_created",
        "media_lab_image_runs",
        ["created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_image_runs_created",
        table_name="media_lab_image_runs",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_image_runs_backend",
        table_name="media_lab_image_runs",
        schema="marketing",
    )
    op.drop_table("media_lab_image_runs", schema="marketing")
