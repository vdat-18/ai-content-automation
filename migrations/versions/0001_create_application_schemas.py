"""Create application schemas.

Revision ID: 0001
Revises: None
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.schema import CreateSchema, DropSchema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(CreateSchema("platform"))
    op.execute(CreateSchema("marketing"))


def downgrade() -> None:
    op.execute(DropSchema("marketing", cascade=True))
    op.execute(DropSchema("platform", cascade=True))
