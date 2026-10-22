"""Drop tables of removed email and creator workflows.

Revision ID: ff6b7c8d9e0f
Revises: fe5a6b7c8d9e
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ff6b7c8d9e0f"
down_revision: str | None = "fe5a6b7c8d9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "creator_evaluation_runs",
    "creator_outreach_runs",
    "email_health_runs",
    "email_production_jobs",
    "email_reports",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS marketing.{table}")


def downgrade() -> None:
    raise NotImplementedError("Dropped tables are not restored")
