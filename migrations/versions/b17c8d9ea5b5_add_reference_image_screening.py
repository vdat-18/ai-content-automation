"""Add Gemini screening result to reference images.

Revision ID: b17c8d9ea5b5
Revises: b06b7c8d9ea4
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b17c8d9ea5b5"
down_revision: str | None = "b06b7c8d9ea4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reference_images", sa.Column("screening", postgresql.JSONB()), schema="marketing"
    )


def downgrade() -> None:
    op.drop_column("reference_images", "screening", schema="marketing")
