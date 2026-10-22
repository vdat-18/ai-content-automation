"""add Creative knowledge bootstrap history

Revision ID: fc3e4f5a6b7c
Revises: fb2d3e4f5a6b
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fc3e4f5a6b7c"
down_revision: str | None = "fb2d3e4f5a6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_knowledge_bootstraps",
        sa.Column("bootstrap_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("applied_by", sa.Text(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_count > 0",
            name="positive_creative_knowledge_bootstrap_items",
        ),
        sa.PrimaryKeyConstraint("bootstrap_id"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("creative_knowledge_bootstraps", schema="marketing")
