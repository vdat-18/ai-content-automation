"""Record what the automatic check found wrong with a keyframe.

Revision ID: b7d24f3b1c2a
Revises: b6c13e2a0f19
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d24f3b1c2a"
down_revision: str | None = "b6c13e2a0f19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_keyframes",
        sa.Column("qa_problem", sa.Text(), server_default=sa.text("''"), nullable=False),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_column("product_keyframes", "qa_problem", schema="marketing")
