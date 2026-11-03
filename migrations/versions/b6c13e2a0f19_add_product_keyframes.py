"""Add product keyframes, one still image per storyboard shot.

Revision ID: b6c13e2a0f19
Revises: b5b02d18e9f9
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c13e2a0f19"
down_revision: str | None = "b5b02d18e9f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_keyframes",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("image_path", sa.Text()),
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
    op.drop_table("product_keyframes", schema="marketing")
