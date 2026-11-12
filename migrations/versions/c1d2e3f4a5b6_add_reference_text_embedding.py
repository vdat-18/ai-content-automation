"""Keep the text embedding of each reference image description.

Revision ID: c1d2e3f4a5b6
Revises: ba0a57c6e4f5
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "ba0a57c6e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reference_images",
        sa.Column("text_embedding", postgresql.JSONB()),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_column("reference_images", "text_embedding", schema="marketing")
