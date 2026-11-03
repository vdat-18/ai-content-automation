"""Add image fingerprints used to drop duplicate reference images.

Revision ID: b5b02d18e9f9
Revises: b4af1c07d8e8
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5b02d18e9f9"
down_revision: str | None = "b4af1c07d8e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reference_images", sa.Column("phash", sa.Text()), schema="marketing")
    op.add_column(
        "reference_images", sa.Column("embedding", postgresql.JSONB()), schema="marketing"
    )
    op.add_column("reference_images", sa.Column("duplicate_of", sa.Text()), schema="marketing")


def downgrade() -> None:
    op.drop_column("reference_images", "duplicate_of", schema="marketing")
    op.drop_column("reference_images", "embedding", schema="marketing")
    op.drop_column("reference_images", "phash", schema="marketing")
