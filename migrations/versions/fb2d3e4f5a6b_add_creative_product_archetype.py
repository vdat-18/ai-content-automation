"""add Creative knowledge product archetype scope

Revision ID: fb2d3e4f5a6b
Revises: fa1c2d3e4b5f
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb2d3e4f5a6b"
down_revision: str | None = "fa1c2d3e4b5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creative_knowledge_versions",
        sa.Column("product_archetype", sa.Text(), nullable=True),
        schema="marketing",
    )
    op.drop_index(
        "ix_creative_knowledge_scope",
        table_name="creative_knowledge_versions",
        schema="marketing",
    )
    op.create_index(
        "ix_creative_knowledge_scope",
        "creative_knowledge_versions",
        ["brand_id", "niche_id", "product_archetype", "product_family_id", "variant_id"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creative_knowledge_scope",
        table_name="creative_knowledge_versions",
        schema="marketing",
    )
    op.create_index(
        "ix_creative_knowledge_scope",
        "creative_knowledge_versions",
        ["brand_id", "niche_id", "product_family_id", "variant_id"],
        schema="marketing",
    )
    op.drop_column(
        "creative_knowledge_versions",
        "product_archetype",
        schema="marketing",
    )
