"""Persist selected-SKU Creative automation state in PostgreSQL.

Revision ID: d2c8a4f9e731
Revises: a9d4e2f6b731
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d2c8a4f9e731"
down_revision: str | None = "a9d4e2f6b731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marketing_creative_automation_states",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("package_ref", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "route IN ('manual', 'assisted', 'automated')",
            name=op.f("ck_marketing_creative_automation_states_valid_route"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_marketing_creative_automation_states_nonnegative_revision"),
        ),
        sa.PrimaryKeyConstraint(
            "request_id",
            name=op.f("pk_marketing_creative_automation_states"),
        ),
        schema="marketing",
    )
    op.create_index(
        "ix_marketing_creative_automation_states_status",
        "marketing_creative_automation_states",
        ["status", "updated_at"],
        unique=False,
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_creative_automation_states_status",
        table_name="marketing_creative_automation_states",
        schema="marketing",
    )
    op.drop_table("marketing_creative_automation_states", schema="marketing")
