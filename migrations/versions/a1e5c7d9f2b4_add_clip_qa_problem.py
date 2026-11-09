"""Record what the automatic check found wrong with a clip.

Revision ID: a1e5c7d9f2b4
Revises: c1d2e3f4a5b6
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1e5c7d9f2b4"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_clips",
        sa.Column("qa_problem", sa.Text(), server_default=sa.text("''"), nullable=False),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_column("product_clips", "qa_problem", schema="marketing")
