"""Add final Media Lab video projects.

Revision ID: d7c2a9f4e681
Revises: b1a5c7d9e2f4
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7c2a9f4e681"
down_revision: str | None = "b1a5c7d9e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_lab_video_projects",
        sa.Column("project_id", sa.Text(), nullable=False),
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
            "state IN ('assembling', 'awaiting_human_review', 'approved', 'rejected', 'failed')",
            name=op.f("ck_media_lab_video_projects_valid_media_lab_video_project_state"),
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_media_lab_video_projects")),
        sa.UniqueConstraint(
            "source_run_id", name=op.f("uq_media_lab_video_projects_source_run_id")
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_video_projects_state",
        "media_lab_video_projects",
        ["state"],
        schema="marketing",
    )
    op.create_index(
        "ix_media_lab_video_projects_created",
        "media_lab_video_projects",
        ["created_at"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_lab_video_projects_created",
        table_name="media_lab_video_projects",
        schema="marketing",
    )
    op.drop_index(
        "ix_media_lab_video_projects_state",
        table_name="media_lab_video_projects",
        schema="marketing",
    )
    op.drop_table("media_lab_video_projects", schema="marketing")
