"""Add collected marketplace products.

Revision ID: ad3e4f5a6b71
Revises: ac3d4e5f6071
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ad3e4f5a6b71"
down_revision: str | None = "ac3d4e5f6071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marketplace_products",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("sold_count", sa.BigInteger()),
        sa.Column("has_video", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("listing", postgresql.JSONB()),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column("detail_captured_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("product_id", name="pk_marketplace_products"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("marketplace_products", schema="marketing")
