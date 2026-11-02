"""Add Pinterest reference images and crawled searches.

Revision ID: af5a6b7c8d93
Revises: ae4f5a6b7c82
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "af5a6b7c8d93"
down_revision: str | None = "ae4f5a6b7c82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "reference_images",
        sa.Column("image_id", sa.Text(), nullable=False),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("pin_url", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'new'")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("image_id", name="pk_reference_images"),
        schema="marketing",
    )
    op.create_table(
        "reference_searches",
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("product_type", "query", name="pk_reference_searches"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("reference_searches", schema="marketing")
    op.drop_table("reference_images", schema="marketing")
