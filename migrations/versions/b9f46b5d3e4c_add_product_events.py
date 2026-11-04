"""Add product events, the step-by-step run log shown beside a brief.

Revision ID: b9f46b5d3e4c
Revises: b8e35a4c2d3b
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9f46b5d3e4c"
down_revision: str | None = "b8e35a4c2d3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("shot_index", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="marketing",
    )
    op.create_index(
        "ix_product_events_product",
        "product_events",
        ["product_id", "id"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index("ix_product_events_product", table_name="product_events", schema="marketing")
    op.drop_table("product_events", schema="marketing")
