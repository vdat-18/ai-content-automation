"""Drop tables of removed creative loop, feedback and performance decision workflows.

Revision ID: aa1b2c3d4e5f
Revises: bb8d9e0f1a2b
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "aa1b2c3d4e5f"
down_revision: str | None = "bb8d9e0f1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "creative_loop_runs",
    "creative_feedback_runs",
    "performance_decision_runs",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS marketing.{table}")


def downgrade() -> None:
    raise NotImplementedError("Dropped tables are not restored")
