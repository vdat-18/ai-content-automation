"""Add product clips, one image-to-video clip per storyboard shot.

Revision ID: b8e35a4c2d3b
Revises: b7d24f3b1c2a
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e35a4c2d3b"
down_revision: str | None = "b7d24f3b1c2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_clips",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text()),
        sa.Column("job_model", sa.Text()),
        sa.Column("video_path", sa.Text()),
        sa.Column("seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("product_id", "shot_index"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("product_clips", schema="marketing")
