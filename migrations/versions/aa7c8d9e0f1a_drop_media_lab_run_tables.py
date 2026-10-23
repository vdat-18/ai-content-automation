"""Drop tables of the removed Media Lab generation workflows.

Revision ID: aa7c8d9e0f1a
Revises: ff6b7c8d9e0f
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "aa7c8d9e0f1a"
down_revision: str | None = "ff6b7c8d9e0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "media_lab_image_runs",
    "media_lab_video_runs",
    "media_lab_video_projects",
    "media_lab_video_ad_jobs",
    "media_lab_planning_jobs",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS marketing.{table}")


def downgrade() -> None:
    raise NotImplementedError("Dropped tables are not restored")
