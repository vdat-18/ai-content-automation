"""Add selected products and reference search profiles.

Revision ID: ae4f5a6b7c82
Revises: ad3e4f5a6b71
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ae4f5a6b7c82"
down_revision: str | None = "ad3e4f5a6b71"
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
        "product_selections",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("product_type", sa.Text()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("product_id", name="pk_product_selections"),
        schema="marketing",
    )
    op.create_table(
        "reference_profiles",
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("exclude_keywords", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("product_type", name="pk_reference_profiles"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("reference_profiles", schema="marketing")
    op.drop_table("product_selections", schema="marketing")
