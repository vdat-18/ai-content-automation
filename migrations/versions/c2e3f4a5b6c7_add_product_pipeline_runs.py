"""Add product pipeline runs, so how a run ended survives a restart.

Revision ID: c2e3f4a5b6c7
Revises: b17c8d9e0fa5
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2e3f4a5b6c7"
down_revision: str | None = "b17c8d9e0fa5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_pipeline_runs",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("product_id"),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_table("product_pipeline_runs", schema="marketing")
