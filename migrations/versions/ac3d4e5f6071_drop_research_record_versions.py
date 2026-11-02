"""Drop research record version history.

Revision ID: ac3d4e5f6071
Revises: ab2c3d4e5f60
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ac3d4e5f6071"
down_revision: str | None = "ab2c3d4e5f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing.research_record_versions")
    op.execute("ALTER TABLE marketing.research_records DROP COLUMN IF EXISTS version_count")


def downgrade() -> None:
    raise NotImplementedError("Dropped record history is not restored")
