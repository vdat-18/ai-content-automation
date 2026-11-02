"""Drop reference profile exclude keywords.

Revision ID: b06b7c8d9ea4
Revises: af5a6b7c8d93
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b06b7c8d9ea4"
down_revision: str | None = "af5a6b7c8d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("reference_profiles", "exclude_keywords", schema="marketing")


def downgrade() -> None:
    raise NotImplementedError("Dropped exclude keywords are not restored")
