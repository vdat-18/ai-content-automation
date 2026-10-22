"""add human review state to research records

Revision ID: f9a0b1c2d303
Revises: f8b2c4d6e901
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d303"
down_revision: str | None = "f8b2c4d6e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_records",
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending_review'"),
        ),
        schema="marketing",
    )
    op.add_column(
        "research_records",
        sa.Column("reviewer_alias", sa.Text(), nullable=True),
        schema="marketing",
    )
    op.add_column(
        "research_records",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema="marketing",
    )
    op.add_column(
        "research_records",
        sa.Column("review_reason", sa.Text(), nullable=True),
        schema="marketing",
    )
    op.create_index(
        "ix_research_records_review_status",
        "research_records",
        ["review_status"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_records_review_status",
        table_name="research_records",
        schema="marketing",
    )
    op.drop_column("research_records", "review_reason", schema="marketing")
    op.drop_column("research_records", "reviewed_at", schema="marketing")
    op.drop_column("research_records", "reviewer_alias", schema="marketing")
    op.drop_column("research_records", "review_status", schema="marketing")
