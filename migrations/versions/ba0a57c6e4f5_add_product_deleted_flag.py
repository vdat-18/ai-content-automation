"""Mark products the user deleted, so the collector does not bring them back.

Revision ID: ba0a57c6e4f5
Revises: b9f46b5d3e4c
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ba0a57c6e4f5"
down_revision: str | None = "b9f46b5d3e4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_products",
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_column("marketplace_products", "deleted", schema="marketing")
