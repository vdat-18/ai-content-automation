"""Reference images that passed review are live; humans only remove images.

Revision ID: b4af1c07d8e8
Revises: b39e0fb6c7d7
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4af1c07d8e8"
down_revision: str | None = "b39e0fb6c7d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE marketing.reference_images SET status = 'live' WHERE status IN ('new', 'approved')"
    )
    op.alter_column(
        "reference_images",
        "status",
        server_default=sa.text("'pending'"),
        schema="marketing",
    )


def downgrade() -> None:
    raise NotImplementedError("Reference image statuses are not restored")
