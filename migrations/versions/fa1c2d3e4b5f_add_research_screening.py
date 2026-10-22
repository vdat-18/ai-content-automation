"""add automatic research screening state

Revision ID: fa1c2d3e4b5f
Revises: f9a0b1c2d303
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fa1c2d3e4b5f"
down_revision: str | None = "f9a0b1c2d303"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_records",
        sa.Column(
            "screening_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'kept'"),
        ),
        schema="marketing",
    )
    op.create_check_constraint(
        "valid_research_screening_status",
        "research_records",
        "screening_status IN ('kept', 'auto_filtered', 'unavailable')",
        schema="marketing",
    )
    op.create_index(
        "ix_research_records_screening_status",
        "research_records",
        ["screening_status"],
        schema="marketing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_records_screening_status",
        table_name="research_records",
        schema="marketing",
    )
    op.drop_constraint(
        "valid_research_screening_status",
        "research_records",
        schema="marketing",
        type_="check",
    )
    op.drop_column("research_records", "screening_status", schema="marketing")
