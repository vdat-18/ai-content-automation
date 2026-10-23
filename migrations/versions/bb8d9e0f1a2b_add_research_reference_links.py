"""Add reference-to-product links and reference usage.

Revision ID: bb8d9e0f1a2b
Revises: aa7c8d9e0f1a
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb8d9e0f1a2b"
down_revision: str | None = "aa7c8d9e0f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_reference_products",
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("match_kind", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "match_kind IN ('product_visible', 'scene_fit', 'style_only')",
            name=op.f("ck_research_reference_products_valid_match_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["record_key"],
            ["marketing.research_records.record_key"],
            name=op.f("fk_research_reference_products_record_key_research_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "record_key", "product_id", name=op.f("pk_research_reference_products")
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_research_reference_products_product",
        "research_reference_products",
        ["product_id"],
        schema="marketing",
    )
    op.create_table(
        "research_reference_uses",
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_key"],
            ["marketing.research_records.record_key"],
            name=op.f("fk_research_reference_uses_record_key_research_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "record_key", "media_id", "batch_id", name=op.f("pk_research_reference_uses")
        ),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("research_reference_uses", schema="marketing")
    op.drop_index(
        "ix_research_reference_products_product",
        table_name="research_reference_products",
        schema="marketing",
    )
    op.drop_table("research_reference_products", schema="marketing")
