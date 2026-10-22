"""add research record soft delete

Revision ID: fd4e5f6a7b8c
Revises: fc3e4f5a6b7c
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fd4e5f6a7b8c"
down_revision: str | None = "fc3e4f5a6b7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_records",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_column("research_records", "deleted_at", schema="marketing")
