"""Add content briefs drafted by the agent.

Revision ID: b39e0fb6c7d7
Revises: b28d9ea5b6c6
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b39e0fb6c7d7"
down_revision: str | None = "b28d9ea5b6c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_briefs",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("user_idea", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("product_id", name="pk_product_briefs"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("product_briefs", schema="marketing")
