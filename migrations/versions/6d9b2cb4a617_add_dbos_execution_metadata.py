"""add DBOS execution metadata

Revision ID: 6d9b2cb4a617
Revises: 25a2a00f13fd
Create Date: 2026-09-14 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6d9b2cb4a617"
down_revision: str | None = "25a2a00f13fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_commands",
        sa.Column(
            "execution_backend",
            sa.Text(),
            server_default="lease_worker",
            nullable=False,
        ),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("queue_name", sa.Text(), server_default="control", nullable=False),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("dispatch_generation", sa.Integer(), server_default="0", nullable=False),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("execution_id", sa.Text(), nullable=True),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.add_column(
        "execution_commands",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_check_constraint(
        "nonnegative_dispatch_generation",
        "execution_commands",
        "dispatch_generation >= 0",
        schema="platform",
    )


def downgrade() -> None:
    op.drop_constraint(
        "nonnegative_dispatch_generation",
        "execution_commands",
        schema="platform",
        type_="check",
    )
    for column in (
        "cancelled_at",
        "cancel_requested_at",
        "started_at",
        "execution_id",
        "dispatch_generation",
        "queue_name",
        "execution_backend",
    ):
        op.drop_column("execution_commands", column, schema="platform")
